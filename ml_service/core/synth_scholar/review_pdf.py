"""PDF of a review, generated on demand.

An imported review usually brings its own `review.pdf` (the manuscript the local run
produced) and that file is served as-is. A review run here has none, so its
Markdown export is rendered with the synthscholar skill's own PDF script (vendored
in `pdf_tools/`): pandoc + Typst, plain layout — no TeX toolchain needed. The result
is cached as the review's `generated/review.pdf` artifact.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "pdf_tools" / "scripts" / "generate_review_pdf.py"
TIMEOUT_SECONDS = int(os.getenv("SYNTH_SCHOLAR_PDF_TIMEOUT", "300"))


class PDFUnavailable(RuntimeError):
    """The PDF could not be produced (tooling missing, render failed or timed out)."""


def render_markdown_to_pdf(markdown: str) -> bytes:
    """Render a review's Markdown export to PDF bytes. Blocking — run in a thread."""
    if not SCRIPT.is_file():
        raise PDFUnavailable("PDF tooling is not installed with this service")
    with tempfile.TemporaryDirectory(prefix="synthscholar-pdf-") as tmp:
        md = Path(tmp) / "review.md"
        out = Path(tmp) / "review.pdf"
        md.write_text(markdown, encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), str(md), "-o", str(out),
               "--pdf-engine", os.getenv("SYNTH_SCHOLAR_PDF_ENGINE", "typst"), "--layout", "plain",
               "--allow-citation-errors", "--allow-over-limit", "--timeout", str(TIMEOUT_SECONDS)]
        try:
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT_SECONDS + 30)
        except subprocess.TimeoutExpired as e:
            raise PDFUnavailable(f"PDF generation timed out after {TIMEOUT_SECONDS}s") from e
        except OSError as e:
            raise PDFUnavailable(f"PDF generation could not start: {e}") from e
        if proc.returncode != 0 or not out.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            raise PDFUnavailable("PDF generation failed: " + (" | ".join(tail) or f"exit {proc.returncode}"))
        return out.read_bytes()
