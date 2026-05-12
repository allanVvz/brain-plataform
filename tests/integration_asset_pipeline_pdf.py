#!/usr/bin/env python3
"""Pipeline handles PDFs through pypdf or returns an empty-text partial result."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["ASSET_OCR_BACKEND"] = "mock"

from services.asset_pipeline import AssetPipelineContext, run_pipeline  # noqa: E402


# Minimal PDF stub. pypdf returns 0 pages or empty text on this — the contract
# is that we still build a pdf_text reading row with status='partial'.
_PDF_BYTES = b"%PDF-1.4\n%%EOF\n"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def main() -> int:
    ctx = AssetPipelineContext(
        persona_id="p-1",
        persona_slug="tock-fatal",
        upload_context="asset_card",
        original_filename="catalogo.pdf",
        mime="application/pdf",
    )
    bundle = run_pipeline(_PDF_BYTES, ctx)
    _assert(bundle.classification.kind == "pdf", "PDF kind detected")
    _assert(bundle.pdf_text is not None, "pdf_text result populated")
    rt = [row["reading_type"] for row in bundle.rows_to_persist]
    _assert("pdf_text" in rt, "pdf_text row persisted")
    _assert("rename" in rt, "rename row persisted")
    _assert(bundle.ocr is None, "OCR is NOT called for PDFs")
    print("PASS integration_asset_pipeline_pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
