"""Validate that the release route map and Caddy match exactly."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTE_MAP_PATH = ROOT / "ops" / "microservices" / "route-map.json"
CADDY_PATH = ROOT / "infra" / "microservices" / "Caddyfile.routes"


def _caddy_matchers(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("@") or " path " not in line:
            continue
        matcher, patterns = line.split(" path ", 1)
        result[matcher.removeprefix("@")] = patterns.split()
    return result


def main() -> None:
    route_map = json.loads(ROUTE_MAP_PATH.read_text(encoding="utf-8"))
    routes = route_map["routes"]
    matchers = _caddy_matchers(CADDY_PATH.read_text(encoding="utf-8"))
    expected = {
        "transport": routes["transport"],
        "runtime": routes["conversation-runtime"],
    }
    if matchers != expected:
        raise SystemExit(
            "Caddy route matchers differ from route-map.json: "
            f"expected={expected!r} actual={matchers!r}"
        )

    owners: dict[str, str] = {}
    duplicates: list[str] = []
    for owner, patterns in routes.items():
        for pattern in patterns:
            if pattern in owners:
                duplicates.append(f"{pattern}: {owners[pattern]} and {owner}")
            owners[pattern] = owner
    if duplicates:
        raise SystemExit("Duplicate route ownership: " + "; ".join(duplicates))

    process_owner = next(
        (owner for owner, patterns in routes.items() if "/process" in patterns),
        None,
    )
    if process_owner != "conversation-runtime":
        raise SystemExit(f"/process must belong to conversation-runtime, got {process_owner!r}")


if __name__ == "__main__":
    main()
