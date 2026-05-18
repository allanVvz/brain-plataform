#!/usr/bin/env python3
"""Asset pipeline — classifier covers the file kinds the user can upload."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.asset_pipeline import classifier  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def test_pdf_detected_from_mime() -> None:
    result = classifier.detect(b"%PDF-1.7\n...", "application/pdf", "manual.pdf")
    _assert(result.kind == "pdf", "PDF mime maps to kind=pdf")
    _assert(result.has_text_estimate is True, "PDF carries text estimate")
    _assert(result.needs_ocr is False, "PDF should rely on pypdf, not OCR")


def test_video_detected_from_ext() -> None:
    result = classifier.detect(b"\x00\x00\x00\x18ftypmp42", "", "campaign.mp4")
    _assert(result.kind == "video", "mp4 ext maps to kind=video")
    _assert(result.needs_ocr is False, "video does not run OCR")
    _assert(result.confidence >= 0.9, "video confidence is high (path)")


def test_screenshot_filename_hint() -> None:
    # Even with empty bytes Pillow path fails gracefully; filename keyword wins.
    result = classifier.detect(b"\x89PNG\r\n\x1a\n", "image/png", "screenshot-2026-01-04.png")
    _assert(result.kind in ("image_screenshot", "image_other"), "screenshot/png picked up as image")
    _assert(result.needs_ocr is True, "image needs OCR by default")


def test_text_kind() -> None:
    result = classifier.detect(b"oi", "text/plain", "nota.txt")
    _assert(result.kind == "text", "txt detected as text")
    _assert(result.has_text_estimate is True, "text has text estimate")


def test_unknown_kind() -> None:
    result = classifier.detect(b"binary", "application/x-foo", "blob.xyz")
    _assert(result.kind == "unknown", "unrecognized mime/ext returns unknown")


def main() -> int:
    print("test_pdf_detected_from_mime"); test_pdf_detected_from_mime()
    print("test_video_detected_from_ext"); test_video_detected_from_ext()
    print("test_screenshot_filename_hint"); test_screenshot_filename_hint()
    print("test_text_kind"); test_text_kind()
    print("test_unknown_kind"); test_unknown_kind()
    print("PASS integration_asset_pipeline_classifier")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
