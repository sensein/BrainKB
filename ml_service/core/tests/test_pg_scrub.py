"""Regression test — Postgres-illegal control bytes must be scrubbed before write.

Reproduces the failure mode reported in the user's incident::

    asyncpg.exceptions.UntranslatableCharacterError:
    unsupported Unicode escape sequence
    DETAIL: \\u0000 cannot be converted to text.

A NUL byte (or other forbidden C0 control byte) was leaking into a 4 MB
``result_json`` payload from PDF full-text extraction and aborting the
``mark_completed`` UPDATE.  ``_scrub_pg_unsafe`` is the defensive scrubber at
every BrainKB write boundary; this test pins its contract.
"""

from __future__ import annotations

import json

from core.synth_scholar.store import _scrub_pg_unsafe


# ── Strings ───────────────────────────────────────────────────────────────


def test_strips_nul_byte():
    assert _scrub_pg_unsafe("hello\x00world") == "helloworld"


def test_strips_other_forbidden_c0_bytes():
    """All C0 except \\t \\n \\r are illegal in Postgres TEXT."""
    raw = "BEL \x07 BS \x08 VT \x0b FF \x0c SO \x0e SI \x0f"
    out = _scrub_pg_unsafe(raw)
    assert out == "BEL  BS  VT  FF  SO  SI "


def test_preserves_legitimate_whitespace():
    """\\t \\n \\r are legitimate prose whitespace and must NOT be touched."""
    raw = "first\nsecond\tthird\rfourth"
    assert _scrub_pg_unsafe(raw) == raw


def test_clean_string_passthrough():
    """No regex overhead for clean strings (fast path)."""
    s = "ordinary prose with no control bytes"
    assert _scrub_pg_unsafe(s) is s or _scrub_pg_unsafe(s) == s


# ── Container types ───────────────────────────────────────────────────────


def test_walks_lists_recursively():
    log = [
        "[2026-05-05] entry one",
        "[2026-05-05] entry with NUL \x00 buried",
        "[2026-05-05] entry with BEL \x07",
    ]
    out = _scrub_pg_unsafe(log)
    assert out == [
        "[2026-05-05] entry one",
        "[2026-05-05] entry with NUL  buried",
        "[2026-05-05] entry with BEL ",
    ]


def test_walks_dicts_recursively():
    """Reproduces the actual result_json shape from the incident."""
    dirty = {
        "research_question": "ADHD biomarkers",
        "evidence_spans": [
            {"text": "PDF text with \x00 from extractor", "paper_pmid": "1"},
            {"text": "good prose\nwith newlines", "paper_pmid": "2"},
        ],
        "synthesis_text": "long body with \x00 at char 1234",
        "flow": {"total_identified": 247},
    }
    out = _scrub_pg_unsafe(dirty)
    assert out["evidence_spans"][0]["text"] == "PDF text with  from extractor"
    assert "\x00" not in out["synthesis_text"]
    # Whitespace preserved on the clean spans:
    assert "\n" in out["evidence_spans"][1]["text"]


def test_serialised_output_is_postgres_safe():
    """The final smoke test — feed the scrubbed dict through json.dumps and
    confirm the serialisation never contains a forbidden byte. This is the
    exact data shape asyncpg sends to Postgres for JSONB columns."""
    dirty = {
        "a": "x\x00y",
        "b": ["\x07", "\x0c", "fine"],
        "c": {"d": "with \x01 SOH and \x1f US"},
    }
    serialised = json.dumps(_scrub_pg_unsafe(dirty))
    forbidden = {chr(c) for c in range(0x20)} - {"\t", "\n", "\r"}
    for ch in forbidden:
        # json.dumps escapes \x00 as "\\u0000" (six chars), so we check for
        # the raw byte AND its escaped form.
        assert ch not in serialised, f"raw byte {ord(ch):#04x} survived"
        assert f"\\u{ord(ch):04x}" not in serialised, (
            f"escaped \\u{ord(ch):04x} survived in {serialised!r}"
        )


# ── Non-string types passthrough ─────────────────────────────────────────


def test_int_unchanged():
    assert _scrub_pg_unsafe(247) == 247


def test_none_unchanged():
    assert _scrub_pg_unsafe(None) is None


def test_bool_unchanged():
    assert _scrub_pg_unsafe(True) is True
    assert _scrub_pg_unsafe(False) is False


def test_dict_keys_left_alone():
    """Keys are Pydantic field names — they can't legally contain control bytes,
    so we don't pay the cost of scrubbing every key on every write."""
    out = _scrub_pg_unsafe({"clean_key": "value with \x00 NUL"})
    assert "clean_key" in out
    assert out["clean_key"] == "value with  NUL"


def test_tuple_walked():
    """Tuples are rare in JSON-able payloads but we support them defensively."""
    out = _scrub_pg_unsafe(("a\x00", "b"))
    assert out == ("a", "b")


def test_empty_containers():
    assert _scrub_pg_unsafe([]) == []
    assert _scrub_pg_unsafe({}) == {}
    assert _scrub_pg_unsafe("") == ""
