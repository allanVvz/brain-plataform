"""Todo sufixo de rota interna de lead precisa estar na allowlist do middleware.

O middleware libera `/internal/v1/runtime/leads/<id>/<sufixo>` da sessao para
que a rota faca a propria checagem de webhook token. Um sufixo que existe no
router mas nao na allowlist devolve 401 antes de a rota rodar -- e foi assim
que `/resume-answer-window` nasceu quebrado.

O efeito era pior do que um erro visivel: `release_queue_service` trata
HTTPException da chamada como "lead inelegivel", entao a liberacao em lote
pularia todas as leads em silencio, sem erro em lugar nenhum.

A verificacao e feita sobre o texto dos dois arquivos de proposito. Importar
`middleware.auth` aqui e uma armadilha: monolito e microsservico tem modulos
`middleware` e `services` homonimos, entao quem importar primeiro na suite
inteira vence o `sys.modules` -- este teste passava sozinho e falhava no CI
exatamente por isso.
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "apps/conversation-runtime/api"
ROUTES = RUNTIME / "routes/leads.py"
MIDDLEWARE = RUNTIME / "middleware/auth.py"


def _router_suffixes() -> set[str]:
    source = ROUTES.read_text(encoding="utf-8")
    return set(
        re.findall(
            r"@internal_router\.(?:get|post|patch|delete)\(\s*\"/\{lead_ref\}(/[a-z-]+)\"",
            source,
        )
    )


def _middleware_suffixes() -> set[str]:
    source = MIDDLEWARE.read_text(encoding="utf-8")
    block = source.split('path.startswith("/internal/v1/runtime/leads/")', 1)[1]
    tupla = block.split("for suffix in", 1)[1].split("):", 1)[0]
    return set(re.findall(r'"(/[a-z-]+)"', tupla))


def test_router_and_middleware_agree_on_every_suffix() -> None:
    router = _router_suffixes()
    allowlist = _middleware_suffixes()
    assert router, "nenhuma rota /{lead_ref}/... encontrada; o regex saiu do ar"
    faltando = router - allowlist
    assert not faltando, (
        f"rotas internas sem liberacao no middleware: {sorted(faltando)}. "
        "Elas devolvem 401 antes de chegar na rota, e quem chama pode "
        "interpretar a falha como lead inelegivel."
    )


def test_resume_answer_window_is_covered() -> None:
    # A rota que originou o bug, fixada explicitamente.
    assert "/resume-answer-window" in _router_suffixes()
    assert "/resume-answer-window" in _middleware_suffixes()
