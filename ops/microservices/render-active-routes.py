#!/usr/bin/env python3
"""Render Caddy routes from the persisted blue/green slot state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SERVICE_NAMES = ("control-plane", "conversation-runtime", "transport")
SLOTS = {"blue", "green"}


def _active(state: dict, service: str) -> str | None:
    value = state.get(service)
    if isinstance(value, dict):
        value = value.get("active")
    if value in SLOTS:
        return value
    if service == "gateway" and value == "legacy":
        return "legacy"
    return None


def render(state: dict) -> tuple[str, str]:
    gateway = _active(state, "gateway")
    public_target = f"gateway-{gateway}:8080" if gateway in SLOTS else "api:8080"
    public = f"handle {{\n\treverse_proxy {public_target}\n}}\n"

    lines = [":8090 {"]
    for service in SERVICE_NAMES:
        slot = _active(state, service)
        lines.append(f"\thandle_path /{service}/* {{")
        if slot:
            compose_name = "runtime" if service == "conversation-runtime" else service
            lines.append(f"\t\treverse_proxy {compose_name}-{slot}:8080")
        else:
            lines.append("\t\trespond 503")
        lines.append("\t}")
    lines.extend(("\thandle {", "\t\trespond 404", "\t}", "}"))
    return public, "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise SystemExit("slot state must be an object")
    public, internal = render(state)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "public-upstream.caddy").write_text(public, encoding="utf-8")
    (args.output / "internal-upstreams.caddy").write_text(internal, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
