from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from services import kb_intake_service as svc


def test_visible_plan_summary_without_extracted_plan_is_not_rewritten_as_blocked() -> None:
    guided_message = (
        "Estou pronta para montar a estrutura.\n"
        "Ja tenho: persona e fonte.\n"
        "Preciso confirmar: publico, produto/servico e objetivo."
    )
    assert svc._rewrite_visible_plan_summary(guided_message, {}) == guided_message


def test_visible_plan_summary_explicit_empty_plan_remains_blocked() -> None:
    guided_message = (
        "Estou pronta para montar a estrutura.\n"
        "Ja tenho: persona e fonte.\n"
        "Preciso confirmar: publico, produto/servico e objetivo."
    )
    assert "Status: bloqueado" in svc._rewrite_visible_plan_summary(guided_message, {"entries": []})
