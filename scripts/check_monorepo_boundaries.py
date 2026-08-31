"""Fail fast when a deployable Brain app crosses a source boundary.

This check deliberately uses only the standard library so it is usable before
dependencies are installed in CI and release dry-runs.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPS = ("gateway", "control-plane", "conversation-runtime", "transport")
CANONICAL_TEMPLATE = ROOT / "apps/conversation-runtime/n8n/persona-conversation-template.json"
APP_IMPORT = re.compile(r"(?:from|import)\s+apps[./]([a-z-]+)")


def _failure(message: str) -> None:
    print(f"boundary error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _check_layout() -> None:
    for app in APPS:
        path = ROOT / "apps" / app
        if not path.is_dir():
            _failure(f"missing app directory {path.relative_to(ROOT)}")
    for package in ("brain-contracts", "brain-shared"):
        if not (ROOT / "packages" / package).is_dir():
            _failure(f"missing shared package packages/{package}")
    if not CANONICAL_TEMPLATE.is_file():
        _failure("missing canonical conversation template")


def _check_templates() -> None:
    templates = list((ROOT / "apps").rglob("persona-conversation-template.json"))
    if templates != [CANONICAL_TEMPLATE]:
        locations = ", ".join(str(path.relative_to(ROOT)) for path in templates)
        _failure(f"expected exactly one provisionable conversation template, found: {locations}")


def _check_cross_imports() -> None:
    for owner in APPS:
        for path in (ROOT / "apps" / owner).rglob("*.py"):
            text = path.read_text(encoding="utf-8-sig")
            targets = set(APP_IMPORT.findall(text))
            foreign = sorted(target for target in targets if target != owner)
            if foreign:
                _failure(f"{path.relative_to(ROOT)} imports another app: {', '.join(foreign)}")


def _check_contract_clients() -> None:
    for owner in ("control-plane", "conversation-runtime", "transport"):
        client_sources = list((ROOT / "apps" / owner / "api").rglob("*_client.py"))
        for path in client_sources:
            text = path.read_text(encoding="utf-8-sig")
            if "BRAIN_" in text and "http" in text and "/internal/v1/" not in text:
                _failure(f"private client without /internal/v1 contract: {path.relative_to(ROOT)}")


def _check_manifest_contract() -> None:
    manifest = ROOT / "apps/service-boundaries.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("contract_package") != "packages/brain-contracts":
        _failure("service-boundaries.json must name packages/brain-contracts")
    if set(payload.get("apps", {})) != set(APPS):
        _failure("service-boundaries.json app ownership is incomplete")


def main() -> int:
    _check_layout()
    _check_templates()
    _check_cross_imports()
    _check_contract_clients()
    _check_manifest_contract()
    print("monorepo boundaries ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
