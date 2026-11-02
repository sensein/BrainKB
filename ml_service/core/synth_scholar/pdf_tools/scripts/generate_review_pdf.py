#!/usr/bin/env python3
"""Render an exported review (``review.md``) to PDF via pandoc.

``export_review.py`` writes the review as Markdown; this turns that file — and
optionally its sidecar exports as appendices — into one PDF. It does not
re-run or re-serialise anything: the PDF is a rendering of ``review.md``.

What a SynthScholar review needs beyond a plain pandoc call:

* **Title and numbering.** The review opens with ``# <title>`` and numbers its
  own sections (``## 1. Introduction``). The H1 becomes the PDF title and,
  when it is the only H1, the ``##`` sections become top-level.
  ``--number-sections`` is off by default (it would print "1 1. Introduction").
* **Tables.** Charting / narrative tables put line breaks in cells as
  ``<br>``, which TeX and Typst drop; they are rewritten to each engine's own
  line break. Tables wrap at the text width instead of running off the page.
* **Characters.** TeX's default font has no ``≥ μ κ α →``; they vanish with
  only a log line. On TeX engines the script picks an installed font that
  covers the characters the review actually uses (``fc-list``), maps
  ``✓ ✗ ⚠`` to TeX symbols, and reports any glyph still missing.
* **Citation gate.** If ``verify_citations.py`` has been run
  (``<stem>.citations.json`` next to the Markdown, or ``--citations``) and
  found errors, or its report is older than the Markdown, the build stops.
  ``--allow-citation-errors`` overrides; with no report at all it warns.
* **Verified reference list.** ``--references vancouver`` swaps the review's
  References list for ``<stem>.references.vancouver.md``, the list
  ``verify_citations.py --style vancouver`` rendered from registry metadata.
* **Appendices.** ``--include charting appraisal per-group narrative citations``
  appends ``<stem>.charting.md`` etc., each on a new page. A sidecar whose
  title already heads a section of the review (``appraisal`` duplicates its
  *Appendix C*) is skipped rather than printed twice.

Engines, best first: xelatex, lualatex, tectonic (self-contained TeX), pdflatex,
typst (no TeX at all), then the HTML engines weasyprint / wkhtmltopdf / prince.
``[@key]`` citations, if a hand-edited Markdown has them, are processed with
``--citeproc`` against a sibling or YAML-declared ``.bib`` and a CSL style
(``--citation-style``, fetched from the official CSL repository when needed).

Usage:
    python generate_review_pdf.py out/review.md
    python generate_review_pdf.py out/review.md --references vancouver \\
        --include per-group citations -o out/review.pdf
    python generate_review_pdf.py out/review.md --pdf-engine typst --dry-run
    python generate_review_pdf.py --batch ~/reviews           # every review without an up-to-date PDF
    python generate_review_pdf.py --batch out/ --force       # rebuild them all
    python generate_review_pdf.py --check-deps

Needs ``pandoc`` and one engine; stdlib only otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prisma_flow  # noqa: E402  (the PRISMA 2020 flow diagram)

# Engines pandoc can drive, best first. xelatex/lualatex give proper Unicode;
# tectonic is self-contained (fetches its own TeX packages on first run);
# pdflatex is last among TeX engines because its Unicode handling is weakest.
LATEX_ENGINES = ["xelatex", "lualatex", "tectonic", "pdflatex"]
UNICODE_TEX = {"xelatex", "lualatex", "tectonic"}   # take a system font (fontspec)
TYPST_ENGINES = ["typst"]
HTML_ENGINES = ["weasyprint", "wkhtmltopdf", "prince"]
ALL_ENGINES = LATEX_ENGINES + TYPST_ENGINES + HTML_ENGINES
CSL_URL = "https://raw.githubusercontent.com/citation-style-language/styles/master/{}.csl"
# Common names that are not file names in the CSL repository.
CSL_ALIASES = {"vancouver": "nlm-citation-sequence", "nlm": "nlm-citation-sequence",
               "ama": "american-medical-association", "chicago": "chicago-author-date",
               "harvard": "harvard-cite-them-right"}

# Sidecar exports that can be appended, by export_review.py's file suffix.
SIDECARS = {
    "charting": ".charting.md",
    "appraisal": ".appraisal.md",
    "per-group": ".per-group.md",
    "narrative": ".narrative.md",
    "citations": ".citations.md",   # verify_citations.py's report
}

# Symbols the exporters emit that most text fonts lack, mapped to TeX symbols.
TEX_SYMBOLS = {
    "✓": r"`$\checkmark$`{=latex}",
    "✔": r"`$\checkmark$`{=latex}",
    "✗": r"`$\times$`{=latex}",
    "✘": r"`$\times$`{=latex}",
    "⚠": r"`\textbf{!}`{=latex}",
    "⚡": "",
}
# Text fonts with wide coverage, best-looking first. The first installed one
# that covers every character the review uses becomes the TeX main font.
UNICODE_FONTS = ["STIX Two Text", "DejaVu Serif", "Noto Serif", "Libertinus Serif",
                 "FreeSerif", "STIXGeneral", "Arial Unicode MS", "DejaVu Sans", "Noto Sans"]
# One raw inline per output family; pandoc keeps only the one for the target.
LINE_BREAK = r"`\newline{}`{=latex}`#linebreak()`{=typst}"
PAGE_BREAK = ("\n```{=latex}\n\\newpage\n```\n\n```{=typst}\n#pagebreak()\n```\n\n"
              '```{=html}\n<div style="page-break-before: always"></div>\n```\n')
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)")
HEADING = re.compile(r"^(#{1,6})(\s+)(.*?)\s*#*\s*$")
RULE = re.compile(r"^ {0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
# Pandoc wraps a pipe table (cells reflow to the text width) only when one of
# its lines is longer than --columns; review tables are long, so set it low.
WRAP_COLUMNS = 40

# A4 text block at 2 cm margins, in px at 96 dpi (pandoc's default image dpi):
# an image larger than this is scaled down to fit instead of running off the page.
TEXT_W_PX = 642     # 17.0 cm
TEXT_H_PX = 870     # ~23 cm, leaving room for a caption and the running header
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(\s+"[^"]*")?\s*\)(\{[^}]*\})?')

HTML_CSS = """
img { max-width: 100%; height: auto; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; line-height: 1.35; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 0.6em 0; }
th, td { border: 1px solid #bbb; padding: 3px 5px; vertical-align: top; }
th { background: #f0f0f0; }
code, pre { font-size: 8.5pt; }
pre { white-space: pre-wrap; }
@page { size: A4; margin: 2cm; }
"""


# ─────────────────────────── tooling ────────────────────────────

def engine_family(engine: str) -> str:
    """``/Library/TeX/texbin/xelatex`` → ``xelatex``: options key off the name."""
    name = Path(engine).name.lower()
    return name[:-4] if name.endswith(".exe") else name


def tex_dirs() -> list[str]:
    """Where TeX installs put their binaries when the installer didn't add them to PATH.

    MacTeX/TeX Live often lands in /usr/local/texlive/<year>/bin/<arch> with only a
    /Library/TeX/texbin link, which a non-login shell (an agent's) may not have on
    PATH; the engine is installed, just not found. Newest year first.
    """
    import glob
    home = Path.home()
    pats = ["/Library/TeX/texbin", "/usr/local/texlive/*/bin/*", "/opt/texlive/*/bin/*",
            str(home / "Library/TinyTeX/bin/*"), str(home / ".TinyTeX/bin/*"),
            str(home / "texlive/*/bin/*"), "C:/texlive/*/bin/*"]
    found: list[str] = []
    for pat in pats:
        found += sorted((d for d in glob.glob(pat) if os.path.isdir(d)), reverse=True)
    return found


def which_tex(name: str) -> Optional[str]:
    """``shutil.which`` that also looks in the usual TeX install directories."""
    hit = shutil.which(name)
    if hit or Path(name).is_absolute():
        return hit
    for d in tex_dirs():
        hit = shutil.which(name, path=d)
        if hit:
            return hit
    return None


def find_engine(preferred: Optional[str] = None) -> Optional[str]:
    """First available PDF engine. An explicit choice is honoured or refused, not swapped."""
    if preferred:
        return which_tex(preferred)
    return next((hit for e in ALL_ENGINES if (hit := which_tex(e))), None)


ACM_CLASS_DIR = Path(__file__).resolve().parent.parent / "assets" / "acmart"


def acmart_available(engine: str) -> bool:
    """The ACM class is at hand: bundled in assets/acmart/ (put on the TeX path), else installed."""
    if (ACM_CLASS_DIR / "acmart.cls").is_file() or engine_family(engine) == "tectonic":
        return True
    kpse = shutil.which("kpsewhich", path=str(Path(engine).parent)) or which_tex("kpsewhich")
    if not kpse:
        return False
    r = subprocess.run([kpse, "acmart.cls"], capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and bool(r.stdout.strip())


def csl_cache() -> Optional[Path]:
    """First writable cache directory, or None ($HOME is read-only in some sandboxes)."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    candidates = [Path(xdg) / "csl"] if xdg else []
    candidates += [Path.home() / ".cache" / "csl", Path(tempfile.gettempdir()) / "csl-cache"]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            continue
    return None


def resolve_csl(style: str, near: Path) -> Optional[Path]:
    """Style name → CSL file: explicit path, sibling, cwd, cache, then the CSL repository."""
    if style.endswith(".csl"):
        p = Path(style)
        return p if p.is_file() else None
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", style):
        print(f"  warning: '{style}' is not a CSL style id; using pandoc's default style",
              file=sys.stderr)
        return None
    style = CSL_ALIASES.get(style, style)
    cache = csl_cache()
    for c in [near / f"{style}.csl", Path.cwd() / f"{style}.csl"] + ([cache / f"{style}.csl"] if cache else []):
        if c.is_file():
            return c
    try:
        with urllib.request.urlopen(CSL_URL.format(style), timeout=20) as r:
            body = r.read()
    except (urllib.error.URLError, OSError) as e:
        print(f"  warning: no CSL for '{style}' ({e}); using pandoc's default style — style ids "
              "are the file names at https://github.com/citation-style-language/styles", file=sys.stderr)
        return None
    if b"<style" not in body[:2000]:
        print(f"  warning: '{style}' did not download as a CSL style; using pandoc's default",
              file=sys.stderr)
        return None
    # Write to a temp file and rename, so an interrupted download never leaves a
    # truncated style in the cache to break every later build.
    dest_dir = cache or Path(tempfile.gettempdir())
    fd, tmp = tempfile.mkstemp(suffix=".csl", dir=dest_dir)
    with os.fdopen(fd, "wb") as f:
        f.write(body)
    target = dest_dir / f"{style}.csl"
    os.replace(tmp, target)
    print(f"  fetched CSL style '{style}' -> {target}", file=sys.stderr)
    return target


def find_bibliography(md: Path) -> Optional[Path]:
    for name in (f"{md.stem}.bib", "references.bib", "bibliography.bib"):
        p = md.parent / name
        if p.is_file():
            return p
    return None


def yaml_keys(text: str) -> set[str]:
    """Keys of a leading YAML block, so the author's own title/bibliography win."""
    m = re.match(r"^---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*\n", text, re.S)
    return set(re.findall(r"^([A-Za-z][\w-]*)\s*:", m.group(1), re.M)) if m else set()


def _font_families(chars: str) -> list[str]:
    """Installed font families covering every character in ``chars`` (fontconfig)."""
    if not shutil.which("fc-list"):
        return []
    charset = " ".join(f"{ord(c):x}" for c in chars)
    try:
        out = subprocess.run(["fc-list", f":charset={charset}", "family"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [fam for line in out.splitlines() for fam in line.split(",") if fam.strip()]


def pick_main_font(text: str) -> tuple[Optional[str], str]:
    """(font, chars it must cover) for a TeX engine, or (None, "") when Latin Modern will do.

    Latin Modern covers Latin-1 plus common typographic punctuation; anything
    beyond that (Greek, maths relations, arrows) needs a Unicode font.
    """
    needed = "".join(sorted({c for c in text if ord(c) > 0x17F and c not in TEX_SYMBOLS
                             and c not in "‘’“”–—…•′″€"
                             and unicodedata.category(c)[0] in "LSNP"}))
    if not needed:
        return None, ""
    have = set(_font_families(needed[:80]))
    return next((f for f in UNICODE_FONTS if f in have), None), needed


# ─────────────────────────── Markdown preparation ────────────────────────────

def _outside_fences(text: str, fn: Callable[[str], str]) -> str:
    """Apply ``fn`` to each line not inside a fenced code block.

    A fence closes only on the same character, at least as long as it opened,
    with nothing after it — so a ``` line inside a ~~~ block stays code.
    """
    out, fence = [], None
    for line in text.split("\n"):
        if fence is None:
            m = FENCE_OPEN.match(line)
            if m:
                fence = m.group(1)
                out.append(line)
            else:
                out.append(fn(line))
        else:
            out.append(line)
            s = line.strip()
            if s and set(s) == {fence[0]} and len(s) >= len(fence):
                fence = None
    return "\n".join(out)


def _outside_code_spans(line: str, fn: Callable[[str], str]) -> str:
    """Apply ``fn`` to the parts of a line outside inline `code` spans."""
    out, pos = [], 0
    for m in CODE_SPAN.finditer(line):
        out += [fn(line[pos:m.start()]), m.group()]
        pos = m.end()
    out.append(fn(line[pos:]))
    return "".join(out)


def headings(text: str) -> list[tuple[int, str, int]]:
    """(level, text, line index) of every ATX heading outside code fences."""
    found: list[tuple[int, str, int]] = []
    fence = None
    for i, line in enumerate(text.split("\n")):
        if fence is None:
            m = FENCE_OPEN.match(line)
            if m:
                fence = m.group(1)
            elif (h := HEADING.match(line)):
                found.append((len(h.group(1)), h.group(3), i))
        else:
            s = line.strip()
            if s and set(s) == {fence[0]} and len(s) >= len(fence):
                fence = None
    return found


def shift_headings(text: str, by: int) -> str:
    """Move every heading ``by`` levels (outside fences), clamped to 1–6."""
    return _outside_fences(text, lambda ln: re.sub(
        r"^(#{1,6})(?=\s)", lambda m: "#" * max(1, min(6, len(m.group(1)) + by)), ln))


def lift_title(text: str) -> tuple[str, Optional[str]]:
    """Take a leading ``# Title`` out of the body; (body, title or None).

    When that was the document's only H1, its ``##`` sections are promoted to
    top level. When other H1s follow, levels are left alone — promoting would
    push those H1s below level 1, where pandoc turns them into paragraphs.
    """
    hs = headings(text)
    lines = text.split("\n")
    first_text = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if not hs or hs[0][0] != 1 or hs[0][2] != first_text:
        return text, None
    title = hs[0][1]
    body = "\n".join(lines[:hs[0][2]] + lines[hs[0][2] + 1:])
    if not any(level == 1 for level, _, _ in hs[1:]):
        body = shift_headings(body, -1)
    return body, title


def neutralise_rules(text: str, keep_front_matter: bool) -> str:
    """Turn bare ``---`` rules into ``* * *``.

    The exporters separate sections with ``---``. Pandoc reads a ``---`` line
    followed by text ("---\\n*Generated: …*") as the start of a YAML block — and
    a sidecar appended mid-document is full of them — so the build fails with a
    YAML error. ``* * *`` is the same rule with no other reading. A genuine
    front-matter block at the very top of the review is kept.
    """
    lines = text.split("\n")
    start = 0
    if keep_front_matter and lines and lines[0].strip() == "---":
        close = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
        if close is not None:
            start = close + 1
    head, rest = lines[:start], "\n".join(lines[start:])
    body = _outside_fences(rest, lambda ln: "\n* * *\n" if ln.strip() == "---" else ln)
    return "\n".join(head + [body]) if head else body


def for_engine(text: str, family: str) -> str:
    """Rewrite the HTML-isms and symbols an engine family can't print."""
    if family in HTML_ENGINES:
        return text

    def fix(seg: str) -> str:
        # a function, not a string: re.sub would read "\n" in "\newline" as a newline
        seg = re.sub(r"<br\s*/?>", lambda _: LINE_BREAK, seg, flags=re.I)
        seg = re.sub(r"</?(?:details|summary)[^>]*>", "", seg, flags=re.I)
        if family in LATEX_ENGINES:
            for sym, tex in TEX_SYMBOLS.items():
                seg = seg.replace(sym, tex)
        return seg
    return _outside_fences(text, lambda ln: _outside_code_spans(ln, fix))


def replace_references(text: str, styled: str) -> tuple[str, bool]:
    """Swap the list under ``## References`` for a styled one; (text, replaced?).

    Only the list is replaced: it ends at the next heading of any level or the
    next rule, so a footer or appendix after it survives even when References
    is the last ``##`` section.
    """
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(r"^##\s+References\s*$", ln)), None)
    if start is None:
        return text, False
    end = next((i for i in range(start + 1, len(lines))
                if HEADING.match(lines[i]) or RULE.match(lines[i])), len(lines))
    body = styled.strip("\n").split("\n")
    if body and body[0].startswith("## "):  # verify_citations' "## References (style)"
        body = body[1:]
    new = ["## References", ""] + body + [""]
    return "\n".join(lines[:start] + new + lines[end:]), True


def _norm_title(s: str) -> str:
    s = re.sub(r"^appendix\s+[a-z0-9]+\s*[:.\-—]\s*", "", s.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def base_stem(md: Path) -> str:
    """``review.manuscript.md`` → ``review``: the manuscript shares the review's siblings."""
    return md.stem[:-len(".manuscript")] if md.stem.endswith(".manuscript") else md.stem


def citation_gate(md: Path, report: Optional[Path], allow: bool) -> Optional[str]:
    """Refusal message if the citation report has errors or predates ``md``."""
    report = report or md.with_name(f"{base_stem(md)}.citations.json")
    if not report.is_file():
        print(f"  warning: {report} not found — citations unverified; run "
              f"verify_citations.py on {base_stem(md)}.json first (or point --citations at its report)",
              file=sys.stderr)
        return None
    try:
        summary = json.loads(report.read_text(encoding="utf-8")).get("summary") or {}
    except (OSError, json.JSONDecodeError) as e:
        return f"{report.name} is unreadable ({e}); re-run verify_citations.py"
    problems = []
    # The report verifies the review JSON's references; a manuscript re-assembled
    # from the same JSON is not new citations. Compare against the JSON when present.
    basis = md.with_name(f"{base_stem(md)}.json")
    basis = basis if basis.is_file() else md
    if report.stat().st_mtime < basis.stat().st_mtime:
        problems.append(f"{report.name} is older than {basis.name} — it describes an earlier "
                        "export; re-run verify_citations.py on the re-exported review.json")
    errors = int(summary.get("errors") or 0)
    if errors:
        codes = ", ".join(f"{k} {v}" for k, v in (summary.get("by_code") or {}).items())
        problems.append(f"{report.name} reports {errors} citation error(s) ({codes})")
    if problems and not allow:
        return ("\n  ".join(problems) + "\n  Fix them (see references/citation_verification.md) "
                "and re-export, or pass --allow-citation-errors to build anyway.")
    for p in problems:
        print(f"  warning: building anyway — {p}", file=sys.stderr)
    return None


def image_size(path: Path) -> Optional[tuple[float, float]]:
    """(width, height) in px at 96 dpi for PNG / JPEG / GIF / SVG / PDF, else None."""
    try:
        head = path.read_bytes()[:65536] if path.suffix.lower() != ".svg" else path.read_bytes()[:20000]
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) >= 24:
        return float(int.from_bytes(head[16:20], "big")), float(int.from_bytes(head[20:24], "big"))
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return float(int.from_bytes(head[6:8], "little")), float(int.from_bytes(head[8:10], "little"))
    if head[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF:
                i += 1
                continue
            marker, seglen = head[i + 1], int.from_bytes(head[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return float(int.from_bytes(head[i + 7:i + 9], "big")), float(int.from_bytes(head[i + 5:i + 7], "big"))
            i += 2 + seglen
        return None
    if head[:4] == b"%PDF":
        m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", head)
        if m:
            x0, y0, x1, y1 = (float(v) for v in m.groups())
            return (x1 - x0) * 96 / 72, (y1 - y0) * 96 / 72
        return None
    text = head.decode("utf-8", "replace")
    if "<svg" in text:
        tag = re.search(r"<svg\b[^>]*>", text, re.S)
        if not tag:
            return None
        attrs = tag.group(0)

        def length(name: str) -> Optional[float]:
            m = re.search(rf'\b{name}\s*=\s*"([\d.]+)\s*(px|pt|mm|cm|in)?"', attrs)
            if not m:
                return None
            scale = {"px": 1, None: 1, "pt": 96 / 72, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}
            return float(m.group(1)) * scale[m.group(2)]
        w, h = length("width"), length("height")
        if w and h:
            return w, h
        vb = re.search(r'viewBox\s*=\s*"[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)"', attrs)
        if vb:
            return float(vb.group(1)), float(vb.group(2))
    return None


def fit_images(text: str, base_dirs: list[Path]) -> tuple[str, list[str]]:
    """Give every local image that would overflow the page a width/height cap.

    Without one, an image wider than the text block runs off the page edge in
    TeX and Typst, and a tall one is cut at the page foot. Images that fit are
    left at their natural size (a blanket ``width=100%`` would blow small ones
    up); an explicit width or height the author set is never touched. Fenced
    code is left alone.
    """
    notes: list[str] = []

    def fix(line: str) -> str:
        def one(m: re.Match) -> str:
            alt, target, title, attrs = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
            if re.search(r"\b(width|height)\s*=", attrs) or re.match(r"^(https?:|data:)", target):
                return m.group(0)
            path = next((d / target for d in base_dirs if (d / target).is_file()),
                        Path(target) if Path(target).is_absolute() else None)
            size = image_size(path) if path else None
            cap = ""
            if size is None:
                cap = "width=100%" if path else ""      # local but unreadable: fit to be safe
            else:
                w, h = size
                scale = min(1.0, TEXT_W_PX / w) if w else 1.0
                if h * scale > TEXT_H_PX:
                    cap = f"height={TEXT_H_PX * 2.54 / 96:.1f}cm"
                elif w > TEXT_W_PX:
                    cap = "width=100%"
            if not cap:
                return m.group(0)
            notes.append(f"fitted {Path(target).name} ({cap})")
            inner = attrs[1:-1].strip() if attrs else ""
            return f"![{alt}]({target}{title}){{{(inner + ' ' if inner else '') + cap}}}"
        return IMAGE_RE.sub(one, line)

    return _outside_fences(text, fix), notes


def prepare_images(text: str, base_dirs: list[Path], family: str, tmp: Path) -> tuple[str, list[str]]:
    """Make every local image resolvable from anywhere, and printable by the engine.

    Paths become absolute, so the intermediate ``.tex`` compiles wherever it is
    written. On TeX engines an SVG is converted to PDF first: LaTeX cannot
    include SVG, and leaving it to the engine is what breaks builds.
    """
    notes: list[str] = []
    converted: dict[Path, Optional[Path]] = {}

    def fix(line: str) -> str:
        def one(m: re.Match) -> str:
            alt, target, title, attrs = m.group(1), m.group(2), m.group(3) or "", m.group(4) or ""
            if re.match(r"^(https?:|data:)", target):
                return m.group(0)
            path = next((d / target for d in base_dirs if (d / target).is_file()),
                        Path(target) if Path(target).is_absolute() and Path(target).is_file() else None)
            if path is None:
                notes.append(f"WARNING: image not found: {target}")
                return m.group(0)
            path = path.resolve()
            if family in LATEX_ENGINES and path.suffix.lower() == ".svg":
                if path not in converted:
                    pdf = tmp / f"img_{len(converted)}_{path.stem}.pdf"
                    converted[path] = pdf if prisma_flow.svg_to_pdf(path, pdf) else None
                if converted[path] is None:
                    notes.append(f"WARNING: {path.name} is SVG and no converter is installed "
                                 "(rsvg-convert, cairosvg or typst); it is left out of the PDF")
                    return f"*[Figure file {path.name} could not be converted for this engine]*"
                path = converted[path]
            return f"![{alt}]({path}{title}){attrs}"
        return IMAGE_RE.sub(one, line)

    return _outside_fences(text, fix), notes


def estimate_pages(text: str) -> tuple[float, list[tuple[str, float]]]:
    """Pages the Markdown will take, and the heaviest sections, before rendering.

    The template's estimator: words/550 + table rows/45 + 0.4 per image. Rendering
    first and finding out after is how a 1,300-page PDF happens.
    """
    sections: dict[str, list[int]] = {}
    current, fence = "front matter", False
    for line in text.split("\n"):
        if FENCE_OPEN.match(line):
            fence = not fence
        h = None if fence else HEADING.match(line)
        if h and len(h.group(1)) <= 2:
            current = h.group(3)
        w, r, i = sections.setdefault(current, [0, 0, 0])
        if line.lstrip().startswith("|"):
            sections[current][1] += 1
        elif line.lstrip().startswith("!["):
            sections[current][2] += 1
        else:
            sections[current][0] += len(line.split())
    per = [(name, w / 550 + r / 45 + 0.4 * i) for name, (w, r, i) in sections.items()]
    return sum(p for _, p in per), sorted(per, key=lambda kv: -kv[1])


def pdf_page_count(pdf: Path) -> Optional[int]:
    """Pages in a PDF: the page tree's ``/Count``, also inside compressed object streams.

    Counting ``/Type /Page`` objects over-counts some writers and misses others
    (xdvipdfmx packs objects into compressed streams); the root ``/Pages`` node's
    ``/Count`` is the total either way. Stdlib only.
    """
    import zlib
    try:
        data = pdf.read_bytes()
    except OSError:
        return None
    chunks = [data]
    for m in re.finditer(rb"stream\r?\n", data):
        end = data.find(b"endstream", m.end())
        if end > 0:
            try:
                chunks.append(zlib.decompress(data[m.end():end]))
            except zlib.error:
                pass
    counts = [int(c) for chunk in chunks
              for c in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", chunk)
              for c in c if c]
    return max(counts) if counts else None


def insert_flow_diagram(text: str, image: Path) -> tuple[str, bool]:
    """Put the diagram right under the PRISMA flow heading (the counts table stays)."""
    if re.search(r"!\[[^\]]*\]\([^)]*(prisma|flow)[^)]*\)", text, re.I):
        return text, True      # the manuscript already carries it (assemble_manuscript.py)
    figure = f"\n![]({image}){{width=100%}}\n\n**Figure.** PRISMA 2020 flow diagram.\n"
    hs = headings(text)
    target = next((i for lvl, t, i in hs if re.search(r"prisma\s+flow", t, re.I)), None)
    if target is None:
        target = next((i for lvl, t, i in hs if re.search(r"\bresults\b", t, re.I)), None)
    if target is None:
        return text, False
    lines = text.split("\n")
    return "\n".join(lines[:target + 1] + [figure] + lines[target + 1:]), True


def flow_figure(md: Path, flow_json: Optional[Path], family: str, tmp: Path) -> tuple[Optional[Path], str]:
    """(diagram file for this engine, note). SVG for Typst and HTML; PDF for TeX."""
    src = flow_json or md.with_name(f"{base_stem(md)}.json")
    flow = prisma_flow.load_flow(src) if src.is_file() else None
    if flow is None:
        return None, (f"no flow diagram ({src.name} not found)" if not src.is_file()
                      else f"no flow diagram ({src.name} has no PRISMA flow counts)")
    svg = tmp / "prisma_flow.svg"
    svg.write_text(prisma_flow.render_svg(flow), encoding="utf-8")
    if family not in LATEX_ENGINES:
        return svg, "PRISMA flow diagram"
    pdf = tmp / "prisma_flow.pdf"
    tool = prisma_flow.svg_to_pdf(svg, pdf)
    if tool:
        return pdf, f"PRISMA flow diagram (via {tool})"
    return None, ("WARNING: no flow diagram — TeX engines need the SVG converted, and none of "
                  "rsvg-convert, cairosvg or typst is installed (ask before installing one, "
                  "e.g. `conda install -c conda-forge librsvg`; or use --pdf-engine typst)")


def assemble(md: Path, family: str, references: Optional[str],
             include: list[str], flow_image: Optional[Path] = None) -> tuple[str, Optional[str], list[str]]:
    """(Markdown for pandoc, lifted title, notes). Raises ValueError."""
    text = neutralise_rules(md.read_text(encoding="utf-8"), keep_front_matter=True)
    notes: list[str] = []
    if references:
        styled = md.with_name(f"{base_stem(md)}.references.{references}.md")
        if not styled.is_file():
            raise ValueError(f"{styled.name} not found — run "
                             f"verify_citations.py {base_stem(md)}.json --style {references} first")
        text, done = replace_references(text, styled.read_text(encoding="utf-8"))
        if not done:
            raise ValueError(f"{md.name} has no '## References' section to replace")
        notes.append(f"references: {styled.name}")

    title = None
    if "title" not in yaml_keys(text):
        text, title = lift_title(text)
    present = {_norm_title(t) for _, t, _ in headings(text)}
    for name in include:
        side = md.with_name(base_stem(md) + SIDECARS[name])
        if not side.is_file():
            raise ValueError(f"{side.name} not found — " + (
                "run verify_citations.py first" if name == "citations"
                else f"export it with export_review.py --formats {name}"))
        side_text = neutralise_rules(side.read_text(encoding="utf-8"), keep_front_matter=False)
        side_hs = headings(side_text)
        if side_hs and _norm_title(side_hs[0][1]) in present:
            notes.append(f"skipped {side.name} (already in {md.name} as “{side_hs[0][1]}”)")
            continue
        # Sidecars open with "# …": a top-level section, like the review's own.
        text += "\n" + PAGE_BREAK + "\n" + side_text + "\n"
        notes.append(f"appendix: {side.name}")
    if flow_image is not None:
        text, placed = insert_flow_diagram(text, flow_image)
        if not placed:
            notes.append("flow diagram not placed (no 'PRISMA Flow' or 'Results' heading)")
    text, fitted = fit_images(text, [md.parent])
    notes += fitted
    return text, title, notes


# ─────────────────────────── ACM layout ────────────────────────────

ACM_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "acm-review.latex"
FIGURE_BLOCK = re.compile(
    r"^!\[\]\((?P<path>[^)\s]+)\)(?P<attrs>\{[^}]*\})?[ \t]*\n[ \t]*\n"
    r"\*\*Figure(?:\s+\d+)?\.\*\*[ \t]*(?P<caption>[^\n]+)$", re.M)


def figures_as_floats(text: str) -> tuple[str, int]:
    """``![](f.svg)`` + ``**Figure N.** caption`` → one captioned figure pandoc makes a float.

    The manuscript prints the caption as a bold paragraph so every engine shows it;
    in LaTeX that paragraph is not attached to the image, so a page break can part
    them. A float with ``\\caption`` keeps them together and is numbered by LaTeX in
    the same order the assembler numbered them.
    """
    def one(m: re.Match) -> str:
        cap = m.group("caption").strip().replace("[", "\\[").replace("]", "\\]")
        return f"![{cap}]({m.group('path')}){m.group('attrs') or ''}"
    return FIGURE_BLOCK.subn(one, text)


def small_wide_tables(text: str, columns: int = 7) -> tuple[str, int]:
    """Set pipe tables of ``columns``+ columns one size smaller (``\\scriptsize``) in the ACM layout.

    acmsmall's text block is 13.5 cm; an eight-column inventory at footnote size
    leaves each column a few characters and breaks words. Fences are left alone.
    """
    out, n, i = [], 0, 0
    lines = text.split("\n")
    fence = False
    while i < len(lines):
        ln = lines[i]
        if FENCE_OPEN.match(ln):
            fence = not fence
        if (not fence and ln.lstrip().startswith("|") and i + 1 < len(lines)
                and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]) and ln.count("|") - 1 >= columns):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out += ["```{=latex}", "\\renewcommand{\\reviewtablefont}{\\scriptsize}", "```", ""]
            out += lines[i:j]
            out += ["", "```{=latex}", "\\renewcommand{\\reviewtablefont}{\\footnotesize}", "```"]
            n += 1
            i = j
            continue
        out.append(ln)
        i += 1
    return "\n".join(out), n


def split_front_matter(body: str) -> tuple[str, dict]:
    """Take the review-details block, Abstract and Keywords out of the body for the title block.

    acmart sets the abstract and keywords inside ``\\maketitle``; left in the body
    they would print as an ordinary first section under the title block.
    """
    meta: dict = {}
    lines = body.split("\n")
    hs = headings(body)
    first = hs[0][2] if hs else len(lines)
    details = "\n".join(lines[:first]).strip()
    if details:
        meta["review-details"] = details
    rest = lines[first:]
    hs = headings("\n".join(rest))
    abs_h = next(((lvl, i) for lvl, t, i in hs if _norm_title(t) == "abstract"), None)
    if abs_h is not None:
        lvl, i = abs_h
        end = next((j for l2, _, j in hs if j > i and l2 <= lvl), len(rest))
        block = rest[i + 1:end]
        kw = [ln for ln in block if re.match(r"^\s*\*\*Keywords?:?\*\*", ln, re.I)]
        if kw:
            words = re.sub(r"^\s*\*\*Keywords?:?\*\*:?\s*", "", kw[0], flags=re.I).strip()
            meta["keywords"] = [w.strip() for w in re.split(r";|,(?![^()]*\))", words) if w.strip()]
            block = [ln for ln in block if ln not in kw]
        # structured abstract: one run-in paragraph per label, not hard line breaks
        meta["abstract"] = re.sub(r"[ \t]{2,}$", "\n", "\n".join(block).strip(), flags=re.M).replace("\n\n\n", "\n\n")
        rest = rest[:i] + rest[end:]
    return "\n".join(rest), meta


def short_title(title: str) -> str:
    """Running-head title: the part before a colon, else the first words."""
    head = title.split(":")[0].strip()
    words = head.split()
    return head if len(words) <= 8 else " ".join(words[:8]) + " …"


def manuscript_authors(md: Path) -> list[dict]:
    """``authors`` from ``<stem>.manuscript.json`` ({name, affiliation, email, country}), if given."""
    side = md.with_name(f"{base_stem(md)}.manuscript.json")
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for a in (data.get("authors") or []) if isinstance(data, dict) else []:
        a = {"name": a} if isinstance(a, str) else a
        if isinstance(a, dict) and a.get("name"):
            out.append({k: str(a[k]) for k in ("name", "affiliation", "email", "country") if a.get(k)})
    return out


# ─────────────────────────── pandoc ────────────────────────────

def build_command(src: Path, md: Path, out: Path, engine: str, *, meta: Optional[Path],
                  extra_resources: Optional[Path] = None,
                  citeproc: bool, csl: Optional[Path], bib: Optional[Path], toc: bool,
                  number_sections: bool, template: Optional[str], declared: set[str],
                  css: Optional[Path], mainfont: Optional[str], layout: str = "plain") -> list[str]:
    family = engine_family(engine)
    acm = layout == "acm"
    # ACM: images with a caption become floats; plain: the caption stays a paragraph
    reader = "markdown" if acm else "markdown-implicit_figures"
    cmd = ["pandoc", str(src), "-f", reader, "-o", str(out), f"--pdf-engine={engine}",
           # images resolve relative to the review, not to the temp copy
           "--resource-path", os.pathsep.join([str(md.parent), "."]
                                              + ([str(extra_resources)] if extra_resources else [])),
           "--standalone",
           f"--columns={WRAP_COLUMNS}"]
    if meta:
        cmd += ["--metadata-file", str(meta)]
    elif "title" not in declared:
        cmd += ["--metadata", f"title={md.stem.replace('_', ' ').replace('-', ' ').title()}"]

    if acm:
        cmd += ["--template", str(ACM_TEMPLATE)]
    elif family in LATEX_ENGINES:
        cmd += ["-V", "geometry:margin=2cm", "-V", "fontsize=10pt", "-V", "linestretch=1.1",
                "-V", "colorlinks=true", "-V", "linkcolor=blue", "-V", "urlcolor=blue",
                "-V", "citecolor=blue", "-V", "papersize=a4"]
        if mainfont and family in UNICODE_TEX:
            cmd += ["-V", f"mainfont={mainfont}"]
    elif family in TYPST_ENGINES:
        cmd += ["-V", "fontsize=10pt", "-V", "papersize=a4",
                # typst reads files only under its root (the temp dir); the figures are
                # absolute paths elsewhere, so open the root to the filesystem
                "--pdf-engine-opt=--root=" + os.path.abspath(os.sep)]
    elif css:
        cmd += ["--css", str(css), "--embed-resources"]

    if toc:
        cmd += ["--toc", "--toc-depth=2"]
    if number_sections:
        cmd.append("--number-sections")
    if citeproc:
        cmd += ["--citeproc", "-M", "link-citations=true"]
        if bib:
            cmd += ["--bibliography", str(bib)]
        if csl:
            cmd += ["--csl", str(csl)]
    if template and not acm:
        cmd += ["--template", template]
    return cmd


def _missing_glyphs(log: str) -> list[str]:
    """Characters TeX reported missing from the font, deduplicated."""
    found = re.findall(r"Missing character: There is no (\S+)", log)
    return sorted(set(found))


def generate_pdf(markdown_file: str, output_pdf: Optional[str] = None, *,
                 citation_style: str = "apa", references: Optional[str] = None,
                 include: Optional[list[str]] = None, template: Optional[str] = None,
                 toc: Optional[bool] = None, number_sections: bool = False,
                 pdf_engine: Optional[str] = None, bibliography: Optional[str] = None,
                 citations: Optional[str] = None, allow_citation_errors: bool = False,
                 mainfont: Optional[str] = None, dry_run: bool = False,
                 keep_source: bool = False, timeout: int = 900,
                 flow_diagram: bool = True, flow_json: Optional[str] = None,
                 page_limit: int = 50, allow_over_limit: bool = False, keep_tex: bool = True,
                 layout: Optional[str] = None) -> bool:
    md = Path(markdown_file)
    if not md.is_file():
        print(f"Error: markdown file not found: {md}", file=sys.stderr)
        return False
    manuscript = md.with_name(f"{md.stem}.manuscript.md")
    if not md.stem.endswith(".manuscript") and manuscript.is_file():
        # the raw export inlines every record; the manuscript is the paper
        print(f"  building {manuscript.name} (the assembled manuscript), not the raw {md.name}",
              file=sys.stderr)
        md = manuscript
    elif not md.stem.endswith(".manuscript"):
        print(f"  warning: {md.name} is the raw export, not an assembled manuscript — run "
              "assemble_manuscript.py first for the paper layout; the page limit still applies",
              file=sys.stderr)
    if toc is None:
        # a journal manuscript has no contents page: front matter and abstract open page 1
        toc = not md.stem.endswith(".manuscript")
    if not shutil.which("pandoc"):
        print("Error: pandoc not found. Install with:\n"
              "  conda install -c conda-forge pandoc   # or: brew / apt install pandoc",
              file=sys.stderr)
        return False
    engine = find_engine(pdf_engine)
    if not engine:
        which = f"'{pdf_engine}'" if pdf_engine else "any of: " + ", ".join(ALL_ENGINES)
        print(f"Error: PDF engine not found ({which}).\n"
              "  conda install -c conda-forge tectonic   # self-contained TeX\n"
              "  conda install -c conda-forge typst      # no TeX at all\n"
              "  apt-get install texlive-xetex           # or: brew install --cask mactex",
              file=sys.stderr)
        return False
    family = engine_family(engine)
    # The ACM journals layout (acmart, acmsmall) is the default for a manuscript on TeX.
    wanted = layout or ("acm" if md.stem.endswith(".manuscript") and not template else "plain")
    if wanted == "acm":
        why = ("needs a TeX engine (xelatex, lualatex, tectonic or pdflatex), not " + family
               if family not in LATEX_ENGINES
               else "the acmart class is not installed (TeX Live/MacTeX include it: "
                    "`tlmgr install acmart`; tectonic fetches it itself)" if not acmart_available(engine)
               else "")
        if why:
            if layout == "acm":
                print(f"Error: --layout acm {why}", file=sys.stderr)
                return False
            print(f"  note: plain layout — the ACM layout {why}", file=sys.stderr)
            wanted = "plain"
    layout = wanted
    if family not in ALL_ENGINES:
        print(f"  warning: '{engine}' is not an engine this script knows; "
              "no engine-specific options are applied", file=sys.stderr)

    refusal = citation_gate(md, Path(citations) if citations else None, allow_citation_errors)
    if refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        return False

    tmpdir = tempfile.TemporaryDirectory(prefix="review-pdf-")
    try:
        return _build(md, output_pdf, Path(tmpdir.name), engine=engine, family=family,
                      page_limit=page_limit, allow_over_limit=allow_over_limit, keep_tex=keep_tex,
                      citation_style=citation_style, references=references, include=include,
                      template=template, toc=toc, number_sections=number_sections,
                      bibliography=bibliography, mainfont=mainfont, dry_run=dry_run,
                      keep_source=keep_source, timeout=timeout, flow_diagram=flow_diagram,
                      flow_json=Path(flow_json) if flow_json else None, layout=layout)
    finally:
        tmpdir.cleanup()


def _build(md: Path, output_pdf: Optional[str], tmp: Path, *, engine: str, family: str,
           page_limit: int = 50, allow_over_limit: bool = False, keep_tex: bool = True,
           citation_style: str, references: Optional[str], include: Optional[list[str]],
           template: Optional[str], toc: bool, number_sections: bool, bibliography: Optional[str],
           mainfont: Optional[str], dry_run: bool, keep_source: bool, timeout: int,
           flow_diagram: bool, flow_json: Optional[Path], layout: str = "plain") -> bool:
    # #3: a kept .tex must still compile after the temp dir is gone, so images
    # converted for it live in <name>_files/ beside it, not in the temp dir.
    out_path = Path(output_pdf) if output_pdf else md.with_suffix(".pdf")
    assets = out_path.with_name(f"{out_path.stem}_files") if (family in LATEX_ENGINES and keep_tex) else tmp
    assets.mkdir(parents=True, exist_ok=True)
    assets = assets.resolve()      # the engine compiles from the temp dir: paths must be absolute
    has_flow = bool(re.search(r"!\[[^\]]*\]\([^)]*(prisma|flow)[^)]*\)", md.read_text(encoding="utf-8"), re.I))
    flow_image, flow_note = (flow_figure(md, flow_json, family, assets)
                             if flow_diagram and not has_flow else (None, ""))
    try:
        text, title, notes = assemble(md, family, references, include or [], flow_image)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return False
    if flow_note:
        (print(f"  {flow_note}", file=sys.stderr) if flow_note.startswith("WARNING")
         else notes.insert(0, flow_note))
    acm_meta: dict = {}
    if layout == "acm":
        text, n_floats = figures_as_floats(text)
        text, acm_meta = split_front_matter(text)
        text, _ = small_wide_tables(text)
        notes.append(f"layout: ACM acmsmall ({n_floats} figure float(s))")
    text, img_notes = prepare_images(text, [md.parent], family, assets)
    for n in img_notes:
        print(f"  {n}", file=sys.stderr)
    text = for_engine(text, family)

    est, heavy = estimate_pages(text)
    if page_limit and est > page_limit and not allow_over_limit:
        top = "\n".join(f"    {name[:60]:<60} ~{pages:.0f} pages" for name, pages in heavy[:6])
        print(f"Error: this document would run to about {est:.0f} pages, over the {page_limit}-page limit. "
              f"Heaviest sections:\n{top}\n"
              "  Build from the assembled manuscript (assemble_manuscript.py), which moves per-record "
              "appendices to sibling files, or pass --allow-over-limit.", file=sys.stderr)
        return False
    notes.append(f"~{est:.0f} pages estimated")

    out = Path(output_pdf) if output_pdf else md.with_suffix(".pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    declared = yaml_keys(text)
    # citeproc only when the Markdown has pandoc citations — the exported review
    # carries its own rendered reference list, which citeproc would not touch.
    uses_cites = bool(re.search(r"\[@[\w:.#$%&\-+?<>~/]+", text))
    bib = None
    if bibliography:
        bib = Path(bibliography)
        if not bib.is_file():
            print(f"Error: bibliography not found: {bib}", file=sys.stderr)
            return False
    elif uses_cites and "bibliography" not in declared:
        bib = find_bibliography(md)
    citeproc = uses_cites and bool(bib or "bibliography" in declared)
    if uses_cites and not citeproc:
        print("  warning: [@key] citations but no bibliography (sibling .bib, YAML "
              "'bibliography:' or --bibliography); they will print as written", file=sys.stderr)
    csl = resolve_csl(citation_style, md.parent) if citeproc and "csl" not in declared else None

    if layout == "acm":
        pass                        # acmart sets its own type (Libertine); --mainfont is ignored
    elif family in UNICODE_TEX and not mainfont:
        mainfont, needed = pick_main_font(text)
        if needed and not mainfont:
            print(f"  warning: no installed font found covering {needed[:40]!r}; those "
                  "characters may be missing — pass --mainfont", file=sys.stderr)
    elif family == "pdflatex" and pick_main_font(text)[1]:
        print("  warning: pdflatex cannot set this review's non-Latin characters; "
              "use xelatex, lualatex, tectonic or typst", file=sys.stderr)
    if mainfont and family in UNICODE_TEX:
        notes.append(f"font: {mainfont}")

    if True:   # the build runs inside the caller's temporary directory
        src = tmp / f"{md.stem}.pandoc.md"
        src.write_text(text, encoding="utf-8")
        meta = None
        fields: dict = {}
        if title:
            fields["title"] = title
        if layout == "acm":
            fields.update(acm_meta)
            fields["shorttitle"] = short_title(title or md.stem)
            authors = manuscript_authors(md)
            if authors:
                fields["author"] = authors
                names = [a["name"] for a in authors]
                fields["shortauthors"] = names[0] + (" et al." if len(names) > 2 else
                                                     f" and {names[1]}" if len(names) == 2 else "")
            else:
                fields["shortauthors"] = "SynthScholar"
        if fields:
            # A metadata file, not --metadata title=…: a title with a colon would
            # be read as YAML structure on the command line. JSON is YAML, and
            # its strings are read as Markdown by pandoc.
            meta = tmp / "meta.yaml"
            meta.write_text(json.dumps(fields, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        css = None
        if family in HTML_ENGINES:
            css = tmp / "review.css"
            css.write_text(HTML_CSS, encoding="utf-8")
        cmd = build_command(src, md, out, engine, meta=meta, extra_resources=tmp, citeproc=citeproc, csl=csl, bib=bib,
                            toc=toc, number_sections=number_sections, template=template,
                            declared=declared, css=css, mainfont=mainfont if layout != "acm" else None,
                            layout=layout)
        if keep_source:
            kept = out.with_suffix(".pandoc.md")
            kept.write_text(text, encoding="utf-8")
            notes.append(f"pandoc source: {kept}")
        print(f"Engine: {engine}" + "".join(f" | {n}" for n in notes), file=sys.stderr)
        if dry_run:
            print(" ".join(_shell_quote(c) for c in cmd))
            return True
        print(f"Writing: {out}", file=sys.stderr)
        try:
            if family in LATEX_ENGINES:
                result = latex_route(cmd, out, engine, family, tmp, timeout, keep_tex,
                                     search=ACM_CLASS_DIR if layout == "acm" else None)
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"Error: the build did not finish within {timeout}s "
                  "(tectonic's first run downloads its TeX bundle; retry, or raise --timeout)",
                  file=sys.stderr)
            return False

    if result.returncode != 0:
        print("Error: pandoc failed.", file=sys.stderr)
        # TeX dumps hundreds of log lines; the real error is near the end.
        for stream in (result.stdout, result.stderr):
            for line in [ln for ln in stream.splitlines() if ln.strip()][-15:]:
                print(f"  {line}", file=sys.stderr)
        return False
    missing = _missing_glyphs(result.stderr)
    # tectonic notes every system font it reads by absolute path; one line will do.
    font_paths = [ln for ln in result.stderr.splitlines() if "accessing absolute path" in ln]
    warnings = [ln for ln in result.stderr.splitlines()
                if ln.strip() and "Missing character" not in ln and ln not in font_paths]
    if font_paths:
        warnings.insert(0, f"note: {len(font_paths)} system font file(s) read; the PDF embeds them")
    for line in warnings[:10]:
        print(f"  {line}", file=sys.stderr)
    if len(warnings) > 10:
        print(f"  … {len(warnings) - 10} more warning line(s)", file=sys.stderr)
    if missing:
        print(f"  WARNING: {len(missing)} character(s) missing from the PDF's font: "
              f"{' '.join(missing[:30])} — pass --mainfont with a font that has them",
              file=sys.stderr)
    pages = pdf_page_count(out)
    print(f"Done: {out} ({out.stat().st_size / 1024:.0f} KB"
          + (f", {pages} pages" if pages else "") + ")", file=sys.stderr)
    if page_limit and pages and pages > page_limit and not allow_over_limit:
        print(f"Error: the PDF has {pages} pages, over the {page_limit}-page limit — move per-record "
              "material to sibling files (assemble_manuscript.py) rather than cutting the synthesis",
              file=sys.stderr)
        return False
    return True


def latex_route(cmd: list[str], out: Path, engine: str, family: str, tmp: Path,
                timeout: int, keep_tex: bool, search: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Markdown → standalone .tex (pandoc) → PDF (the TeX engine, run directly).

    Two explicit steps instead of pandoc's internal one: the .tex is kept next
    to the PDF (``<name>.tex``) so the source of every page can be inspected or
    edited, and the engine's own log is what errors are reported from.
    """
    tex = tmp / f"{out.stem}.tex"
    to_tex = [c for c in cmd if not c.startswith("--pdf-engine")]
    to_tex[to_tex.index("-o") + 1] = str(tex)
    to_tex += ["-t", "latex"]
    r = subprocess.run(to_tex, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return r
    if keep_tex:
        shutil.copy(tex, out.with_suffix(".tex"))   # its images are in <name>_files/ beside it
    # the bundled class (assets/acmart/) is found first; the trailing separator
    # keeps the distribution's own search path after it
    env = dict(os.environ)
    if search is not None and search.is_dir():
        env["TEXINPUTS"] = f"{search}{os.pathsep}{env.get('TEXINPUTS', '')}"
    if family == "tectonic":
        runs = [[engine, "--keep-logs", "--outdir", str(tmp)]
                + (["-Z", f"search-path={search}"] if search is not None and search.is_dir() else [])
                + [str(tex)]]
    else:
        base = [engine, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={tmp}", str(tex)]
        runs = [base, base]                      # second pass settles the TOC and references
    log = ""
    for run in runs:
        rr = subprocess.run(run, capture_output=True, text=True, timeout=timeout, cwd=str(tmp), env=env)
        log = rr.stdout + rr.stderr      # the last pass's warnings are the ones still true
        if rr.returncode != 0:
            return subprocess.CompletedProcess(run, rr.returncode, rr.stdout, rr.stderr)
    logfile = tmp / f"{out.stem}.log"
    if logfile.is_file():
        log += logfile.read_text(encoding="utf-8", errors="replace")
    shutil.copy(tmp / f"{out.stem}.pdf", out)
    # keep only the lines a reader acts on: real warnings, not TeX's box chatter
    useful = "\n".join(dict.fromkeys(ln for ln in log.splitlines()   # the log repeats stdout
                       if ("Missing character" in ln or "LaTeX Warning" in ln or "accessing absolute path" in ln)
                       and "Underfull" not in ln and "Overfull" not in ln))
    return subprocess.CompletedProcess(runs[-1], 0, "", useful)


# ─────────────────────────── batch ────────────────────────────

SIDECAR_MD = re.compile(r"\.(charting|appraisal|per-group|narrative|citations|writing|pandoc|"
                        r"references\.[\w-]+|manuscript\.md\.writing)$")
SKIP_DIRS = {"work", "figures", "node_modules", "__pycache__", ".git"}


def is_review_json(path: Path) -> bool:
    """A SynthScholar review export (PRISMAReviewResult), judged from its first 64 KB.

    The model serialises ``research_question`` then ``protocol`` first; other JSON
    beside a Markdown file (structsense extractions, validation reports) has neither.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(65536).decode("utf-8", errors="ignore")
    except OSError:
        return False
    return bool(re.match(r'\s*\{\s*"research_question"\s*:', head)) and '"protocol"' in head


def find_reviews(roots: list[Path]) -> list[tuple[Path, str]]:
    """(directory, stem) of every exported review under ``roots``: a ``<stem>.json``
    beside a ``<stem>.md`` or ``<stem>.manuscript.md`` (sidecars and work folders skipped)."""
    found: dict[tuple[Path, str], None] = {}
    for root in roots:
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                           and not d.endswith("_files")]
            names = set(files)
            for f in files:
                if not f.endswith(".md"):
                    continue
                stem = f[:-3]
                stem = stem[:-len(".manuscript")] if stem.endswith(".manuscript") else stem
                if (SIDECAR_MD.search(stem) or f"{stem}.json" not in names
                        or not is_review_json(Path(dirpath) / f"{stem}.json")):
                    continue
                found[(Path(dirpath), stem)] = None
    return sorted(found)


def batch(roots: list[Path], force: bool, **opts) -> int:
    """Build the PDF of every review under ``roots`` that has none, or an outdated one.

    A review's PDF is outdated when its manuscript, review JSON or authored
    ``<stem>.manuscript.json`` is newer. The manuscript is (re-)assembled first
    when it is missing or older than its inputs, with the references list its
    last assembly used. ``force`` rebuilds both regardless. Returns the number
    of failures.
    """
    reviews = find_reviews(roots)
    if not reviews:
        print("No exported reviews found (a <stem>.json beside <stem>.md or <stem>.manuscript.md).",
              file=sys.stderr)
        return 0
    assembler = Path(__file__).resolve().parent / "assemble_manuscript.py"
    results = []
    for d, stem in reviews:
        js, ms_json = d / f"{stem}.json", d / f"{stem}.manuscript.json"
        manuscript, raw, pdf = d / f"{stem}.manuscript.md", d / f"{stem}.md", d / f"{stem}.pdf"
        inputs = [p for p in (js, ms_json) if p.is_file()]
        newest = max(p.stat().st_mtime for p in inputs)
        stale_ms = (not manuscript.is_file()) or manuscript.stat().st_mtime < newest
        if (force or stale_ms) and assembler.is_file():
            print(f"\n[{d / stem}] assembling the manuscript", file=sys.stderr)
            r = subprocess.run([sys.executable, str(assembler), str(js)], capture_output=True, text=True)
            if r.returncode != 0 and not manuscript.is_file():
                print("  " + (r.stderr.strip().splitlines() or ["assembly failed"])[-1], file=sys.stderr)
        src = manuscript if manuscript.is_file() else raw
        if not src.is_file():
            results.append((d / stem, "FAILED", "no manuscript or review Markdown"))
            continue
        built_from = max([src.stat().st_mtime] + [p.stat().st_mtime for p in inputs])
        if pdf.is_file() and pdf.stat().st_mtime >= built_from and not force:
            results.append((d / stem, "up to date", pdf.name))
            continue
        print(f"\n[{d / stem}] {'rebuilding' if pdf.is_file() else 'building'} {pdf.name}", file=sys.stderr)
        ok = generate_pdf(str(src), str(pdf), **opts)
        results.append((d / stem, "built" if ok else "FAILED", pdf.name))
    print("\nReviews:", file=sys.stderr)
    for where, status, what in results:
        print(f"  {status:<10} {where}  ({what})", file=sys.stderr)
    return sum(1 for _, status, _ in results if status == "FAILED")


def _shell_quote(s: str) -> str:
    return s if re.fullmatch(r"[\w@%+=:,./-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def check_dependencies() -> bool:
    """Report what is installed; pandoc plus one engine is enough."""
    have_pandoc = bool(shutil.which("pandoc"))
    print(f"[{'ok' if have_pandoc else 'MISSING'}] pandoc")
    found = [e for e in ALL_ENGINES if which_tex(e)]
    for e in found:
        where = which_tex(e)
        print(f"[ok] {e}" + ("" if shutil.which(e) else f" ({where}; not on PATH, found anyway)"))
    if not found:
        print("[MISSING] no PDF engine (tried: " + ", ".join(ALL_ENGINES) + ")")
    tex = next((which_tex(e) for e in LATEX_ENGINES if which_tex(e)), None)
    if tex:
        acm = acmart_available(tex)
        print(f"[{'ok' if acm else '--'}] acmart (ACM journals layout, the manuscript default)"
              + (f" (bundled: {ACM_CLASS_DIR})" if (ACM_CLASS_DIR / "acmart.cls").is_file() else "")
              + ("" if acm else ": `tlmgr install acmart`, or use tectonic, which fetches it"))
    else:
        print("[--] TeX (needed for the ACM journals layout, the manuscript default): MacTeX / "
              "TeX Live (`brew install --cask mactex-no-gui`, `apt-get install texlive-full`) or "
              "tectonic (`conda install -c conda-forge tectonic`). Without it the PDF uses typst/HTML.")
    if any(e in LATEX_ENGINES for e in found):
        conv = next((c for c in ("rsvg-convert", "typst") if shutil.which(c)), None)
        if not conv:
            try:
                import cairosvg  # type: ignore  # noqa: F401
                conv = "cairosvg"
            except Exception:
                pass
        print(f"[{'ok' if conv else '--'}] SVG→PDF for the flow diagram on TeX engines"
              + (f" ({conv})" if conv else ": rsvg-convert, cairosvg or typst"))
    if any(e in UNICODE_TEX for e in found):
        print(f"[{'ok' if shutil.which('fc-list') else '--'}] fc-list "
              "(picks a Unicode font for TeX engines; optional)")
    print("\nReady." if have_pandoc and found else "\nNot ready: install the items marked MISSING.")
    return have_pandoc and bool(found)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("markdown_file", nargs="?", help="exported review Markdown (review.md)")
    p.add_argument("-o", "--output", help="output PDF (default: next to the Markdown)")
    # Any style verify_citations.py can render: the file decides, not a list here.
    p.add_argument("--references", metavar="STYLE", type=lambda s: s if re.fullmatch(r"[a-z0-9-]+", s)
                   else p.error(f"bad style name {s!r}"),
                   help="replace the References list with <stem>.references.<STYLE>.md "
                        "(verify_citations.py --style STYLE)")
    p.add_argument("--include", nargs="+", choices=list(SIDECARS), default=[], metavar="NAME",
                   help="append sidecar exports as appendices: " + ", ".join(SIDECARS))
    p.add_argument("--citations", metavar="REPORT_JSON",
                   help="citation report to gate on (default: <stem>.citations.json beside the Markdown)")
    p.add_argument("--allow-citation-errors", action="store_true",
                   help="build even if the citation report has errors or is stale")
    p.add_argument("--citation-style", default="apa",
                   help="CSL style id or .csl path, for [@key] citations only (default: apa)")
    p.add_argument("--bibliography", help="explicit .bib for [@key] citations")
    p.add_argument("--pdf-engine", help=f"force an engine ({', '.join(ALL_ENGINES)}), name or path")
    p.add_argument("--mainfont", help="TeX main font (default: an installed font covering the text)")
    p.add_argument("--template", help="custom pandoc template (implies --layout plain)")
    p.add_argument("--layout", choices=["acm", "plain"],
                   help="acm: ACM journals layout (acmart acmsmall; default for a manuscript on TeX); "
                        "plain: pandoc's article layout")
    p.add_argument("--toc", dest="toc", action="store_true", default=None,
                   help="contents page (default: on for a raw export, off for a manuscript)")
    p.add_argument("--no-toc", dest="toc", action="store_false")
    p.add_argument("--number-sections", action="store_true",
                   help="pandoc section numbers (off: the review numbers its own)")
    p.add_argument("--page-limit", type=int, default=50,
                   help="refuse to build past this many pages (estimated before, counted after; default 50)")
    p.add_argument("--allow-over-limit", action="store_true", help="build even when over --page-limit")
    p.add_argument("--no-tex", action="store_true",
                   help="LaTeX route: don't keep the intermediate .tex next to the PDF")
    p.add_argument("--no-flow-diagram", action="store_true",
                   help="don't draw the PRISMA 2020 flow diagram under the PRISMA Flow heading")
    p.add_argument("--flow-json", metavar="REVIEW_JSON",
                   help="review JSON with the flow counts (default: <stem>.json beside the Markdown)")
    p.add_argument("--keep-source", action="store_true",
                   help="also write the Markdown pandoc reads, next to the PDF")
    p.add_argument("--dry-run", action="store_true", help="print the pandoc command and stop")
    p.add_argument("--timeout", type=int, default=900, help="seconds before pandoc is stopped")
    p.add_argument("--check-deps", action="store_true", help="report tooling and exit")
    p.add_argument("--batch", nargs="+", metavar="DIR",
                   help="build the PDF of every exported review under DIR(s) that has none or an "
                        "outdated one (assembling the manuscript first when needed)")
    p.add_argument("--force", action="store_true", help="--batch: rebuild every manuscript and PDF")
    args = p.parse_args()

    if args.check_deps:
        return 0 if check_dependencies() else 1
    if args.batch:
        if args.output:
            p.error("--batch writes each review's PDF beside it; -o does not apply")
        failed = batch([Path(d) for d in args.batch], args.force,
                       citation_style=args.citation_style, references=args.references, include=args.include,
                       template=args.template, toc=args.toc, number_sections=args.number_sections,
                       pdf_engine=args.pdf_engine, citations=None,
                       allow_citation_errors=args.allow_citation_errors, mainfont=args.mainfont,
                       dry_run=args.dry_run, keep_source=args.keep_source, timeout=args.timeout,
                       flow_diagram=not args.no_flow_diagram, page_limit=args.page_limit,
                       allow_over_limit=args.allow_over_limit, keep_tex=not args.no_tex, layout=args.layout)
        return 1 if failed else 0
    if not args.markdown_file:
        p.error("markdown_file is required (or use --batch / --check-deps)")
    ok = generate_pdf(args.markdown_file, args.output, citation_style=args.citation_style,
                      references=args.references, include=args.include, template=args.template,
                      toc=args.toc, number_sections=args.number_sections,
                      pdf_engine=args.pdf_engine, bibliography=args.bibliography,
                      citations=args.citations, allow_citation_errors=args.allow_citation_errors,
                      mainfont=args.mainfont, dry_run=args.dry_run,
                      keep_source=args.keep_source, timeout=args.timeout,
                      flow_diagram=not args.no_flow_diagram, flow_json=args.flow_json,
                      page_limit=args.page_limit, allow_over_limit=args.allow_over_limit,
                      keep_tex=not args.no_tex, layout=args.layout)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
