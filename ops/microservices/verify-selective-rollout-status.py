#!/usr/bin/env python3
"""Verify only the service promoted by a compatible blue/green release."""
from __future__ import annotations

import re
import sys


SERVICE_WORKER_PREFIXES = {
    "gateway": (),
    "control-plane": (
        "brain-ai-control-plane-knowledge-",
        "brain-ai-control-plane-integrations-",
        "brain-ai-control-plane-validator-",
    ),
    "conversation-runtime": (
        "brain-ai-runtime-conversation-",
        "brain-ai-runtime-validator-",
    ),
    "transport": (
        "brain-ai-transport-dispatch-",
        "brain-ai-transport-media-",
    ),
}


def verify_output(service: str, output: str) -> None:
    if service not in SERVICE_WORKER_PREFIXES:
        raise ValueError(f"unknown service: {service}")

    service_line = next((
        line for line in output.splitlines()
        if re.match(rf"^{re.escape(service)}\s+slot=(blue|green)\s+", line)
    ), None)
    if service_line is None or not service_line.rstrip().endswith("up to date"):
        raise ValueError(f"released service is not up to date: {service}")

    prefixes = SERVICE_WORKER_PREFIXES[service]
    if prefixes:
        pending = [
            line.strip() for line in output.splitlines()
            if line.strip().startswith(prefixes)
        ]
        if pending:
            raise ValueError(
                f"released service has workers pending replacement: {', '.join(pending)}"
            )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: verify-selective-rollout-status.py SERVICE", file=sys.stderr)
        return 2
    try:
        verify_output(argv[1], sys.stdin.read())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"PASS affected_service={argv[1]} state=up_to_date workers=clear")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
