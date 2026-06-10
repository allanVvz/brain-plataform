#!/usr/bin/env python3
"""Retired live probe.

The current QA path runs through Docker Compose and the dashboard proxy. This
legacy live probe is disabled to avoid depending on old environment files.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("scripts/probe_sofia_plan_json_blocking_live.py is retired for the Docker Compose flow.")
    return 64


if __name__ == "__main__":
    sys.exit(main())
