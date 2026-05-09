from __future__ import annotations

import os
from typing import Any


def _bool_env(name: str) -> bool:
    value = (os.environ.get(name) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def is_production_runtime() -> bool:
    return (
        bool((os.environ.get("K_SERVICE") or "").strip())
        or bool((os.environ.get("CLOUD_RUN_JOB") or "").strip())
        or (os.environ.get("ENV", "").strip().lower() == "production")
        or (os.environ.get("PYTHON_ENV", "").strip().lower() == "production")
    )


def get_backend_env() -> dict[str, Any]:
    return {
        "allowed_origins": [
            origin.strip()
            for origin in os.environ.get(
                "ALLOWED_ORIGINS",
                "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000",
            ).split(",")
            if origin.strip()
        ],
        "supabase_url": (os.environ.get("SUPABASE_URL") or "").strip(),
        "supabase_service_key": (os.environ.get("SUPABASE_SERVICE_KEY") or "").strip(),
        "is_production": is_production_runtime(),
        "run_embedded_workers": _bool_env("RUN_EMBEDDED_WORKERS"),
    }


def validate_backend_env(strict: bool | None = None) -> list[str]:
    env = get_backend_env()
    if strict is None:
        strict = bool(env["is_production"])
    missing: list[str] = []
    if strict:
        if not env["supabase_url"]:
            missing.append("SUPABASE_URL")
        if not env["supabase_service_key"]:
            missing.append("SUPABASE_SERVICE_KEY")
        if not env["allowed_origins"]:
            missing.append("ALLOWED_ORIGINS")
    return missing
