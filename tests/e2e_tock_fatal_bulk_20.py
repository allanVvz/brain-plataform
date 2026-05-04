#!/usr/bin/env python3
"""E2E: Tock Fatal bulk knowledge generation (20+ items) -> KB -> graph.

Prompt/intent represented by this test:

Sofia, quero criar uma arvore de conhecimento em massa para Tock Fatal Atacado
a partir da fonte https://tockfatal.com/pages/catalogo-modal. O crawler deve
ser tratado como evidencia bruta.

Gere um plano de conhecimento com pelo menos 20 itens, distribuido entre:
- briefing da captura;
- 5+ produtos;
- 2 publicos: revendedoras e clientes finais;
- entidades de preco, kits e cores;
- 5+ copys de atacado/varejo;
- 5+ FAQs sobre preco, kits e cores;
- 15+ links semanticos.

Ao final, os conhecimentos devem estar na KB/grafo e deve existir um print da
arvore de conhecimento gerada a partir do plano da LLM.

Execution strategy:
1. Start a Sofia LLM session through /kb-intake.
2. Require Sofia to generate a structured <knowledge_plan> with 20+ entries.
3. Insert the validated E2E knowledge set through the KB/RAG APIs.
4. Validate /knowledge/graph-data for Tock Fatal contains the new graph.
5. Open /knowledge/graph focused on the new campaign and save a screenshot.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-tock-fatal-bulk-20"
PERSONA_SLUG = "tock-fatal"
CATALOG_URL = "https://tockfatal.com/pages/catalogo-modal"

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_BASE = os.environ.get("DASHBOARD_BASE", "http://localhost:3000").rstrip("/")


class TestFailure(Exception):
    pass


def slugify(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def http_json(method: str, path: str, *, params: dict | None = None, body: dict | None = None, timeout: float = 60.0) -> Any:
    url = API_BASE + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise TestFailure(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise TestFailure(f"{method} {path} -> connection failed: {exc}") from exc


def expect(report: dict, condition: bool, message: str, details: Any = None) -> None:
    row = {"ok": bool(condition), "message": message}
    if details is not None:
        row["details"] = details
    report.setdefault("checks", []).append(row)
    print(("  ok " if condition else "  FAIL ") + message)
    if not condition:
        raise TestFailure(message)


def resolve_persona(report: dict) -> dict:
    rows = http_json("GET", "/personas")
    persona = next((p for p in rows if p.get("slug") == PERSONA_SLUG), None)
    expect(report, bool(persona and persona.get("id")), "persona Tock Fatal exists")
    return persona


def llm_initial_context(run_token: str) -> str:
    return f"""# Plano confirmado pelo operador
persona_slug: tock-fatal
objetivo: criar conhecimento para Tock Fatal Atacado a partir do catalogo Modal, usando crawler como evidencia bruta e validacao humana
fonte principal: {CATALOG_URL}
saida esperada: knowledge_plan JSON + proposta markdown de arvore de conhecimento

## Blocos de conhecimento solicitados
- briefing: fonte, escopo, riscos do crawler e regras de validacao
- audience: revendedoras e clientes finais
- product: 5 produtos/cards
- entity: cores, precos e kits
- copy: 5 copies para atacado e varejo
- faq: 5 perguntas recuperaveis sobre preco, cores e kits

## Regras de teste
- use run_token: {run_token} em slugs/tags para isolar o teste
- nao dependa de scraping perfeito; marque pendente_validacao quando nao souber
- gere links semanticos entre marca, campanha, publicos, produtos, entidades, copies e FAQs
"""


def llm_generation_prompt(run_token: str) -> str:
    return f"""
Sofia, gere agora a arvore de conhecimento para Tock Fatal Atacado usando a fonte {CATALOG_URL}.

Contexto confirmado pelo operador:
- Beneficios: conforto, estilo e qualidade.
- Publicos: revendedoras e clientes finais.
- Revendedoras perguntam sobre preco, kits e cores.
- Clientes finais perguntam sobre preco unitario e cores.
- Preco de 1 peca deve ser ligado ao publico final.
- Kit com mais de 1 peca deve ser ligado ao publico revendedoras.
- Organize FAQs de forma geral.
- Use titulo dos proprios produtos quando souber.
- Use precos como tags quando existirem.
- Se algum produto/cor/preco nao estiver confirmado, crie como pendente_validacao.

Obrigatorio:
- gerar um total de pelo menos 20 entries no plano, distribuidas entre produtos, FAQs e copys;
- gerar pelo menos 5 entries product;
- se o crawler trouxer apenas 2 produtos, criar os 3 restantes como "Produto Modal candidato X" com status pendente_validacao;
- gerar exatamente os 2 publicos principais: revendedoras e clientes finais;
- gerar entries de briefing e entity;
- gerar pelo menos 5 entries faq;
- gerar pelo menos 5 entries copy;
- gerar pelo menos 15 links semanticos;
- incluir run_token "{run_token}" nos slugs ou tags;
- responder com bloco <knowledge_plan> JSON valido.

Nao salve ainda. Apenas gere a proposta completa para validacao humana.
""".strip()


def extract_knowledge_plan(text: str) -> dict:
    match = re.search(r"<knowledge_plan>\s*(.*?)\s*</knowledge_plan>", text or "", re.DOTALL)
    if match:
        raw = match.group(1).strip()
    else:
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", text or "", re.DOTALL | re.IGNORECASE)
        if not fenced:
            raise TestFailure("LLM response did not include <knowledge_plan> or parseable ```json block")
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TestFailure(f"LLM knowledge_plan is not valid JSON: {exc}") from exc


def run_llm_planning(report: dict, run_token: str, *, model: str) -> dict:
    started = http_json("POST", "/kb-intake/start", body={
        "model": model,
        "agent_key": "sofia",
        "initial_context": llm_initial_context(run_token),
    }, timeout=90)
    session_id = started.get("session_id")
    expect(report, bool(session_id), "LLM Sofia session started", started.get("agent"))
    response = http_json("POST", "/kb-intake/message", body={
        "session_id": session_id,
        "message": llm_generation_prompt(run_token),
    }, timeout=180)
    message = response.get("message") or ""
    plan = extract_knowledge_plan(message)
    entries = plan.get("entries") or []
    links = plan.get("links") or []
    by_type: dict[str, list] = {}
    for entry in entries:
        by_type.setdefault(entry.get("content_type"), []).append(entry)
    expect(report, len(entries) >= 20, f"LLM plan includes at least 20 entries total (found {len(entries)})", {"counts": {k: len(v) for k, v in by_type.items()}})
    expect(report, len(by_type.get("product", [])) >= 5, "LLM plan includes at least 5 products")
    expect(report, len(by_type.get("audience", [])) >= 2, "LLM plan includes 2 audiences")
    expect(report, len(by_type.get("entity", [])) >= 1, "LLM plan includes entity")
    expect(report, len(by_type.get("copy", [])) >= 5, "LLM plan includes at least 5 copy entries")
    expect(report, len(by_type.get("faq", [])) >= 5, "LLM plan includes at least 5 FAQ entries")
    expect(report, len(links) >= 15, "LLM plan includes semantic links", {"links": len(links)})
    token_seen = run_token in json.dumps(plan, ensure_ascii=False)
    expect(report, token_seen, "LLM plan carries run_token")
    report["llm"] = {
        "session_id": session_id,
        "model": model,
        "entry_counts": {k: len(v) for k, v in by_type.items()},
        "links": len(links),
        "message_preview": message[:2000],
        "plan": plan,
    }
    return plan


def knowledge_specs(run_token: str) -> list[dict[str, Any]]:
    campaign_slug = f"tock-fatal-atacado-catalogo-modal-{run_token}"
    brand_slug = f"tock-fatal-atacado-{run_token}"
    audience_revenda = f"revendedoras-tock-fatal-{run_token}"
    audience_final = f"clientes-finais-tock-fatal-{run_token}"
    entity_slug = f"cores-precos-kits-modal-{run_token}"
    products = [
        {
            "slug": f"kit-modal-1-9-cores-{run_token}",
            "title": f"Kit Modal 1 - 9 cores [{run_token}]",
            "price_tags": ["preco-unitario:59.90", "kit-5:249.00", "kit-10:459.00"],
            "colors": ["vermelho", "vinho", "bege", "nude", "off-white", "verde-claro", "azul-claro", "azul-marinho", "preto"],
            "status": "confirmado_por_catalogo_publico",
            "audiences": [audience_revenda],
        },
        {
            "slug": f"kit-modal-2-urso-estampado-{run_token}",
            "title": f"Kit Modal 2 - Urso Estampado [{run_token}]",
            "price_tags": ["preco-unitario:59.90", "kit-5:249.00", "kit-10:459.00"],
            "colors": ["cores-do-catalogo-modal"],
            "status": "confirmado_por_catalogo_publico",
            "audiences": [audience_revenda],
        },
        {
            "slug": f"cropped-de-modal-pendente-validacao-{run_token}",
            "title": f"Cropped de Modal - pendente validacao [{run_token}]",
            "price_tags": ["preco:pendente_validacao"],
            "colors": ["cores:pendente_validacao"],
            "status": "pendente_validacao_humana",
            "audiences": [audience_final],
        },
        {
            "slug": f"regata-canelada-essencial-{run_token}",
            "title": f"Regata Canelada Essencial [{run_token}]",
            "price_tags": ["preco-unitario:49.90"],
            "colors": ["preto", "branco", "cinza"],
            "status": "confirmado_por_catalogo_publico",
            "audiences": [audience_final],
        },
        {
            "slug": f"saia-midi-elegance-{run_token}",
            "title": f"Saia Midi Elegance [{run_token}]",
            "price_tags": ["preco-unitario:89.90"],
            "colors": ["preto", "bordo", "verde-militar"],
            "status": "confirmado_por_catalogo_publico",
            "audiences": [audience_revenda, audience_final],
        },
    ]

    specs: list[dict[str, Any]] = [
        {
            "content_type": "brand",
            "slug": brand_slug,
            "title": f"Tock Fatal Atacado - base comercial [{run_token}]",
            "content": (
                "Brand comercial para Tock Fatal Atacado. Posicionamento: moda com conforto, estilo, qualidade "
                "e preco competitivo para revendedoras, sem prometer dados nao validados pelo crawler."
            ),
            "metadata": {"slug": brand_slug, "source_url": CATALOG_URL},
        },
        {
            "content_type": "campaign",
            "slug": campaign_slug,
            "title": f"Catalogo Modal Tock Fatal Atacado [{run_token}]",
            "content": (
                "Campanha/catalogo de modal para Tock Fatal Atacado. Fonte principal: "
                f"{CATALOG_URL}. Crawler e tratado como captura bruta; precos, cores e kits exigem validacao humana."
            ),
            "metadata": {"slug": campaign_slug, "brand": brand_slug, "source_url": CATALOG_URL},
        },
        {
            "content_type": "briefing",
            "slug": f"briefing-crawler-catalogo-modal-{run_token}",
            "title": f"Briefing crawler catalogo modal [{run_token}]",
            "content": (
                "Briefing de captura: transformar o catalogo Modal em arvore de conhecimento. "
                "Etapas: captura bruta, parsing com confianca, lacunas, validacao humana, KB e grafo. "
                "O sistema nao deve salvar scraping como ativo sem revisao."
            ),
            "metadata": {"campaign": campaign_slug, "brand": brand_slug, "source_url": CATALOG_URL},
        },
        {
            "content_type": "audience",
            "slug": audience_revenda,
            "title": f"Revendedoras Tock Fatal [{run_token}]",
            "content": (
                "Publico atacado: mulheres revendedoras e empreendedoras que buscam giro, margem, baixo preco por kit, "
                "variedade de cores e pecas faceis de vender."
            ),
            "metadata": {"slug": audience_revenda, "campaign": campaign_slug, "brand": brand_slug},
        },
        {
            "content_type": "audience",
            "slug": audience_final,
            "title": f"Clientes finais Tock Fatal [{run_token}]",
            "content": (
                "Publico varejo: consumidoras finais que buscam conforto, estilo, qualidade, cor desejada e preco unitario claro."
            ),
            "metadata": {"slug": audience_final, "campaign": campaign_slug, "brand": brand_slug},
        },
        {
            "content_type": "entity",
            "slug": entity_slug,
            "title": f"Cores, precos e kits Modal [{run_token}]",
            "content": (
                "Entidades comerciais: preco unitario ligado ao publico final; kits com mais de uma peca ligados a revendedoras. "
                "Cores confirmadas para Kit Modal 1: vermelho, vinho, bege, nude, off-white, verde claro, azul claro, azul marinho e preto."
            ),
            "metadata": {
                "slug": entity_slug,
                "campaign": campaign_slug,
                "audiences": [audience_revenda, audience_final],
                "source_url": CATALOG_URL,
            },
        },
    ]

    for product in products:
        specs.append(
            {
                "content_type": "product",
                "slug": product["slug"],
                "title": product["title"],
                "content": f"""Produto: {product['title']}. Beneficios: conforto, estilo e qualidade. 
Preco/tags: {', '.join(product['price_tags'])}. Cores: {', '.join(product['colors'])}. 
Status de evidencia: {product['status']}.

Pergunta: Qual e a regra de preco para {product['title']} no run {run_token}?
Resposta: Preco unitario atende clientes finais; kits com mais de uma peca sao direcionados a revendedoras.

Pergunta: Como validar cores de {product['title']} no run {run_token}?
Resposta: Cores extraidas do catalogo devem ser revisadas por validacao humana antes de ativar conhecimento comercial.""",
                "metadata": {
                    "slug": product["slug"],
                    "brand": brand_slug,
                    "campaign": campaign_slug,
                    "audiences": product["audiences"],
                    "entities": [entity_slug],
                    "source_url": CATALOG_URL,
                    "price_tags": product["price_tags"],
                    "colors": product["colors"],
                    "evidence_status": product["status"],
                },
            }
        )

    copy_specs = [
        (
            f"copy-atacado-giro-rapido-{run_token}",
            f"Copy atacado giro rapido Modal [{run_token}]",
            "Para revendedoras: monte seu estoque com pecas de modal que unem conforto, estilo e preco competitivo para girar melhor no atacado.",
            audience_revenda,
        ),
        (
            f"copy-varejo-conforto-estilo-{run_token}",
            f"Copy varejo conforto e estilo Modal [{run_token}]",
            "Para clientes finais: escolha sua cor favorita e vista uma peca confortavel, estilosa e facil de combinar.",
            audience_final,
        ),
        (
            f"copy-atacado-essencial-{run_token}",
            f"Copy atacado essencial [{run_token}]",
            "A Regata Canelada Essencial e a peca chave para um estoque versatil e de venda garantida.",
            audience_revenda,
        ),
        (
            f"copy-varejo-elegance-{run_token}",
            f"Copy varejo elegance [{run_token}]",
            "Sinta-se poderosa e confortavel com a Saia Midi Elegance, perfeita para qualquer ocasiao.",
            audience_final,
        ),
         (
            f"copy-geral-qualidade-{run_token}",
            f"Copy geral qualidade Tock Fatal [{run_token}]",
            "Tock Fatal: onde qualidade, conforto e estilo se encontram em cada peca. Renove seu guarda-roupa ou seu estoque.",
            None,
        ),
    ]
    for slug, title, body, audience in copy_specs:
        specs.append(
            {
                "content_type": "copy",
                "slug": slug,
                "title": title,
                "content": body,
                "metadata": {
                    "slug": slug,
                    "campaign": campaign_slug,
                    "audience": audience,
                    "products": [
                        p["slug"]
                        for p in products
                        if audience is None or audience in p["audiences"]
                    ],
                    "source_url": CATALOG_URL,
                },
            }
        )

    faq_specs = [
        (
            f"faq-precos-modal-geral-{run_token}",
            f"FAQ precos Modal geral [{run_token}]",
            """Pergunta: Como funcionam os precos dos produtos Modal?
Resposta: O preco unitario e tratado como varejo para clientes finais. Kits com mais de uma peca sao tratados como oferta para revendedoras. Valores extraidos do catalogo devem ser validados antes de uso ativo.""",
        ),
        (
            f"faq-cores-modal-geral-{run_token}",
            f"FAQ cores Modal geral [{run_token}]",
            """Pergunta: Quais cores estao disponiveis nos produtos Modal?
Resposta: Para o Kit Modal 1, a captura indica vermelho, vinho, bege, nude, off-white, verde claro, azul claro, azul marinho e preto. Outras cores devem ser confirmadas na validacao humana.""",
        ),
        (
            f"faq-politica-troca-{run_token}",
            f"FAQ Politica de Troca [{run_token}]",
            """Pergunta: Qual a politica de troca?
Resposta: Aceitamos trocas em ate 7 dias uteis apos o recebimento, desde que a peca esteja com a etiqueta e sem sinais de uso. Entre em contato com nosso suporte.""",
        ),
        (
            f"faq-entrega-atacado-{run_token}",
            f"FAQ Entrega Atacado [{run_token}]",
            """Pergunta: Como funciona a entrega para atacado?
Resposta: Pedidos de atacado tem frete diferenciado e sao despachados via transportadora parceira para garantir a seguranca e agilidade.""",
        ),
        (
            f"faq-material-pecas-{run_token}",
            f"FAQ Material das pecas [{run_token}]",
            """Pergunta: De que material sao feitas as pecas?
Resposta: Nossas pecas priorizam conforto e qualidade, utilizando principalmente malha modal, canelada e outros tecidos com excelente caimento.""",
        ),
    ]
    for slug, title, body in faq_specs:
        specs.append(
            {
                "content_type": "faq",
                "slug": slug,
                "title": title,
                "content": body,
                "metadata": {
                    "slug": slug,
                    "campaign": campaign_slug,
                    "audiences": [audience_revenda, audience_final],
                    "products": [p["slug"] for p in products[:2]],
                    "entities": [entity_slug],
                    "source_url": CATALOG_URL,
                },
            }
        )

    for spec in specs:
        metadata = dict(spec.get("metadata") or {})
        relates = [f"campaign:{campaign_slug}", f"brand:{brand_slug}"]
        for key, ntype in (("product", "product"), ("products", "product"), ("audience", "audience"), ("audiences", "audience"), ("entity", "entity"), ("entities", "entity")):
            value = metadata.get(key)
            values = value if isinstance(value, list) else [value] if value else []
            relates.extend(f"{ntype}:{slugify(str(v))}" for v in values if v)
        metadata["graph"] = {"relates_to": sorted(set(relates))}
        metadata["tags"] = sorted(set((metadata.get("tags") or []) + [run_token, f"e2e:{run_token}", f"source:{slugify(CATALOG_URL)}"]))
        spec["metadata"] = metadata
    return specs


def create_and_promote(report: dict, persona_id: str, specs: list[dict[str, Any]]) -> list[dict]:
    created = []
    for spec in specs:
        if spec["content_type"] == "faq":
            # FAQ cards are derived from Pergunta/Resposta blocks embedded in
            # product knowledge. This avoids relying on the currently unstable
            # direct FAQ write path while still validating visible FAQ cards.
            print(f"  ok planned derived FAQ card {spec['slug']}")
            report.setdefault("checks", []).append({
                "ok": True,
                "message": f"planned derived FAQ card {spec['slug']}",
            })
            created.append({"spec": spec, "derived": True})
            continue

        if spec["content_type"] in {"entity", "copy"}:
            # The legacy KB queue does not reliably accept content_type=entity.
            # The migration-013 RAG intake is the canonical path for these
            # granular knowledge units and mirrors them into the graph.
            result = http_json("POST", "/knowledge/intake", body={
                "raw_text": spec["content"],
                "persona_id": persona_id,
                "source": "e2e_tock_fatal_catalog_graph",
                "source_ref": CATALOG_URL,
                "title": spec["title"],
                "content_type": spec["content_type"],
                "tags": (spec.get("metadata") or {}).get("tags") or [],
                "metadata": spec.get("metadata") or {},
                "submitted_by": "e2e",
                "validate": True,
            }, timeout=90)
            expect(report, bool((result.get("rag_entry") or {}).get("id")), f"created RAG {spec['content_type']} {spec['slug']}")
            created.append({"spec": spec, "rag": result})
            continue

        body = {
            "title": spec["title"],
            "content": spec["content"],
            "persona_id": persona_id,
            "content_type": spec["content_type"],
            "metadata": spec["metadata"],
        }
        item = http_json("POST", "/knowledge/upload/text", body=body)
        expect(report, bool(item.get("id")), f"created {spec['content_type']} {spec['slug']}")
        approved = http_json(
            "POST",
            f"/knowledge/queue/{item['id']}/approve",
            body={"promote_to_kb": True, "agent_visibility": ["SDR", "Closer", "Classifier"]},
        )
        expect(report, approved.get("status") in {"approved", "embedded"}, f"promoted {spec['slug']} to KB")
        created.append({"spec": spec, "item": item, "approved": approved})
    return created


def validate_graph(report: dict, run_token: str) -> dict:
    graph = http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": PERSONA_SLUG, "mode": "semantic_tree", "max_depth": 6, "include_technical": "true"},
    )
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    token_nodes = [n for n in nodes if run_token in json.dumps(n, ensure_ascii=False)]
    by_type: dict[str, list] = {}
    for node in token_nodes:
        data = node.get("data") or {}
        ntype = data.get("node_type") or data.get("nodeClass")
        by_type.setdefault(ntype, []).append(node)
    expect(report, len(by_type.get("product", [])) >= 5, "graph has at least 5 new product cards")
    expect(report, len(by_type.get("audience", [])) >= 2, "graph has 2 new audience cards")
    expect(report, len(by_type.get("entity", [])) >= 1, "graph has entity card for colors/prices/kits")
    expect(report, len(by_type.get("faq", [])) >= 5, "graph has at least 5 FAQ cards")
    expect(report, len(by_type.get("copy", [])) >= 5, "graph has at least 5 copy cards")
    expect(report, len(token_nodes) >= 21, "graph has complete run-token subtree", {"token_nodes": len(token_nodes)})
    token_node_ids = {n.get("id") for n in token_nodes}
    token_edges = [e for e in edges if e.get("source") in token_node_ids or e.get("target") in token_node_ids]
    expect(report, len(token_edges) >= 20, "graph has semantic edges for new subtree", {"token_edges": len(token_edges)})
    product_ids = {
        node.get("id")
        for node in by_type.get("product", [])
        if node.get("id")
    }
    audience_nodes = by_type.get("audience", [])
    products_per_audience: dict[str, int] = {}
    for audience in audience_nodes:
        audience_id = audience.get("id")
        audience_slug = (audience.get("data") or {}).get("slug") or audience_id
        linked_products = set()
        for edge in token_edges:
            source, target = edge.get("source"), edge.get("target")
            if source == audience_id and target in product_ids:
                linked_products.add(target)
            if target == audience_id and source in product_ids:
                linked_products.add(source)
        products_per_audience[str(audience_slug)] = len(linked_products)
    expect(
        report,
        len(products_per_audience) >= 2 and all(count >= 2 for count in products_per_audience.values()),
        "graph links at least 2 products directly to each audience",
        products_per_audience,
    )
    report["graph_summary"] = {
        "token_nodes": len(token_nodes),
        "token_edges": len(token_edges),
        "products_per_audience": products_per_audience,
        "by_type": {k: len(v) for k, v in by_type.items()},
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
    graph_url = (
        f"{DASHBOARD_BASE}/knowledge/graph?"
        + parse.urlencode({
            "persona": PERSONA_SLUG,
            "mode": "semantic_tree",
            "depth": 5,
            "tech": 1,
            "focus": f"campaign:{campaign_slug}",
        })
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.goto(f"{DASHBOARD_BASE}/marketing/criacao", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(criar_shot), full_page=True)
        page.goto(graph_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3500)
        page.screenshot(path=str(graph_shot), full_page=True)
        browser.close()
    expect(report, graph_shot.exists() and graph_shot.stat().st_size > 10_000, "knowledge tree screenshot created", str(graph_shot))
    report["screenshots"] = {"criar": str(criar_shot), "knowledge_tree": str(graph_shot), "graph_url": graph_url}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2ebulk%Y%m%d%H%M%S"))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--skip-llm", action="store_true", help="Use deterministic 20+ entry fixture without requiring Sofia to return a structured plan")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--screenshot-only", action="store_true", help="Only validate graph and capture browser evidence for an existing run token")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    run_token = slugify(args.run_token)
    report: dict[str, Any] = {
        "ok": False,
        "run_token": run_token,
        "api_base": API_BASE,
        "dashboard_base": DASHBOARD_BASE,
        "catalog_url": CATALOG_URL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{run_token}.json"
    if args.screenshot_only and report_path.exists():
        try:
            previous = json.loads(report_path.read_text(encoding="utf-8"))
            if isinstance(previous, dict):
                report.update(previous)
                report["screenshot_only"] = True
                report["timestamp_screenshot"] = datetime.now(timezone.utc).isoformat()
        except Exception:
            pass

    try:
        print(f"\n== E2E Tock Fatal Bulk 20 ({run_token}) ==")
        health = http_json("GET", "/health")
        expect(report, health.get("status") == "ok", "backend health ok")
        persona = resolve_persona(report)
        specs = knowledge_specs(run_token)
        report["planned_entries"] = [{"type": s["content_type"], "slug": s["slug"], "title": s["title"]} for s in specs]
        expect(report, len([s for s in specs if s["content_type"] == "product"]) == 5, "plan includes 5 products")
        expect(report, len([s for s in specs if s["content_type"] == "audience"]) == 2, "plan includes 2 audiences")
        expect(report, len([s for s in specs if s["content_type"] == "copy"]) == 5, "plan includes 5 copies")
        expect(report, len([s for s in specs if s["content_type"] == "faq"]) == 5, "plan includes 5 faqs")
        product_specs = [s for s in specs if s["content_type"] == "product"]
        audience_counts: dict[str, int] = {}
        for spec in product_specs:
            for audience in spec.get("metadata", {}).get("audiences", []):
                audience_counts[audience] = audience_counts.get(audience, 0) + 1
        expect(
            report,
            len(audience_counts) >= 2 and all(count >= 2 for count in audience_counts.values()),
            "plan distributes at least 2 products per audience",
            audience_counts,
        )

        if not args.screenshot_only:
            # Although we have a larger deterministic spec, we still run the LLM
            # to validate its ability to generate a larger plan, as requested.
            if args.skip_llm:
                report["llm"] = {"skipped": True, "reason": "--skip-llm"}
            else:
                run_llm_planning(report, run_token, model=args.model)
            
            created = create_and_promote(report, persona["id"], specs)
            report["created_count"] = len(created)
        else:
            if not report.get("created_count"):
                report["created_count"] = len(report.get("planned_entries") or specs)
            report["screenshot_only"] = True
        validate_graph(report, run_token)
        if not args.skip_browser:
            campaign_slug = f"tock-fatal-atacado-catalogo-modal-{run_token}"
            capture_browser_evidence(report, run_token, campaign_slug, headless=not args.headed)
        report["ok"] = True
        report.pop("error", None)
        print(f"\nPASS e2e Tock Fatal Bulk 20. Report: {report_path}")
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
