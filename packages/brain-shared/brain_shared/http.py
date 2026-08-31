"""Tiny URL helper for typed private clients; no domain behavior lives here."""
from __future__ import annotations


def internal_url(base_url: str, path: str) -> str:
    if not path.startswith("/internal/v1/"):
        raise ValueError("private calls must use /internal/v1")
    return base_url.rstrip("/") + path
