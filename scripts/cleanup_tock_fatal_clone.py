#!/usr/bin/env python3
"""Retired QA cleanup helper.

The current operational stack is local-first through Docker Compose. This
legacy remote-QA cleanup script is intentionally disabled.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("scripts/cleanup_tock_fatal_clone.py is retired for the Docker Compose flow.")
    return 64


if __name__ == "__main__":
    sys.exit(main())
