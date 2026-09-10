"""As rotas internas de lead precisam passar pelo middleware antes da rota.

O middleware libera `/internal/v1/runtime/leads/<id>/<sufixo>` da sessao para
que a rota faca a propria checagem de webhook token. Um sufixo que existe no
router mas nao aqui devolve 401 antes de chegar na rota -- e foi assim que
`/resume-answer-window` nasceu quebrado: o release_queue trata falha de chamada
como "lead inelegivel", entao a liberacao em lote pularia todas as leads em
silencio, sem erro visivel em lugar nenhum.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT / "apps/conversation-runtime/api",
    ROOT / "packages/brain-shared",
    ROOT / "packages/brain-contracts",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from middleware.auth import is_public_path  # noqa: E402


def test_every_internal_lead_suffix_reaches_its_route() -> None:
    for suffix in (
        "pause", "resume", "resume-answer-window", "acknowledge-handoff", "handoff",
    ):
        assert is_public_path(f"/internal/v1/runtime/leads/209/{suffix}"), suffix


def test_only_numeric_lead_refs_are_allowed() -> None:
    assert not is_public_path("/internal/v1/runtime/leads/../resume")
    assert not is_public_path("/internal/v1/runtime/leads/abc/resume")
    assert not is_public_path("/internal/v1/runtime/leads/209/delete")
