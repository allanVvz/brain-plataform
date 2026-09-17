#!/usr/bin/env python3
"""Return the minimal service image set for a list of changed repository paths."""
from __future__ import annotations

import argparse
import json
from pathlib import PurePosixPath


SERVICES = ("gateway", "control-plane", "conversation-runtime", "transport")
CONTRACT_CONSUMERS = ("control-plane", "conversation-runtime", "transport")


def affected_services(paths: list[str]) -> list[str]:
    affected: set[str] = set()
    for raw in paths:
        path = PurePosixPath(raw.strip().replace("\\", "/"))
        value = path.as_posix()
        if not value or value == ".":
            continue
        if value.startswith("packages/brain-shared/"):
            return list(SERVICES)
        if value.startswith("packages/brain-contracts/"):
            affected.update(CONTRACT_CONSUMERS)
        for service in SERVICES:
            if value.startswith(f"apps/{service}/"):
                affected.add(service)
    return [service for service in SERVICES if service in affected]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    print(json.dumps(affected_services(args.paths), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
