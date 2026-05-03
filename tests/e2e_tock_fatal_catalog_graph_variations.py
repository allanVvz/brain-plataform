#!/usr/bin/env python3
"""E2E: Tock Fatal catalog graph with variation controls and richer FAQ fan-out.

This extends the base catalog graph scenario with:
- visual validation of the variation selector on /marketing/criacao;
- FAQ variation raised from default 2 -> 3;
- richer multi-branch graph validation with audience/product semantic focus;
- at least 3 FAQ question/answer branches embedded per product knowledge.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-tock-fatal-catalog-graph-variations"
BASE_FILE = ROOT / "tests" / "e2e_tock_fatal_catalog_graph.py"


def _load_base():
    spec = importlib.util.spec_from_file_location("e2e_tock_fatal_catalog_graph_base", BASE_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load base test from {BASE_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_BASE = os.environ.get("DASHBOARD_BASE", "http://localhost:3000").rstrip("/")


def llm_initial_context(run_token: str) -> str:
    return "\n".join([
        "# Plano confirmado pelo operador",
        "persona_slug: tock-fatal",
        "objetivo: criar conhecimento para Tock Fatal Atacado a partir do catalogo Modal, em estrutura de multiplos galhos, com FAQ enriquecida por conhecimento",
        f"fonte principal: {base.CATALOG_URL}",
        "saida esperada: knowledge_plan JSON + proposta markdown de arvore de conhecimento",
        "",
        "## Blocos de conhecimento solicitados",
        "- briefing: 1 variacao",
        "- audience: 1 variacao por publico",
        "- product: 1 variacao por produto",
        "- entity: 1 variacao",
        "- copy: 1 variacao por ramo",
        "- faq: 3 variacoes por conhecimento",
        "",
        "## Regras de teste",
        f"- use run_token: {run_token} em slugs/tags para isolar o teste",
        "- sempre criar estrutura baseada em multiplos galhos",
        "- cada produto deve render pelo menos 3 FAQs recuperaveis",
        "- nao dependa de scraping perfeito; marque pendente_validacao quando nao souber",
    ])


def llm_generation_prompt(run_token: str) -> str:
    return f"""
Sofia, gere agora a arvore de conhecimento para Tock Fatal Atacado usando a fonte {base.CATALOG_URL}.

Contexto confirmado pelo operador:
- Beneficios: conforto, estilo e qualidade.
- Publicos: revendedoras e clientes finais.
- Preco unitario atende publico final.
- Kits com mais de 1 peca atendem revendedoras.
- O resultado deve sempre criar multiplos galhos.
- Para cada produto, gere 3 FAQs recuperaveis no plano.
- Mantenha 3 produtos, 2 publicos, 1 entidade principal e copies por ramo.

Obrigatorio:
- gerar pelo menos 3 entries product;
- gerar exatamente 2 entries audience;
- gerar entries de briefing, entity, copy e faq;
- gerar pelo menos 9 entries faq no total, distribuindo 3 por produto;
- gerar pelo menos 10 links semanticos;
- incluir run_token "{run_token}" nos slugs ou tags;
- responder com bloco <knowledge_plan> JSON valido.

Nao salve ainda. Apenas gere a proposta completa para validacao humana.
""".strip()


def knowledge_specs(run_token: str) -> list[dict[str, Any]]:
    specs = base.knowledge_specs(run_token)
    extra_faq = [
        ("FAQ disponibilidade e reposicao", "Reposicao depende de validacao humana do catalogo e disponibilidade comercial no momento da campanha."),
        ("FAQ diferenca entre unitario e kit", "Preco unitario orienta varejo; combinacoes em kit orientam atacado e revendedoras."),
        ("FAQ prova social e venda", "As pecas priorizam conforto e giro comercial, mas argumentos finais de venda devem seguir evidencia confirmada."),
    ]
    for spec in specs:
        if spec.get("content_type") != "product":
            continue
        blocks = []
        for title, answer in extra_faq:
            blocks.append(
                f"Pergunta: {title} para {spec['title']} no run {run_token}?\n"
                f"Resposta: {answer}"
            )
        spec["content"] = f"{spec['content']}\n\n" + "\n\n".join(blocks)
        metadata = dict(spec.get("metadata") or {})
        metadata["faq_variations"] = 3
        spec["metadata"] = metadata
    return specs


def validate_graph(report: dict, run_token: str) -> dict:
    graph = base.http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": base.PERSONA_SLUG, "mode": "semantic_tree", "max_depth": 6, "include_technical": "true"},
    )
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    token_nodes = [n for n in nodes if run_token in json.dumps(n, ensure_ascii=False)]
    by_type: dict[str, list] = {}
    for node in token_nodes:
        data = node.get("data") or {}
        ntype = data.get("node_type") or data.get("nodeClass")
        by_type.setdefault(ntype, []).append(node)
    base.expect(report, len(by_type.get("product", [])) >= 3, "graph has at least 3 product cards")
    base.expect(report, len(by_type.get("audience", [])) >= 2, "graph has 2 audience cards")
    base.expect(report, len(by_type.get("entity", [])) >= 1, "graph has entity card")
    base.expect(report, len(by_type.get("faq", [])) >= 6, "graph has richer FAQ fan-out", {"faq_cards": len(by_type.get("faq", []))})
    base.expect(report, len(by_type.get("copy", [])) >= 2, "graph has copy cards")
    token_node_ids = {n.get("id") for n in token_nodes}
    token_edges = [e for e in edges if e.get("source") in token_node_ids or e.get("target") in token_node_ids]
    base.expect(report, len(token_edges) >= 12, "graph has semantic edges for richer subtree", {"token_edges": len(token_edges)})
    audience_labels = [n.get("data", {}).get("label") for n in by_type.get("audience", [])]
    report["graph_summary"] = {
        "token_nodes": len(token_nodes),
        "token_edges": len(token_edges),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "audiences": audience_labels,
    }
    return graph


def capture_browser_evidence(report: dict, run_token: str, campaign_slug: str, *, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.setdefault("warnings", []).append("playwright not installed; screenshot skipped")
        print("  WARN playwright not installed; screenshot skipped")
        return

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    criar_shot = ARTIFACTS_DIR / f"criar-{run_token}.png"
    graph_shot = ARTIFACTS_DIR / f"knowledge-tree-{run_token}.png"
    graph_focus_shot = ARTIFACTS_DIR / f"knowledge-focus-{run_token}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 980})

        page.goto(f"{DASHBOARD_BASE}/marketing/criacao", wait_until="domcontentloaded", timeout=60000)
        page.get_by_test_id("aumentar-faq").click()
        page.wait_for_timeout(400)
        page.screenshot(path=str(criar_shot), full_page=True)
        page_text = page.locator("body").inner_text()
        base.expect(report, "Variacoes por atributo" in page_text, "capture screen exposes variation selector")
        base.expect(report, "FAQ inicia com 2" in page_text, "capture screen documents FAQ default 2")

        graph_url = (
            f"{DASHBOARD_BASE}/knowledge/graph?"
            + parse.urlencode({
                "persona": base.PERSONA_SLUG,
                "mode": "semantic_tree",
                "depth": 5,
                "tech": 1,
                "focus": f"campaign:{campaign_slug}",
            })
        )
        page.goto(graph_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(graph_shot), full_page=True)

        semantic_filter = page.locator('select[aria-label="filtro-semantico-grafo"]')
        semantic_filter.wait_for(state="visible", timeout=15000)
        options = semantic_filter.locator("option")
        count = options.count()
        audience_value = None
        for idx in range(count):
          value = options.nth(idx).get_attribute("value") or ""
          label = options.nth(idx).inner_text()
          if value.startswith("audience:") and run_token in label.lower():
              audience_value = value
              break
        if audience_value:
            semantic_filter.select_option(audience_value)
            page.wait_for_timeout(1800)
            page.screenshot(path=str(graph_focus_shot), full_page=True)
            base.expect(report, "focus=audience%3A" in page.url, "semantic graph filter focuses selected audience", page.url)
        else:
            report.setdefault("warnings", []).append("audience option not found in semantic graph filter")

        browser.close()

    base.expect(report, graph_shot.exists() and graph_shot.stat().st_size > 10_000, "knowledge tree screenshot created", str(graph_shot))
    report["screenshots"] = {
        "criar": str(criar_shot),
        "knowledge_tree": str(graph_shot),
        "knowledge_focus": str(graph_focus_shot),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2evar%Y%m%d%H%M%S"))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    run_token = base.slugify(args.run_token)
    report: dict[str, Any] = {
        "ok": False,
        "run_token": run_token,
        "api_base": API_BASE,
        "dashboard_base": DASHBOARD_BASE,
        "catalog_url": base.CATALOG_URL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "variant": "faq-3-per-knowledge",
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{run_token}.json"

    try:
        print(f"\n== E2E Tock Fatal catalog graph variations ({run_token}) ==")
        health = base.http_json("GET", "/health")
        base.expect(report, health.get("status") == "ok", "backend health ok")
        persona = base.resolve_persona(report)
        specs = knowledge_specs(run_token)
        report["planned_entries"] = [{"type": s["content_type"], "slug": s["slug"], "title": s["title"]} for s in specs]
        base.expect(report, len([s for s in specs if s["content_type"] == "product"]) == 3, "plan keeps 3 products")
        base.expect(report, len([s for s in specs if s["content_type"] == "audience"]) == 2, "plan keeps 2 audiences")
        faq_variations = [s for s in specs if s["content_type"] == "product" and (s.get("metadata") or {}).get("faq_variations") == 3]
        base.expect(report, len(faq_variations) == 3, "all products carry FAQ variation 3")

        if not args.skip_llm:
            started = base.http_json("POST", "/kb-intake/start", body={
                "model": args.model,
                "agent_key": "sofia",
                "initial_context": llm_initial_context(run_token),
            }, timeout=90)
            session_id = started.get("session_id")
            base.expect(report, bool(session_id), "LLM Sofia session started", started.get("agent"))
            response = base.http_json("POST", "/kb-intake/message", body={
                "session_id": session_id,
                "message": llm_generation_prompt(run_token),
            }, timeout=180)
            plan = base.extract_knowledge_plan(response.get("message") or "")
            entries = plan.get("entries") or []
            faqs = [e for e in entries if e.get("content_type") == "faq"]
            base.expect(report, len(faqs) >= 9, "LLM plan includes at least 9 FAQ entries")
            report["llm"] = {"session_id": session_id, "entry_count": len(entries), "faq_count": len(faqs), "plan": plan}
        else:
            report.setdefault("warnings", []).append("LLM planning skipped by --skip-llm")

        created = base.create_and_promote(report, persona["id"], specs)
        report["created_count"] = len(created)
        validate_graph(report, run_token)
        if not args.skip_browser:
            campaign_slug = f"tock-fatal-atacado-catalogo-modal-{run_token}"
            capture_browser_evidence(report, run_token, campaign_slug, headless=not args.headed)

        report["ok"] = True
        print(f"\nPASS e2e Tock Fatal catalog graph variations. Report: {report_path}")
        return 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        print(f"\nFAIL {exc}")
        return 1
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
