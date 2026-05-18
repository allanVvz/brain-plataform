#!/usr/bin/env python3
"""Pipeline w/ mock OCR backend flags needs_ai_fallback and persists rows."""
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


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def main() -> int:
    ctx = AssetPipelineContext(
        persona_id="p-1",
        persona_slug="tock-fatal",
        session_id="s-1",
        upload_context="sofia_chat",
        original_filename="screenshot-modal.png",
        mime="image/png",
    )
    bundle = run_pipeline(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, ctx)
    _assert(bundle.classification.kind.startswith("image"), "classifier returns an image kind")
    _assert(bundle.ocr is not None, "OCR result is present for images")
    _assert(bundle.ocr.engine == "mock", "mock engine is used when ASSET_OCR_BACKEND=mock")
    _assert(bundle.ocr.needs_ai_fallback is True, "mock signals needs_ai_fallback=True")

    rt = [row["reading_type"] for row in bundle.rows_to_persist]
    _assert("classification" in rt, "classification row persisted")
    _assert("ocr" in rt, "ocr row persisted")
    _assert("rename" in rt, "rename row persisted")
    _assert(bundle.reading_status in ("partial", "completed"), "reading_status is partial or completed (no real OCR data)")
    print("PASS integration_asset_pipeline_ocr_mock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
