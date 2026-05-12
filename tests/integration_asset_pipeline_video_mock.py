#!/usr/bin/env python3
"""Video upload returns a mock reading and never invokes OCR or vision."""
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
os.environ["ASSET_RENAME_DISABLE_MODEL"] = "1"

from services.asset_pipeline import AssetPipelineContext, run_pipeline  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def main() -> int:
    ctx = AssetPipelineContext(
        persona_id="p-1",
        persona_slug="tock-fatal",
        upload_context="sofia_chat",
        original_filename="anuncio.mp4",
        mime="video/mp4",
    )
    bundle = run_pipeline(b"\x00\x00\x00\x18ftypmp42", ctx)
    _assert(bundle.classification.kind == "video", "video kind detected")
    _assert(bundle.ocr is None, "OCR is not called for video")
    _assert(bundle.ai_fallback is None, "AI fallback is not called for video")
    _assert(bundle.video_mock is not None, "video_mock payload populated")
    _assert(bundle.reading_status == "mocked", "reading_status='mocked' for video")
    rt = [row["reading_type"] for row in bundle.rows_to_persist]
    _assert("video_mock" in rt, "video_mock row persisted")
    _assert("ocr" not in rt, "ocr row NOT persisted for video")
    _assert(bundle.video_mock.get("video_reading_mocked") is True, "video_reading_mocked flag set")
    print("PASS integration_asset_pipeline_video_mock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
