#!/usr/bin/env python3
"""Generate coherent self-hosted Supabase JWT material for the Docker stack.

The self-hosted data plane (PostgREST + Storage + Kong) authenticates every
request with JWTs signed by a shared HS256 secret (`JWT_SECRET`). The backend
talks to PostgREST as `service_role`, so its `SUPABASE_SERVICE_KEY` must be a
JWT carrying `"role": "service_role"` signed with that same secret (see
CLAUDE.md: the anon key 404s on RLS-bypass routes).

This script has no third-party dependencies (HS256 is implemented with the
stdlib) so it runs anywhere `python3` exists, before the images are built.

Usage:
    python infra/generate_keys.py                 # print env lines to stdout
    python infra/generate_keys.py --write .env.compose   # patch the env file
    JWT_SECRET=existing-secret python infra/generate_keys.py   # reuse a secret
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

# 10 years — self-hosted keys are long-lived operational secrets, rotated by
# regenerating the whole set, not by short expiry.
TEN_YEARS = 10 * 365 * 24 * 3600
ISSUER = "supabase"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_jwt(secret: str, role: str, *, iat: int, exp: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"role": role, "iss": ISSUER, "iat": iat, "exp": exp}
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def generate(secret: str | None = None) -> dict[str, str]:
    # Supabase requires the JWT secret to be at least 32 chars.
    secret = secret or secrets.token_urlsafe(48)
    if len(secret) < 32:
        raise SystemExit("JWT_SECRET must be at least 32 characters long.")
    now = int(time.time())
    exp = now + TEN_YEARS
    return {
        "JWT_SECRET": secret,
        "ANON_KEY": mint_jwt(secret, "anon", iat=now, exp=exp),
        "SERVICE_ROLE_KEY": mint_jwt(secret, "service_role", iat=now, exp=exp),
    }


def _patch_env_file(path: Path, keys: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(keys)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0] if "=" in stripped and not stripped.startswith("#") else None
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        metavar="ENV_FILE",
        help="Patch JWT_SECRET/ANON_KEY/SERVICE_ROLE_KEY into this env file in place.",
    )
    args = parser.parse_args()

    keys = generate(os.environ.get("JWT_SECRET") or None)

    if args.write:
        target = Path(args.write)
        _patch_env_file(target, keys)
        print(f"Wrote JWT_SECRET, ANON_KEY and SERVICE_ROLE_KEY to {target}")
    else:
        print("# Generated self-hosted Supabase keys — copy into .env.compose")
        for key, value in keys.items():
            print(f"{key}={value}")
        print("# SUPABASE_SERVICE_KEY for the API must equal SERVICE_ROLE_KEY above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
