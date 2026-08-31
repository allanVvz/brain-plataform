"""Small, side-effect-free environment configuration helpers."""
from __future__ import annotations

import os


def required_environment(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def optional_environment(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()
