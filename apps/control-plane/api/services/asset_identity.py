from __future__ import annotations

import hashlib
import io
import mimetypes
import re
from typing import Optional


_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]{1,10}$")


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def content_extension(filename: Optional[str], mime: Optional[str]) -> str:
    name = (filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    suffix = f".{name.rsplit('.', 1)[-1].lower()}" if "." in name else ""
    if not _SAFE_EXTENSION.fullmatch(suffix):
        suffix = (mimetypes.guess_extension(mime or "") or "").lower()
    if suffix == ".jpe":
        suffix = ".jpg"
    return suffix if _SAFE_EXTENSION.fullmatch(suffix) else ""


def content_addressed_path(
    persona_id: str,
    content_sha256: str,
    filename: Optional[str],
    mime: Optional[str],
    *,
    prefix: str = "",
) -> str:
    extension = content_extension(filename, mime)
    root = f"{persona_id}/sha256/{content_sha256}{extension}"
    return f"{prefix.rstrip('/')}/{root}" if prefix else root


def provisional_asset_type(filename: str, mime: str) -> str:
    value = (mime or "").lower()
    if value.startswith("video/"):
        return "video"
    if value == "application/pdf" or filename.lower().endswith(".pdf"):
        return "pdf"
    if value.startswith("text/"):
        return "text"
    return "image"


def image_dimensions(content: bytes, mime: str) -> tuple[int, int] | None:
    """Read intrinsic raster dimensions for deterministic site presentation."""
    if not (mime or "").lower().startswith("image/"):
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
        if width > 0 and height > 0:
            return int(width), int(height)
    except Exception:
        return None
    return None
