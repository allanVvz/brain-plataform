"""Inbound media must reach the agent as content, never as a placeholder sentence."""
from __future__ import annotations

from services import asset_pipeline, media_ingest
from services.asset_pipeline import ocr_local
from services.asset_pipeline.schemas import AiFallbackResult


def _context():
    return asset_pipeline.AssetPipelineContext(
        persona_id="p", persona_slug=None, upload_context="whatsapp_inbound",
        original_filename="foto.jpg", mime="image/jpeg",
    )


def _png() -> bytes:
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 10, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_without_ocr_or_vision_the_agent_gets_the_honest_placeholder(monkeypatch):
    monkeypatch.setenv("ASSET_OCR_BACKEND", "mock")
    monkeypatch.setattr(asset_pipeline._ai, "run", lambda *a, **k: None)
    bundle = asset_pipeline.run_pipeline(_png(), _context())
    text, status = media_ingest.describe(
        {"kind": "image", "caption": None},
        {"extracted_text": bundle.extracted_text, "visual_summary": bundle.visual_summary},
    )
    assert ocr_local._MOCK_TEXT not in text
    assert text == "[o cliente enviou uma imagem]" and status == "failed"


def test_vision_reading_reaches_the_agent(monkeypatch):
    monkeypatch.setenv("ASSET_OCR_BACKEND", "mock")
    monkeypatch.setattr(asset_pipeline._ai, "run", lambda *a, **k: AiFallbackResult(
        extracted_text="", visual_summary="Blusa preta de manga longa", model_used="vision"))
    bundle = asset_pipeline.run_pipeline(_png(), _context())
    text, status = media_ingest.describe(
        {"kind": "image", "caption": "Tem essa?"},
        {"extracted_text": bundle.extracted_text, "visual_summary": bundle.visual_summary},
    )
    assert "Blusa preta de manga longa" in text and status == "completed"
