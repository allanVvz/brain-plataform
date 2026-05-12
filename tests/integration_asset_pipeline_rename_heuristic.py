#!/usr/bin/env python3
"""Renamer falls back to a deterministic heuristic (no model call)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["ASSET_RENAME_DISABLE_MODEL"] = "1"

from services.asset_pipeline import renamer  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok {message}")


def main() -> int:
    result = renamer.run(
        persona_slug="tock-fatal",
        branch_label="Kit Modal 1",
        kind="image_product",
        extracted_text="Modal 1 vermelho promocao R$ 59,90",
        visual_summary="Foto do kit modal vermelho",
        original_filename="WhatsApp Image.png",
    )
    _assert(result.used_model is False, "renamer skips the model when disabled")
    _assert(result.filename.endswith(".png"), "filename keeps original extension")
    _assert(result.slug != "", "slug is non-empty")
    _assert(result.asset_function == "product_reference", "asset_function maps from kind=image_product")
    _assert(any("modal" in t for t in result.tags) or any("kit" in t for t in result.tags),
            "heuristic picks meaningful tags from the visual summary")
    _assert(result.suggested_parent_slug, "suggested_parent_slug derived from branch_label")
    print("PASS integration_asset_pipeline_rename_heuristic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
