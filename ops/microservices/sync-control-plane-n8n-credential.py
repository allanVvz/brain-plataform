#!/usr/bin/env python3
"""Synchronize only the existing production n8n API key into control-plane.env."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(os.environ.get("AUDIT_ROOT", "/opt/brain-ai")).resolve()
SOURCE = ROOT / ".env.compose"
TARGET = ROOT / ".env.microservices" / "control-plane.env"


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--dry-run"
    if mode not in {"--dry-run", "--apply"} or ROOT != Path("/opt/brain-ai"):
        raise SystemExit("invalid mode or production root")
    source = parse(SOURCE)
    target = parse(TARGET)
    source_key = source.get("N8N_API_KEY", "")
    if not source_key:
        raise SystemExit("N8N_API_KEY is missing from the production source env")
    matches = target.get("N8N_API_KEY") == source_key
    print(f"N8N_CREDENTIAL_PLAN mode={mode} source_present=true target_present={bool(target.get('N8N_API_KEY'))} matches={str(matches).lower()}")
    if mode == "--dry-run":
        return 0
    if os.environ.get("N8N_CREDENTIAL_SYNC_AUTHORIZED") != "true":
        raise SystemExit("authorization marker missing")
    target["N8N_API_KEY"] = source_key
    temporary = TARGET.with_suffix(".env.tmp")
    temporary.write_text("".join(f"{key}={value}\n" for key, value in sorted(target.items())), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, TARGET)
    if parse(TARGET).get("N8N_API_KEY") != source_key:
        raise SystemExit("credential verification failed")
    print("N8N_CREDENTIAL_SYNC_RESULT=passed value=redacted mode=0600")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
