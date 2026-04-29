#!/usr/bin/env python3
"""
PostToolUse hook: runs the right test layer for the file just edited.

Two layers:
  smoke (fast, no browser)        -> pipeline interno via /process
  e2e   (slow, browser + WA Web)  -> WhatsApp Web real, sessão persistente

Routing:
  - File matches any E2E pattern -> run E2E only.
  - Else if matches smoke pattern -> run smoke.
  - Else: skip silently.

E2E só roda automaticamente se WA_E2E_AUTO=1 (evita abrir browser
e pedir QR Code a cada edição). Sem essa flag, o hook só recomenda.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

E2E_PATTERNS = [
    "wa_validator",
    "wa-validator",
    "wa_validator_service",
    "whatsapp",
    "scraping",
    "webscrap",
    "wa-wscrap-bot",
    "e2e_whatsapp_web",
]

SMOKE_PATTERNS = [
    "/process.py",
    "classifier.py",
    "decision_engine.py",
    "context_builder.py",
    "agents/base",
    "agents/sdr",
    "agents/closer",
    "services/model_router",
    "/prompts/",
]

# Patterns that look related but should NOT trigger anything (docs/assets).
SKIP_PATTERNS = [
    ".md",
    "/docs/",
    "/assets/",
    ".png",
    ".jpg",
    ".svg",
]


def _matches(path: str, patterns: list[str]) -> bool:
    return any(p.replace("\\", "/") in path for p in patterns)


def _run(script: str) -> tuple[int, str]:
    here = os.path.dirname(__file__)
    full = os.path.join(here, script)
    proc = subprocess.run(
        [sys.executable, full],
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    fp = (data.get("tool_input") or {}).get("file_path", "")
    fp_norm = fp.replace("\\", "/")
    label = os.path.basename(fp_norm) or "?"

    # Skip docs/assets even if they live in a watched dir.
    if _matches(fp_norm, SKIP_PATTERNS):
        return 0

    if _matches(fp_norm, E2E_PATTERNS):
        if os.environ.get("WA_E2E_AUTO") != "1":
            print(
                f"E2E recommended [{label}]: "
                "rode `python tests/e2e_whatsapp_web_sofia.py` "
                "(ou exporte WA_E2E_AUTO=1 p/ rodar automaticamente)"
            )
            return 0
        rc, out = _run("e2e_whatsapp_web_sofia.py")
        if rc != 0:
            print(f"E2E FAIL [{label}]: {out[:200]}")
            return 2
        print(f"E2E PASS [{label}]: {out[:120]}")
        return 0

    if _matches(fp_norm, SMOKE_PATTERNS):
        rc, out = _run("smoke_wa_validator.py")
        if rc != 0:
            print(f"Smoke FAIL [{label}]: {out[:200]}")
            return 2
        print(f"Smoke PASS [{label}]: {out[:120]}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
