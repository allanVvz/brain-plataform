# -*- coding: utf-8 -*-
"""E2E real: dialogo do operador -> chat() -> preview graph_json -> print da arvore.

Diferente de `test_vzlupas_catalog_to_hierarchical_graph_e2e.py` (que monta o
grafo perfeito a mao e so roda validadores), este teste dirige o caminho REAL da
Sofia Criar pela sequencia de mensagens que o operador realmente digitou no
dashboard, e afirma sobre o **preview graph_json** -- o mesmo objeto que o
frontend renderiza no canvas. Ao final, imprime a arvore resultante (stdout +
artifact) para inspecao visual ("o print do grafo resultante").

Reproduz a falha relatada: o operador pede "agrupo 3 ... 3 radar, 3 juliet e 3
eye jacket" e o preview sai com **1 product_group contendo todos os produtos**
em vez de 3 grupos com 3 produtos cada. A causa esta em
`kb_intake_service._parse_tree_counts`, que so reconhece a forma literal
"N grupos" -- a fala natural do operador ("agrupo 3 de acordo com as colecoes",
"3 radar, 3 juliet e 3 eye jacket") nao casa, entao num_groups cai para 1.

Determinismo: o ModelRouter e stubado para NAO produzir plano (pior caso para o
LLM), forcando o builder deterministico `build_full_tree_plan_from_session`; o
crawler e stubado com um catalogo realista da vzlupas.com. Sem rede, sem LLM,
sem Supabase.

Estado esperado: VERMELHO hoje (product_group == 1). Vira VERDE quando o parse de
agrupamento honrar a fala do operador (3 grupos x 3 produtos).
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "api", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services import kb_intake_service as svc  # noqa: E402

ARTIFACTS = ROOT / "test-artifacts" / "e2e-vzlupas-dialog-preview"


# --- Catalogo realista (vzlupas.com): 3 Radar, 3 Juliet, 3 Eye Jacket + ruido.
# As 3 familias pedidas sao as mais frequentes; familias de ruido (Plantaris,
# Splice) tem menos itens, entao o ranking por frequencia escolhe as 3 certas
# assim que num_groups for parseado corretamente.
_CANDIDATES = [
    {"title": "Radar Ev Path Copper Prizm Tungsten", "prices": ["219.00"], "source": "https://vzlupas.com/p/radar-copper"},
    {"title": "Radar Ev Path Green Black Iridium", "prices": ["219.00"], "source": "https://vzlupas.com/p/radar-green"},
    {"title": "Radar White Ruby", "prices": ["227.30"], "source": "https://vzlupas.com/p/radar-white-ruby"},
    {"title": "Juliet Plasma Gold Custom", "prices": ["212.30"], "source": "https://vzlupas.com/p/juliet-gold"},
    {"title": "Juliet Roxa Plasma Violet Polarizado", "prices": ["197.30"], "source": "https://vzlupas.com/p/juliet-roxa"},
    {"title": "Juliet Squared Black", "prices": ["197.60"], "source": "https://vzlupas.com/p/juliet-squared"},
    {"title": "Eye Jacket Redux Steel Prizm", "prices": ["240.00"], "source": "https://vzlupas.com/p/eyejacket-steel"},
    {"title": "Eye Jacket Polished Black", "prices": ["238.00"], "source": "https://vzlupas.com/p/eyejacket-black"},
    {"title": "Eye Jacket Matte Clear", "prices": [], "source": "https://vzlupas.com/p/eyejacket-clear"},
    {"title": "Plantaris Matte Sand Prizm Tungsten", "prices": ["205.00"], "source": "https://vzlupas.com/p/plantaris-sand"},
    {"title": "Plantaris Silver Mettalic Liquid Metal", "prices": ["205.00"], "source": "https://vzlupas.com/p/plantaris-silver"},
    {"title": "Splice Carbon Dark Blue", "prices": ["199.00"], "source": "https://vzlupas.com/p/splice-blue"},
    {"title": "Splice Ruby Iridium", "prices": ["199.00"], "source": "https://vzlupas.com/p/splice-ruby"},
]


def _fake_capture(url: str) -> dict:
    return {
        "url": url,
        "final_url": url,
        "status_code": 200,
        "confidence": 0.85,
        "confidence_label": "alta",
        "product_candidates": list(_CANDIDATES),
        "warnings": [],
        "raw_text_preview": "catalogo vz lupas oculos radar juliet eye jacket",
        "stages": [],
    }


class _FakeRouter:
    """Stub do ModelRouter: responde so conversacional, sem <knowledge_plan>.
    Espelha o dialogo real (LLM em loop sem materializar plano), forcando o
    builder deterministico a ser quem monta a arvore."""

    def messages_create(self, *args, **kwargs):
        return (
            "Entendi! Vou montar a arvore com Brand -> Briefing -> Campaign -> "
            "Audience -> Product Group -> Product -> Copy -> FAQ usando os "
            "produtos extraidos do site."
        )


@contextmanager
def _mocked_backends():
    prev_router = svc.ModelRouter
    prev_crawl = svc.crawl_catalog_url
    prev_tools = os.environ.get("SOFIA_TOOLS_ENABLED")
    svc.ModelRouter = _FakeRouter  # type: ignore[assignment]
    svc.crawl_catalog_url = _fake_capture  # type: ignore[assignment]
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    try:
        yield
    finally:
        svc.ModelRouter = prev_router  # type: ignore[assignment]
        svc.crawl_catalog_url = prev_crawl  # type: ignore[assignment]
        if prev_tools is None:
            os.environ.pop("SOFIA_TOOLS_ENABLED", None)
        else:
            os.environ["SOFIA_TOOLS_ENABLED"] = prev_tools


# As mensagens EXATAS do operador (dialogo reportado), em ordem.
_DIALOG = [
    "briefing vendas de inverno. publico joven, usa oculos para esportes.",
    "agrupo 3 de acordo com as colecoes. 3 extraia 9 produtos, 3 radar, 3 juliet "
    "e 3 eye jacket em grupos do site. busque pelas collections",
    "todos os produtos para a mesma audiencia",
    "todas as ligacoes devem ser principais. crie a arvore agora",
]


def _run_dialog() -> dict:
    started = svc.start_bootstrap_session(
        "gpt-4o-mini",
        initial_context=(
            "Missao: vz-lupas | Fonte: https://vzlupas.com | "
            "Blocos: briefing, audience, product"
        ),
        agent_key="sofia",
        initial_state={
            "mode": "criar",
            "persona_slug": "vz-lupas",
            "source_url": "https://vzlupas.com",
            "initial_block_counts": {"briefing": 1, "audience": 1, "product_group": 3, "product": 9},
        },
        bootstrap_llm=False,
    )
    sid = started.get("session_id") or started.get("id")
    responses = [svc.chat(sid, msg) for msg in _DIALOG]
    return {"session_id": sid, "responses": responses}


def _materialized_graph_json(session_id: str, last_response: dict) -> dict | None:
    gj = (last_response.get("plan_state") or {}).get("graph_json")
    if not gj:
        gj = (svc.get_session(session_id) or {}).get("graph_json")
    return gj or None


def _would_be_graph_and_reason(session_id: str) -> tuple[dict | None, str]:
    """Reconstroi o grafo que o builder deterministico PRODUZIRIA a partir da
    sessao, para evidencia visual quando nenhum preview foi materializado.
    Retorna (graph_json|None, motivo)."""
    session = svc.get_session(session_id) or {}
    try:
        built = svc.build_full_tree_plan_from_session(session, _DIALOG[-1])
        if not built:
            return None, "builder retornou None (sem candidatos)"
        state = svc.normalize_validate_summarize_plan(built, session)
        validation = state.get("validation") or {}
        reason = ""
        if not validation.get("valid"):
            reason = "plano invalido: " + str(
                validation.get("blocking_violations") or validation.get("violations")
            )
        gj = state.get("graph_json")
        if not gj:
            # graph_json so e gerado quando o plano valida; reconstroi puro.
            try:
                gj = svc.normalized_plan_to_graph_json(state.get("normalized_plan") or built, session).model_dump()
            except Exception as exc:  # pragma: no cover - evidencia best-effort
                return None, reason or f"graph_json indisponivel: {exc}"
        return gj, reason
    except Exception as exc:  # pragma: no cover
        return None, f"reconstrucao falhou: {exc}"


def _children_by_parent(graph: dict) -> dict[str, list[dict]]:
    nodes_by_id = {n["id"]: n for n in graph.get("nodes", [])}
    out: dict[str, list[dict]] = {}
    for e in graph.get("edges", []):
        child = nodes_by_id.get(e["target"])
        if child is not None:
            out.setdefault(e["source"], []).append(child)
    return out


def _render_tree(graph: dict) -> str:
    nodes_by_id = {n["id"]: n for n in graph.get("nodes", [])}
    children = _children_by_parent(graph)
    targets = {e["target"] for e in graph.get("edges", [])}
    roots = [n["id"] for n in graph.get("nodes", []) if n["id"] not in targets]
    lines: list[str] = []

    def walk(node_id: str, depth: int) -> None:
        node = nodes_by_id.get(node_id, {})
        lines.append(
            f"{'  ' * depth}- [{node.get('node_type', '?')}] {node.get('label') or node.get('slug')}"
        )
        for child in sorted(children.get(node_id, []), key=lambda n: (n.get("node_type", ""), n.get("slug", ""))):
            walk(child["id"], depth + 1)

    for root in roots:
        walk(root, 0)
    return "\n".join(lines)


def _print_graph(graph: dict, title: str) -> None:
    tree = _render_tree(graph)
    counts: dict[str, int] = {}
    for n in graph.get("nodes", []):
        counts[n["node_type"]] = counts.get(n["node_type"], 0) + 1
    header = f"=== {title} ===\nnodes={len(graph.get('nodes', []))} edges={len(graph.get('edges', []))} | {counts}"
    print("\n" + header + "\n" + tree + "\n")
    try:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / "graph-tree.txt").write_text(header + "\n" + tree + "\n", encoding="utf-8")
    except Exception:
        pass


def test_dialog_produces_3_groups_of_3_products_preview() -> None:
    with _mocked_backends():
        result = _run_dialog()

    responses = result["responses"]
    final = responses[-1]
    assert final.get("ok") is True, f"ultima mensagem nao deve dar 500: {final.get('error_code')} / {final.get('detail')}"

    # O crawler rodou e capturou candidatos reais da fonte configurada.
    sess = svc.get_session(result["session_id"])
    captures = sess.get("crawler_captures") or []
    assert captures and captures[-1].get("product_candidates"), "crawler deve ter capturado candidatos"

    graph = _materialized_graph_json(result["session_id"], final)
    if graph is None:
        # Nenhum preview materializado: renderiza o grafo que o builder
        # PRODUZIRIA como evidencia do bug ("preview errado") e falha com a
        # causa-raiz.
        would_be, reason = _would_be_graph_and_reason(result["session_id"])
        if would_be is not None:
            _print_graph(would_be, "GRAFO QUE O BUILDER PRODUZIRIA (bug — preview nao materializado)")
        raise AssertionError(
            "nenhum graph_json de preview foi materializado pelo dialogo. "
            f"Causa: {reason or 'turno final caiu no LLM sem plano'}. "
            "Esperado: 3 product_groups x 3 products."
        )
    _print_graph(graph, "PREVIEW graph_json apos dialogo vz-lupas")

    nodes = graph.get("nodes", [])
    by_type: dict[str, list[dict]] = {}
    for n in nodes:
        by_type.setdefault(n["node_type"], []).append(n)

    # Cadeia canonica presente (1 de cada no topo).
    for ntype in ("persona", "brand", "briefing", "campaign", "audience"):
        assert len(by_type.get(ntype, [])) >= 1, f"cadeia canonica exige >=1 {ntype}"

    product_groups = by_type.get("product_group", [])
    products = by_type.get("product", [])

    # --- O CONTRATO QUE FALHA HOJE: 3 grupos x 3 produtos = 9. ---
    assert len(product_groups) == 3, (
        f"esperados 3 product_groups (Radar/Juliet/Eye Jacket), obtidos {len(product_groups)} "
        f"-> {[g.get('label') for g in product_groups]}. "
        "Bug: _parse_tree_counts nao reconhece 'agrupo 3 ... 3 radar 3 juliet 3 eye jacket'."
    )
    assert len(products) == 9, f"esperados 9 products (3 por grupo), obtidos {len(products)}"

    children = _children_by_parent(graph)
    for group in product_groups:
        group_products = [c for c in children.get(group["id"], []) if c.get("node_type") == "product"]
        assert len(group_products) == 3, (
            f"product_group {group.get('label')!r} deve ter exatamente 3 produtos, "
            f"tem {len(group_products)}"
        )


def test_dialog_does_not_500() -> None:
    """Mesmo que o agrupamento esteja errado, nenhum turno do dialogo pode
    estourar (o catch-all 'Nao consegui processar sua mensagem agora')."""
    with _mocked_backends():
        result = _run_dialog()
    for i, r in enumerate(result["responses"]):
        assert r.get("ok") is True, (
            f"turno {i} ({_DIALOG[i][:40]!r}) deu erro: "
            f"{r.get('error_code')} / {r.get('detail')}"
        )
