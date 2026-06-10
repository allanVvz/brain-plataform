#!/usr/bin/env python3
"""Retired launcher.

The current backend runtime is Docker Compose:

    docker compose --env-file .env.compose up -d --build

This file is kept only so old references fail with a clear message instead of
silently starting a backend against legacy environment files.
"""

from __future__ import annotations

import sys


def main() -> int:
    print("scripts/start_api_qa.py is retired. Use Docker Compose with .env.compose.")
    return 64


if __name__ == "__main__":
    sys.exit(main())
