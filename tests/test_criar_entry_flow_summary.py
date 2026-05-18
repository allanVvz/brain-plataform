#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc


def expect(condition: bool, message: str, detail: object | None = None) -> None:
    if not condition:
        raise AssertionError(f"{message}: {detail!r}")
    print(f"ok {message}")


def main() -> int:
    guided_message = (
        "Estou pronta para montar a estrutura.\n"
        "Ja tenho: persona e fonte.\n"
        "Preciso confirmar: publico, produto/servico e objetivo."
    )

    expect(
        svc._rewrite_visible_plan_summary(guided_message, {}) == guided_message,
        "conversation without extracted plan is not rewritten as blocked",
    )
    expect(
        "Status: bloqueado" in svc._rewrite_visible_plan_summary(guided_message, {"entries": []}),
        "explicit empty plan remains blocked for preview/save",
    )
    print("PASS test_criar_entry_flow_summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
