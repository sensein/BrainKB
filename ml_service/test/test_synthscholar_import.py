"""SynthScholar review import: what an uploaded output directory keeps, the local
run's provenance, and who the caller is (the identity fix that makes ownership
work). No database: the store is exercised by an integration run against Postgres.

    pytest ml_service/test/test_synthscholar_import.py
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.synth_scholar import imports as im  # noqa: E402
from core import security  # noqa: E402

REVIEW = json.dumps({"research_question": "RQ", "protocol": {"title": "T"}}).encode()


def test_keeps_the_review_and_skips_intermediate_work():
    plan = im.plan_import([
        ("output/review.json", REVIEW), ("output/review.pdf", b"%PDF"), ("output/figures/fig_prisma.svg", b"<svg/>"),
        ("output/work/autoscreen.py", b"x"), ("output/.DS_Store", b"x"), ("output/review.screening.csv", b"a,b"),
    ])
    assert plan.root == "output"
    assert [f.path for f in plan.files] == ["figures/fig_prisma.svg", "review.json", "review.pdf", "review.screening.csv"]
    assert {f.path: f.kind for f in plan.files} == {
        "figures/fig_prisma.svg": "figure", "review.json": "review_result",
        "review.pdf": "manuscript_pdf", "review.screening.csv": "table"}
    assert plan.skipped == [{"path": "work/autoscreen.py", "reason": "intermediate files (work/)"}]
    assert plan.get("review.pdf").media_type == "application/pdf"
    assert len(plan.get("review.json").sha256) == 64


def test_root_is_the_folder_holding_review_json():
    plan = im.plan_import([("runs/a/output/review.json", REVIEW), ("runs/a/output/review.md", b"#"),
                           ("runs/a/notes.txt", b"outside")])
    assert plan.root == "runs/a/output"
    assert [f.path for f in plan.files] == ["review.json", "review.md"]
    assert plan.skipped == [{"path": "runs/a/notes.txt", "reason": "outside the review's folder"}]


@pytest.mark.parametrize("uploads,message", [
    ([("x/notes.md", b"hi")], "no review.json"),
    ([("../../etc/review.json", REVIEW)], "no review.json"),           # traversal is dropped, not followed
    ([("/abs/review.json", REVIEW)], "no review.json"),
])
def test_rejects_what_is_not_an_output_directory(uploads, message):
    with pytest.raises(im.ImportError_, match=message):
        im.plan_import(uploads)


def test_local_run_provenance_keeps_numbers_and_queries_not_local_paths():
    plan = im.plan_import([
        ("o/review.json", REVIEW),
        ("o/search_log.json", json.dumps({"PubMed": {"query": "q", "count": 12, "date": "2026-10-15"}}).encode()),
        ("o/review.citations.json", json.dumps({"summary": {"references": 3, "reference_status": {"verified": 2},
                                                             "file": "/Users/someone/out/review.json"}}).encode()),
        ("o/url_verification.json", json.dumps({"https://a": {"status": 200, "checked_at": "2026-10-15T00:00:00Z"},
                                                "https://b": {"status": 404}}).encode()),
        ("o/review.manuscript.check.json", json.dumps({"manuscript": "/Users/someone/out/review.manuscript.md",
                                                       "body_words": 8247, "figures": 8}).encode()),
    ])
    lr = im.local_run_provenance(plan)
    assert lr["search_log"] == [{"database": "PubMed", "query": "q", "count": 12, "date": "2026-10-15"}]
    assert lr["citation_verification"] == {"references": 3, "reference_status": {"verified": 2}}
    assert lr["url_verification"]["checked"] == 2 and lr["url_verification"]["reachable"] == 1
    assert lr["manuscript_check"] == {"body_words": 8247, "figures": 8}
    assert "/Users/" not in json.dumps(lr)


def _identity(payload, is_sso, row):
    async def get_user(email):
        return row
    with patch.object(security, "get_user", get_user):
        return asyncio.run(security.identity_from_token(payload, is_sso))


def test_identity_is_a_dict_with_token_roles():
    user = _identity({"sub": "a@x.org", "roles": ["Admin"], "scopes": ["admin"]}, True, {"id": 7, "password": "h"})
    assert user["email"] == "a@x.org" and user["roles"] == ["Admin"] and user["id"] == 7
    assert "password" not in user


def test_sso_user_without_an_active_local_row_is_still_the_caller():
    assert _identity({"sub": "oauth@x.org"}, True, False)["email"] == "oauth@x.org"


def test_legacy_token_still_needs_an_active_row():
    assert _identity({"sub": "old@x.org"}, False, False) is None


def test_what_the_browser_left_out_is_recorded_not_trusted():
    plan = im.plan_import([("review.json", REVIEW)], client_skipped=[
        {"path": "work/screen.py", "reason": "intermediate files (work/)"},
        {"path": "../../etc/passwd", "reason": "x"}, "junk"])
    assert plan.skipped == [{"path": "work/screen.py", "reason": "intermediate files (work/)", "by": "client"}]
    assert [f.path for f in plan.files] == ["review.json"]
