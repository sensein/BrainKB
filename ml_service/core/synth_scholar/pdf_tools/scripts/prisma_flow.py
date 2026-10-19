#!/usr/bin/env python3
"""Draw the PRISMA 2020 flow diagram for a review, as SVG (and PDF).

The exported review reports the flow as a table; reviews and journals expect
the diagram. This draws the PRISMA 2020 template for new systematic reviews
from ``review.json``'s ``flow`` counts:

    Identification   records identified, per source  →  records removed before screening
    Screening        records screened                 →  records excluded
                     reports sought for retrieval     →  reports not retrieved
                     reports assessed for eligibility →  reports excluded, with reasons
    Included         studies included in review

Sources are listed one per line (PubMed, bioRxiv, the user's own databases,
related-article and citation searching), and exclusion reasons with their
counts, exactly as recorded — the diagram adds no number the flow doesn't hold.

Usage:
    python prisma_flow.py out/review.json                   # → out/review.prisma.svg
    python prisma_flow.py out/review.json --pdf             # + review.prisma.pdf
    python prisma_flow.py out/review.json --out fig.svg

The SVG needs nothing. The PDF (what TeX engines embed) is converted with the
first available of ``rsvg-convert``, ``cairosvg`` or ``typst``; stdlib otherwise.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

# Geometry, in SVG user units (px at 96 dpi). 880 wide keeps the diagram
# legible when scaled to an A4 text width (~17 cm).
W = 880
PHASE_X, PHASE_W = 8, 32
MAIN_X, MAIN_W = 56, 380
SIDE_X, SIDE_W = 488, 384
PAD, LINE, GAP, FONT = 12, 18, 34, 14
CHAR_W = 7.4   # average glyph advance at 14 px sans-serif, for wrapping
PHASE_FILL = "#cfe0f1"

SOURCE_LABELS = (
    ("db_pubmed", "PubMed"), ("db_biorxiv", "bioRxiv"), ("db_medrxiv", "medRxiv"),
)


def _n(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "?"


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap to the box's character budget."""
    limit = max(10, int((width - 2 * PAD) / CHAR_W))
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            if line and len(line) + 1 + len(word) > limit:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return out


def flow_lines(flow: dict) -> dict[str, list[str]]:
    """Box texts for each slot of the template, from the flow counts."""
    sources = [f"{label} (n = {_n(flow.get(k))})" for k, label in SOURCE_LABELS if flow.get(k)]
    sources += [f"{name} (n = {_n(v)})" for name, v in sorted((flow.get("db_other_sources") or {}).items())]
    if flow.get("db_related"):
        sources.append(f"Related-article searching (n = {_n(flow['db_related'])})")
    if flow.get("db_hops"):
        sources.append(f"Citation searching (n = {_n(flow['db_hops'])})")
    if not sources:
        sources = [f"Databases and registers (n = {_n(flow.get('total_identified'))})"]
    # eligibility-stage reasons: the per-stage field when recorded, else the combined one
    reasons = flow.get("excluded_reasons_full_text") or flow.get("excluded_reasons") or {}
    excluded = ([f"{r} (n = {_n(c)})" for r, c in sorted(reasons.items(), key=lambda kv: -int(kv[1] or 0))]
                or [f"(n = {_n(flow.get('excluded_eligibility'))})"])
    return {
        "identified": ["Records identified from:"] + sources
                      + ([f"Total (n = {_n(flow.get('total_identified'))})"] if len(sources) > 1 else []),
        "removed": ["Records removed before screening:",
                    f"Duplicate records removed (n = {_n(flow.get('duplicates_removed'))})"],
        "screened": [f"Records screened (n = {_n(flow.get('screened_title_abstract'))})"],
        "excluded_ta": [f"Records excluded (n = {_n(flow.get('excluded_title_abstract'))})"],
        "sought": [f"Reports sought for retrieval (n = {_n(flow.get('sought_fulltext'))})"],
        "not_retrieved": [f"Reports not retrieved (n = {_n(flow.get('not_retrieved'))})"],
        "assessed": [f"Reports assessed for eligibility (n = {_n(flow.get('assessed_eligibility'))})"],
        "excluded_el": [f"Reports excluded (n = {_n(flow.get('excluded_eligibility'))}):"]
                       + (excluded if reasons else []),
        "included": [f"Studies included in review (n = {_n(flow.get('included_synthesis'))})"],
    }


def render_svg(flow: dict, title: str = "") -> str:
    """The PRISMA 2020 diagram as a standalone SVG document."""
    t = flow_lines(flow)
    rows = [("identified", "removed"), ("screened", "excluded_ta"), ("sought", "not_retrieved"),
            ("assessed", "excluded_el"), ("included", None)]
    wrapped = [([ln for s in t[m] for ln in _wrap(s, MAIN_W)],
                [ln for s in t[side] for ln in _wrap(s, SIDE_W)] if side else []) for m, side in rows]

    parts: list[str] = []
    y = 16
    heading_h = 0
    if title:
        heading_h = 30
        parts.append(f'<text x="{W / 2}" y="{y + 14}" text-anchor="middle" font-size="16" '
                     f'font-weight="bold">{escape(title)}</text>')
        y += heading_h
    # A single-row phase band must fit its rotated label ("Included").
    label_need = {0: len("Identification"), 4: len("Included")}
    boxes = []   # (top, height, main lines, side lines)
    for i, (mlines, slines) in enumerate(wrapped):
        h = PAD * 2 + LINE * max(len(mlines), len(slines) or 1)
        if i in label_need:
            h = max(h, int(label_need[i] * CHAR_W * 1.08) + 2 * PAD)
        boxes.append((y, h, mlines, slines))
        y += h + GAP
    height = y - GAP + 16

    def box(x: float, top: float, w: float, h: float, lines: list[str], bold_first: bool) -> None:
        parts.append(f'<rect x="{x}" y="{top}" width="{w}" height="{h}" rx="4" fill="#ffffff" '
                     f'stroke="#1a1a1a" stroke-width="1.2"/>')
        ty = top + PAD + FONT
        for i, ln in enumerate(lines):
            weight = ' font-weight="bold"' if bold_first and i == 0 and len(lines) > 1 else ""
            parts.append(f'<text x="{x + PAD}" y="{ty}"{weight}>{escape(ln)}</text>')
            ty += LINE

    def arrow(x1, y1, x2, y2) -> None:
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#1a1a1a" '
                     f'stroke-width="1.3" marker-end="url(#arrow)"/>')

    # phase bands: Identification = row 0, Screening = rows 1–3, Included = row 4
    for label, first, last in (("Identification", 0, 0), ("Screening", 1, 3), ("Included", 4, 4)):
        top = boxes[first][0]
        bottom = boxes[last][0] + boxes[last][1]
        mid = (top + bottom) / 2
        parts.append(f'<rect x="{PHASE_X}" y="{top}" width="{PHASE_W}" height="{bottom - top}" rx="4" '
                     f'fill="{PHASE_FILL}" stroke="none"/>')
        parts.append(f'<text x="{PHASE_X + PHASE_W / 2}" y="{mid}" text-anchor="middle" '
                     f'dominant-baseline="central" font-weight="bold" '
                     f'transform="rotate(-90 {PHASE_X + PHASE_W / 2} {mid})">{label}</text>')

    for i, (top, h, mlines, slines) in enumerate(boxes):
        box(MAIN_X, top, MAIN_W, h, mlines, bold_first=(i == 0))
        if slines:
            box(SIDE_X, top, SIDE_W, h, slines, bold_first=True)
            arrow(MAIN_X + MAIN_W, top + h / 2, SIDE_X - 2, top + h / 2)
        if i + 1 < len(boxes):
            arrow(MAIN_X + MAIN_W / 2, top + h, MAIN_X + MAIN_W / 2, boxes[i + 1][0] - 2)

    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
            f'viewBox="0 0 {W} {height}" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="{FONT}" fill="#1a1a1a">\n'
            f'<title>PRISMA 2020 flow diagram</title>\n'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
            f'fill="#1a1a1a"/></marker></defs>\n'
            f'<rect width="{W}" height="{height}" fill="#ffffff"/>\n'
            + "\n".join(parts) + "\n</svg>\n")


def svg_to_pdf(svg: Path, pdf: Path) -> Optional[str]:
    """Convert with the first available tool; return its name, or None."""
    if shutil.which("rsvg-convert"):
        r = subprocess.run(["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg)],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and pdf.is_file():
            return "rsvg-convert"
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2pdf(url=str(svg), write_to=str(pdf))
        return "cairosvg"
    except Exception:
        pass
    if shutil.which("typst"):
        # a page exactly the size of the SVG, holding only the image
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "flow.typ"
            shutil.copy(svg, Path(tmp) / "flow.svg")
            src.write_text('#set page(width: auto, height: auto, margin: 0pt)\n'
                           '#image("flow.svg")\n', encoding="utf-8")
            r = subprocess.run(["typst", "compile", str(src), str(pdf)], capture_output=True, timeout=120)
            if r.returncode == 0 and pdf.is_file():
                return "typst"
    return None


def load_flow_dict(flow: object) -> Optional[dict]:
    """``flow`` if it holds counts worth drawing, else None."""
    if not isinstance(flow, dict) or not any(
            int(flow.get(k) or 0) for k in ("total_identified", "screened_title_abstract",
                                             "assessed_eligibility", "included_synthesis")):
        return None
    return flow


def load_flow(review_json: Path) -> Optional[dict]:
    """The review's flow counts, or None when there is nothing to draw."""
    try:
        data = json.loads(review_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return load_flow_dict(data.get("flow") if isinstance(data, dict) else None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review", help="review JSON (PRISMAReviewResult)")
    ap.add_argument("--out", help="SVG path (default: <stem>.prisma.svg next to the review)")
    ap.add_argument("--pdf", action="store_true", help="also write a PDF next to the SVG")
    ap.add_argument("--title", default="", help="optional heading drawn above the diagram")
    args = ap.parse_args()

    src = Path(args.review)
    flow = load_flow(src)
    if flow is None:
        print(f"{src}: no PRISMA flow counts to draw", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else src.with_name(f"{src.stem}.prisma.svg")
    out.write_text(render_svg(flow, args.title), encoding="utf-8")
    print(f"diagram: {out}")
    if args.pdf:
        pdf = out.with_suffix(".pdf")
        tool = svg_to_pdf(out, pdf)
        if not tool:
            print("no SVG→PDF converter (rsvg-convert, cairosvg or typst) — SVG only", file=sys.stderr)
            return 1
        print(f"diagram: {pdf} (via {tool})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
