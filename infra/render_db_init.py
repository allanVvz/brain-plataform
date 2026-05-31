#!/usr/bin/env python3
"""Render infra/db-init/init-scripts/99-roles.sql from .env.compose.

The Supabase service roles (authenticator, supabase_storage_admin,
supabase_auth_admin) are created without a password by the supabase/postgres
image. This renders the init-script that sets them to POSTGRES_PASSWORD so
PostgREST and Storage can authenticate. The rendered file is mounted into the
db container's /docker-entrypoint-initdb.d/init-scripts/ and runs on first boot.

Usage:
    python infra/render_db_init.py                  # reads .env.compose
    POSTGRES_PASSWORD=... python infra/render_db_init.py
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "infra" / "db-init" / "init-scripts" / "99-roles.sql.example"
TARGET = ROOT / "infra" / "db-init" / "init-scripts" / "99-roles.sql"
ENV_FILE = ROOT / ".env.compose"


def _password() -> str:
    pw = os.environ.get("POSTGRES_PASSWORD")
    if pw:
        return pw
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("POSTGRES_PASSWORD not set and not found in .env.compose")


def main() -> int:
    pw = _password()
    if "'" in pw:
        raise SystemExit("POSTGRES_PASSWORD must not contain a single quote.")
    rendered = TEMPLATE.read_text(encoding="utf-8").replace("__POSTGRES_PASSWORD__", pw)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Rendered {TARGET} (password length {len(pw)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
