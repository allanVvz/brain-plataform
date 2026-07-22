#!/usr/bin/env python3
"""Fail closed when a VPS .env.compose contains unsafe production values."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def jwt_payload(token: str, secret: str) -> dict:
    header, payload, signature = token.split(".", 2)
    expected = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    if not hmac.compare_digest(actual, expected):
        raise ValueError("signature does not match JWT_SECRET")
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", nargs="?", default=".env.compose")
    args = parser.parse_args()
    path = Path(args.env_file)
    if not path.is_file():
        raise SystemExit(f"env file not found: {path}")
    env = read_env(path)
    required = [
        "POSTGRES_PASSWORD", "JWT_SECRET", "ANON_KEY", "SERVICE_ROLE_KEY",
        "AI_BRAIN_AUTH_SECRET", "AI_BRAIN_WEBHOOK_TOKEN", "API_DOMAIN", "STORAGE_DOMAIN", "ACME_EMAIL",
        "SUPABASE_PUBLIC_URL", "ALLOWED_ORIGINS",
    ]
    errors = [f"{key} is missing" for key in required if not env.get(key)]
    for key in required:
        value = env.get(key, "").lower()
        if "replace_with" in value or "change-me" in value or "local-dev" in value:
            errors.append(f"{key} still contains a placeholder/development value")
    if env.get("ENVIRONMENT") != "production":
        errors.append("ENVIRONMENT must be production")
    if env.get("COMPOSE_PROJECT_NAME", "brain-ai") != "brain-ai":
        errors.append("COMPOSE_PROJECT_NAME must be brain-ai (backup volume labels depend on it)")
    for key in ("POSTGRES_PASSWORD", "AI_BRAIN_AUTH_SECRET", "AI_BRAIN_WEBHOOK_TOKEN"):
        value = env.get(key, "")
        if len(value) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            errors.append(f"{key} must be a URL-safe random value with at least 32 characters")
    application_secrets = {
        env.get("POSTGRES_PASSWORD", ""),
        env.get("AI_BRAIN_AUTH_SECRET", ""),
        env.get("AI_BRAIN_WEBHOOK_TOKEN", ""),
    }
    if len(application_secrets) != 3:
        errors.append("POSTGRES_PASSWORD, AI_BRAIN_AUTH_SECRET and AI_BRAIN_WEBHOOK_TOKEN must be distinct")
    if len(env.get("JWT_SECRET", "")) < 32:
        errors.append("JWT_SECRET must have at least 32 characters")
    for key in ("API_DOMAIN", "STORAGE_DOMAIN"):
        value = env.get(key, "")
        if "://" in value or value.endswith(".invalid") or value.startswith("localhost"):
            errors.append(f"{key} must be a real hostname without scheme")
    expected_storage = f"https://{env.get('STORAGE_DOMAIN', '')}"
    if env.get("SUPABASE_PUBLIC_URL", "").rstrip("/") != expected_storage:
        errors.append(f"SUPABASE_PUBLIC_URL must equal {expected_storage}")
    origins = env.get("ALLOWED_ORIGINS", "")
    if "*" in origins or "localhost" in origins or "127.0.0.1" in origins:
        errors.append("ALLOWED_ORIGINS cannot contain wildcards or local development origins")
    try:
        if jwt_payload(env.get("ANON_KEY", ""), env.get("JWT_SECRET", "")).get("role") != "anon":
            errors.append("ANON_KEY must carry role=anon")
        if jwt_payload(env.get("SERVICE_ROLE_KEY", ""), env.get("JWT_SECRET", "")).get("role") != "service_role":
            errors.append("SERVICE_ROLE_KEY must carry role=service_role")
    except Exception as exc:
        errors.append(f"Supabase JWT validation failed: {exc}")
    if errors:
        print("Production environment validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Production environment validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
