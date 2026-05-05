#!/usr/bin/env python3
"""E2E: VZ Lupas Oakley knowledge graph + manual UI edge creation.

This test intentionally does not skip Sofia/the model. It first asks Sofia to
produce a structured plan for the VZ Lupas Oakley graph, then persists a
deterministic validated set through /knowledge/intake so the graph can be
validated and manipulated through the UI.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-vz-lupas-oakley-graph-ui"
PERSONA_SLUG = "vz-lupas"
API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_BASE = os.environ.get("DASHBOARD_BASE", "http://localhost:3000").rstrip("/")


class TestFailure(Exception):
    pass


def slugify(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def http_json(method: str, path: str, *, params: dict | None = None, body: dict | None = None, timeout: float = 90.0, retries: int = 2) -> Any:
    url = API_BASE + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(retries + 1):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            if exc.code in {502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TestFailure(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TestFailure(f"{method} {path} -> connection failed: {exc}") from exc
    raise TestFailure(f"{method} {path} failed after retries")


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
    expect(report, bool(persona and persona.get("id")), "persona VZ Lupas exists")
    return persona


def llm_initial_context(run_token: str) -> str:
    return f"""# Plano confirmado pelo operador
persona_slug: vz-lupas
objetivo: criar conhecimento de públicos, produtos Oakley, FAQs, briefings, atributos, estilos e benefícios para VZ Lupas
saida esperada: knowledge_plan JSON + proposta markdown de grafo de conhecimento

## Blocos de conhecimento solicitados
- audience: Esportes, Street, Casual
- product: Juliet, Radar_EV, Romeo_2, Flak_2_0, Letch, Holbrook
- faq: perguntas e respostas por produto
- briefing: briefing por produto
- entity: atributos, estilos e beneficios

## Regras de teste
- use run_token: {run_token} em slugs/tags para isolar o teste
- nao pule o modelo; gere uma proposta estruturada antes do salvamento
- relacoes sao conceituais; o sistema final deve mostrar direcao como Entra/Sai na UI
"""


def llm_generation_prompt(run_token: str) -> str:
    return f"""
Sofia, gere agora um knowledge_plan para a persona VZ Lupas com a linha Oakley.

Publicos:
- Esportes
- Street
- Casual

Produtos:
- Juliet
- Radar_EV
- Romeo_2
- Flak_2_0
- Letch
- Holbrook

Grafo detalhado:
- Esportes conecta com Radar_EV e Flak_2_0. Motivacoes: Performance, Protecao UV, Leveza, Campo de visao amplo.
- Street conecta com Juliet e Romeo_2. Motivacoes: Estilo, Exclusividade, Identidade.
- Casual conecta com Holbrook e Letch. Motivacoes: Conforto, Versatilidade, Estetica limpa.

Para cada produto, gere atributos, FAQ e briefing:
- Radar EV: lente alta, Prizm, leve/ventilado. FAQ ciclismo/embaca. Briefing atleta/ciclista.
- Flak 2.0: ajuste firme, lentes intercambiaveis, resistencia. FAQ suor/troca lente.
- Juliet: design iconico, metal premium, raro. FAQ original/streetwear.
- Romeo 2: robustez, design agressivo, durabilidade. FAQ pesado/resistente.
- Holbrook: classico, leve, versatil. FAQ combina/confortavel.
- Letch: minimalista, moderno, leve. FAQ discreto/dia a dia.

Obrigatorio:
- incluir run_token "{run_token}" em slugs ou tags;
- gerar entries atomicas para publicos, produtos, FAQs, briefings, atributos, estilos e beneficios;
- responder exclusivamente com um bloco <knowledge_plan> JSON valido e nada fora da tag;
- usar esta forma exata: <knowledge_plan>{{"entries":[...]}}</knowledge_plan>;
- nao salvar ainda.
""".strip()


def extract_plan(text: str) -> dict:
    match = re.search(r"<knowledge_plan>\s*(.*?)\s*</knowledge_plan>", text or "", re.DOTALL)
    raw = match.group(1).strip() if match else ""
    if not raw and "<knowledge_plan>" in (text or ""):
        raw = (text or "").split("<knowledge_plan>", 1)[1].strip()
        start = raw.find("{")
        if start >= 0:
            depth = 0
            end = -1
            in_string = False
            escaped = False
            for index, char in enumerate(raw[start:], start=start):
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            raw = raw[start:end] if end > start else ""
    if not raw:
        raise TestFailure("Sofia response did not include <knowledge_plan>")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TestFailure(f"Sofia knowledge_plan is invalid JSON: {exc}") from exc


def run_sofia_plan(report: dict, run_token: str, model: str) -> dict:
    started = http_json("POST", "/kb-intake/start", body={
        "model": model,
        "agent_key": "sofia",
        "initial_context": llm_initial_context(run_token),
    }, timeout=90)
    session_id = started.get("session_id")
    expect(report, bool(session_id), "Sofia session started", started.get("agent"))
    message = ""
    plan = None
    prompts = [
        llm_generation_prompt(run_token),
        (
            "A resposta anterior nao cumpriu o contrato. Responda agora somente com "
            f"<knowledge_plan>{{\"entries\":[...]}}</knowledge_plan>, JSON valido, "
            f"incluindo run_token {run_token} em slugs ou tags. Nao escreva markdown fora da tag."
        ),
    ]
    last_error: Exception | None = None
    for prompt in prompts:
        response = http_json("POST", "/kb-intake/message", body={
            "session_id": session_id,
            "message": prompt,
        }, timeout=240)
        message = response.get("message") or ""
        try:
            plan = extract_plan(message)
            break
        except TestFailure as exc:
            last_error = exc
    if plan is None:
        report["llm"] = {"session_id": session_id, "model": model, "message_preview": message[:1800]}
        raise last_error or TestFailure("Sofia response did not include <knowledge_plan>")
    entries = plan.get("entries") or []
    by_type: dict[str, int] = {}
    for entry in entries:
        by_type[entry.get("content_type") or "unknown"] = by_type.get(entry.get("content_type") or "unknown", 0) + 1
    expect(report, len(entries) >= 18, "Sofia generated a substantial VZ Lupas plan", by_type)
    expect(report, run_token in json.dumps(plan, ensure_ascii=False), "Sofia plan carries run token")
    report["llm"] = {"session_id": session_id, "model": model, "entry_counts": by_type, "message_preview": message[:1800]}
    return plan


def specs(run_token: str) -> list[dict[str, Any]]:
    rt = run_token
    audiences = {
        "esportes": {
            "title": f"Publico Esportes VZ Lupas [{rt}]",
            "content": "Publico Esportes: busca performance, protecao UV, leveza e campo de visao amplo.",
            "products": ["radar-ev", "flak-2-0"],
            "benefits": ["performance", "protecao-uv", "leveza", "campo-de-visao-amplo"],
        },
        "street": {
            "title": f"Publico Street VZ Lupas [{rt}]",
            "content": "Publico Street: valoriza estilo, exclusividade e identidade visual.",
            "products": ["juliet", "romeo-2"],
            "benefits": ["estilo", "exclusividade", "identidade"],
        },
        "casual": {
            "title": f"Publico Casual VZ Lupas [{rt}]",
            "content": "Publico Casual: busca conforto, versatilidade e estetica limpa.",
            "products": ["holbrook", "letch"],
            "benefits": ["conforto", "versatilidade", "estetica-limpa"],
        },
    }
    products = {
        "radar-ev": {
            "title": f"Produto Radar EV Oakley [{rt}]",
            "audience": "esportes",
            "attrs": ["Lente alta com campo expandido", "Tecnologia Prizm", "Leve e ventilado"],
            "faq": [("Serve para ciclismo?", "Sim, ideal para alta performance."), ("Embaca?", "Nao, possui ventilacao otimizada.")],
            "briefing": "Persona: atleta/ciclista. Dor: visao limitada + desconforto. Promessa: maxima performance visual. Tom: tecnico + autoridade.",
        },
        "flak-2-0": {
            "title": f"Produto Flak 2.0 Oakley [{rt}]",
            "audience": "esportes",
            "attrs": ["Ajuste firme", "Lentes intercambiaveis", "Resistencia"],
            "faq": [("Escorrega no suor?", "Nao, grip esportivo."), ("Da pra trocar lente?", "Sim.")],
            "briefing": "Persona: esportista versatil. Dor: oculos instavel. Promessa: estabilidade total. Tom: confiavel + funcional.",
        },
        "juliet": {
            "title": f"Produto Juliet Oakley [{rt}]",
            "audience": "street",
            "attrs": ["Design iconico", "Metal premium", "Raro"],
            "faq": [("E original?", "Verificar certificacao."), ("Combina com streetwear?", "Sim, peca iconica.")],
            "briefing": "Persona: hype/streetwear. Dor: falta de identidade. Promessa: estilo unico. Tom: aspiracional + exclusivo.",
        },
        "romeo-2": {
            "title": f"Produto Romeo 2 Oakley [{rt}]",
            "audience": "street",
            "attrs": ["Robustez", "Design agressivo", "Alta durabilidade"],
            "faq": [("E pesado?", "Mais robusto, sim."), ("E resistente?", "Muito.")],
            "briefing": "Persona: urbano/edgy. Dor: produtos frageis. Promessa: resistencia + presenca. Tom: forte + ousado.",
        },
        "holbrook": {
            "title": f"Produto Holbrook Oakley [{rt}]",
            "audience": "casual",
            "attrs": ["Classico", "Leve", "Versatil"],
            "faq": [("Combina com tudo?", "Sim, estilo universal."), ("E confortavel?", "Muito.")],
            "briefing": "Persona: lifestyle. Dor: indecisao de estilo. Promessa: combina com tudo. Tom: simples + elegante.",
        },
        "letch": {
            "title": f"Produto Letch Oakley [{rt}]",
            "audience": "casual",
            "attrs": ["Minimalista", "Moderno", "Leve"],
            "faq": [("E discreto?", "Sim."), ("Serve pro dia a dia?", "Perfeito.")],
            "briefing": "Persona: casual moderno. Dor: excesso de informacao visual. Promessa: simplicidade premium. Tom: clean + contemporaneo.",
        },
    }
    out: list[dict[str, Any]] = []
    for slug, item in audiences.items():
        out.append({
            "content_type": "audience",
            "slug": f"publico-{slug}-{rt}",
            "title": item["title"],
            "content": item["content"],
            "metadata": {"slug": f"publico-{slug}-{rt}", "tags": [rt, "vz-lupas", "oakley", slug], "products": [f"produto-{p}-{rt}" for p in item["products"]], "benefits": item["benefits"]},
        })
        for benefit in item["benefits"]:
            out.append({
                "content_type": "entity",
                "slug": f"beneficio-{benefit}-{slug}-{rt}",
                "title": f"Beneficio {benefit.replace('-', ' ').title()} [{slug}] [{rt}]",
                "content": f"Beneficio valorizado pelo publico {slug}: {benefit.replace('-', ' ')}.",
                "metadata": {"slug": f"beneficio-{benefit}-{slug}-{rt}", "tags": [rt, "beneficio", slug], "audience": f"publico-{slug}-{rt}"},
            })
    for slug, item in products.items():
        product_slug = f"produto-{slug}-{rt}"
        out.append({
            "content_type": "product",
            "slug": product_slug,
            "title": item["title"],
            "content": f"{item['title']}. Atributos: {', '.join(item['attrs'])}. {item['briefing']}",
            "metadata": {"slug": product_slug, "tags": [rt, "vz-lupas", "oakley", slug], "audiences": [f"publico-{item['audience']}-{rt}"]},
        })
        out.append({
            "content_type": "briefing",
            "slug": f"briefing-{slug}-{rt}",
            "title": f"Briefing {item['title']}",
            "content": item["briefing"],
            "metadata": {"slug": f"briefing-{slug}-{rt}", "tags": [rt, "briefing", slug], "product": product_slug},
        })
        out.append({
            "content_type": "entity",
            "slug": f"atributos-{slug}-{rt}",
            "title": f"Atributos {item['title']}",
            "content": "\n".join(f"- {attr}" for attr in item["attrs"]),
            "metadata": {"slug": f"atributos-{slug}-{rt}", "tags": [rt, "atributos", slug], "product": product_slug},
        })
        out.append({
            "content_type": "entity",
            "slug": f"estilo-{slug}-{rt}",
            "title": f"Estilo {item['title']}",
            "content": f"Estilo comercial associado ao produto {item['title']}.",
            "metadata": {"slug": f"estilo-{slug}-{rt}", "tags": [rt, "estilo", slug], "product": product_slug},
        })
        for idx, (question, answer) in enumerate(item["faq"], start=1):
            out.append({
                "content_type": "faq",
                "slug": f"faq-{slug}-{idx}-{rt}",
                "title": f"FAQ {item['title']} {idx}",
                "content": f"Pergunta: {question}\nResposta: {answer}",
                "metadata": {"slug": f"faq-{slug}-{idx}-{rt}", "tags": [rt, "faq", slug], "product": product_slug},
            })
    return out


def create_specs(report: dict, persona_id: str, items: list[dict[str, Any]]) -> None:
    run_token = ""
    if items:
        tags = (items[0].get("metadata") or {}).get("tags") or []
        run_token = next((tag for tag in tags if str(tag).startswith("e2evz")), "")
    entries = [
        {
            "content": spec["content"],
            "title": spec["title"],
            "content_type": spec["content_type"],
            "slug": spec["slug"],
            "tags": (spec.get("metadata") or {}).get("tags") or [],
            "metadata": spec.get("metadata") or {},
        }
        for spec in items
    ]
    result = http_json("POST", "/knowledge/intake/plan", body={
        "persona_id": persona_id,
        "run_token": run_token,
        "source": "e2e_vz_lupas_oakley_graph_ui",
        "source_ref": run_token,
        "entries": entries,
        "links": [],
        "submitted_by": "e2e",
        "validate": True,
    }, timeout=180)
    expect(report, result.get("ok") is True, "bulk created VZ Lupas knowledge plan", {
        "entries_created": result.get("entries_created"),
        "nodes_created": result.get("nodes_created"),
        "main_edges": result.get("main_edges"),
        "auxiliary_edges": result.get("auxiliary_edges"),
        "fallback_parent_count": result.get("fallback_parent_count"),
    })


def graph_nodes_by_slug(run_token: str) -> tuple[dict[str, dict], list[dict]]:
    graph = http_json("GET", "/knowledge/graph-data", params={"persona_slug": PERSONA_SLUG, "mode": "graph", "max_depth": 6})
    nodes = graph.get("nodes") or []
    by_slug = {}
    for node in nodes:
        data = node.get("data") or {}
        slug = data.get("slug")
        if slug and run_token in json.dumps(node, ensure_ascii=False):
            by_slug[slug] = node
    return by_slug, graph.get("edges") or []


def create_base_edges(report: dict, run_token: str, persona_id: str) -> None:
    by_slug, _ = graph_nodes_by_slug(run_token)

    def node_id(slug: str) -> str:
        node = by_slug.get(slug)
        if not node:
            raise TestFailure(f"node not found for slug {slug}")
        return node["id"]

    edge_specs = []
    products = ["radar-ev", "flak-2-0", "juliet", "romeo-2", "holbrook", "letch"]
    audience_products = {
        "publico-esportes": ["radar-ev", "flak-2-0"],
        "publico-street": ["juliet", "romeo-2"],
        "publico-casual": ["holbrook", "letch"],
    }
    for audience_prefix, product_list in audience_products.items():
        for product in product_list:
            edge_specs.append((f"{audience_prefix}-{run_token}", f"produto-{product}-{run_token}"))
    audience_benefits = {
        "publico-esportes": ["performance", "protecao-uv", "leveza", "campo-de-visao-amplo"],
        "publico-street": ["estilo", "exclusividade", "identidade"],
        "publico-casual": ["conforto", "versatilidade", "estetica-limpa"],
    }
    for audience_prefix, benefit_list in audience_benefits.items():
        audience = audience_prefix.replace("publico-", "")
        for benefit in benefit_list:
            edge_specs.append((f"{audience_prefix}-{run_token}", f"beneficio-{benefit}-{audience}-{run_token}"))
    for product in products:
        pslug = f"produto-{product}-{run_token}"
        edge_specs.extend([
            (pslug, f"faq-{product}-1-{run_token}"),
            (pslug, f"faq-{product}-2-{run_token}"),
            (pslug, f"briefing-{product}-{run_token}"),
            (pslug, f"atributos-{product}-{run_token}"),
            (pslug, f"estilo-{product}-{run_token}"),
        ])

    for source_slug, target_slug in edge_specs:
        created = http_json("POST", "/knowledge/graph-edges", body={
            "source_node_id": node_id(source_slug),
            "target_node_id": node_id(target_slug),
            "relation_type": "manual",
            "persona_id": persona_id,
            "weight": 1,
            "metadata": {"run_token": run_token, "source": "e2e_api_seed"},
        })
        expect(report, bool((created.get("edge") or {}).get("id")), f"seed edge {source_slug} -> {target_slug}")


def create_ui_edge(report: dict, run_token: str, *, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise TestFailure("playwright is required for the UI edge test") from exc

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    shot = ARTIFACTS_DIR / f"graph-ui-edge-{run_token}.png"
    url = f"{DASHBOARD_BASE}/knowledge/graph?" + parse.urlencode({
        "persona": PERSONA_SLUG,
        "mode": "graph",
        "depth": 5,
    })
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.get_by_placeholder(re.compile("Buscar")).fill(run_token)
        page.wait_for_timeout(1500)

        source = page.locator(".react-flow__node", has_text=f"Produto Holbrook Oakley [{run_token}]").first
        target = page.locator(".react-flow__node", has_text=f"Beneficio Versatilidade [casual] [{run_token}]").first
        expect(report, source.count() > 0, "UI source node Holbrook visible")
        expect(report, target.count() > 0, "UI target node benefit visible")
        source.scroll_into_view_if_needed()
        target.scroll_into_view_if_needed()
        src_box = source.locator(".react-flow__handle-bottom").bounding_box()
        tgt_box = target.locator(".react-flow__handle-top").bounding_box()
        if not src_box or not tgt_box:
            raise TestFailure("Could not locate visible graph handles")
        page.mouse.move(src_box["x"] + src_box["width"] / 2, src_box["y"] + src_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(tgt_box["x"] + tgt_box["width"] / 2, tgt_box["y"] + tgt_box["height"] / 2, steps=18)
        page.mouse.up()
        page.wait_for_timeout(2200)
        page.screenshot(path=str(shot), full_page=True)
        browser.close()
    expect(report, shot.exists() and shot.stat().st_size > 10_000, "UI graph edge screenshot created", str(shot))
    report["ui"] = {"graph_url": url, "screenshot": str(shot)}


def validate(report: dict, run_token: str, expected_min_edges: int) -> None:
    by_slug, edges = graph_nodes_by_slug(run_token)
    required = [
        "campanha-oakley-vz-lupas",
        "publico-esportes",
        "publico-street",
        "publico-casual",
        "produto-juliet",
        "produto-radar-ev",
        "produto-romeo-2",
        "produto-flak-2-0",
        "produto-letch",
        "produto-holbrook",
    ]
    for prefix in required:
        expect(report, f"{prefix}-{run_token}" in by_slug, f"graph contains {prefix}")
    node_ids = {node["id"] for node in by_slug.values()}
    token_edges = [edge for edge in edges if edge.get("source") in node_ids or edge.get("target") in node_ids]
    expect(report, len(token_edges) >= expected_min_edges, "graph contains seeded VZ Lupas edges", len(token_edges))
    auxiliary_relations = {"has_tag", "mentions", "same_topic_as", "derived_from"}
    visible_nodes = [
        node for node in by_slug.values()
        if (node.get("data") or {}).get("node_type") not in {"tag", "mention"}
    ]
    primary_degree: dict[str, int] = {node["id"]: 0 for node in visible_nodes}
    for edge in edges:
        relation = ((edge.get("data") or {}).get("relation_type") or "").lower()
        if relation in auxiliary_relations:
            continue
        if edge.get("source") in primary_degree:
            primary_degree[edge["source"]] += 1
        if edge.get("target") in primary_degree:
            primary_degree[edge["target"]] += 1
    orphan_slugs = [
        (node.get("data") or {}).get("slug") or node["id"]
        for node in visible_nodes
        if primary_degree.get(node["id"], 0) == 0
    ]
    expect(report, not orphan_slugs, "all VZ Lupas nodes have a primary tree connection", orphan_slugs[:12])

    campaign = by_slug.get(f"campanha-oakley-vz-lupas-{run_token}")
    campaign_has_parent = False
    if campaign:
        for edge in edges:
            relation = ((edge.get("data") or {}).get("relation_type") or "").lower()
            if edge.get("target") == campaign["id"] and relation not in auxiliary_relations:
                campaign_has_parent = True
                break
    expect(report, campaign_has_parent, "campaign has a structural parent edge")

    briefing_orphans = []
    for slug, node in by_slug.items():
        if not slug.startswith("briefing-"):
            continue
        if primary_degree.get(node["id"], 0) == 0:
            briefing_orphans.append(slug)
    expect(report, not briefing_orphans, "all briefings have a structural parent", briefing_orphans[:12])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2evz%Y%m%d%H%M%S"))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument("--ui-only", action="store_true")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    run_token = slugify(args.run_token)
    report: dict[str, Any] = {
        "ok": False,
        "run_token": run_token,
        "api_base": API_BASE,
        "dashboard_base": DASHBOARD_BASE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{run_token}.json"
    try:
        print(f"\n== E2E VZ Lupas Oakley Graph UI ({run_token}) ==")
        health = http_json("GET", "/health")
        expect(report, health.get("status") == "ok", "backend health ok")
        persona = resolve_persona(report)
        if args.seed_only:
            report["mode"] = "seed-only"
            existing, _ = graph_nodes_by_slug(run_token)
            items = [item for item in specs(run_token) if item["slug"] not in existing]
            report["planned_entries"] = [{"type": item["content_type"], "slug": item["slug"], "title": item["title"]} for item in items]
            create_specs(report, persona["id"], items)
            time.sleep(1.5)
            validate(report, run_token, 24)
            report["ok"] = True
            print(f"\nPASS e2e VZ Lupas Oakley Graph UI. Report: {report_path}")
            return 0
        if args.ui_only:
            report["mode"] = "ui-only"
            create_base_edges(report, run_token, persona["id"])
            if not args.skip_browser:
                create_ui_edge(report, run_token, headless=not args.headed)
            expected_min_edges = 24 if args.skip_browser else 25
            validate(report, run_token, expected_min_edges)
            report["ok"] = True
            print(f"\nPASS e2e VZ Lupas Oakley Graph UI. Report: {report_path}")
            return 0
        run_sofia_plan(report, run_token, args.model)
        items = specs(run_token)
        report["planned_entries"] = [{"type": item["content_type"], "slug": item["slug"], "title": item["title"]} for item in items]
        create_specs(report, persona["id"], items)
        # Let graph mirror writes settle behind Supabase/PostgREST.
        time.sleep(1.5)
        if not args.skip_browser:
            create_ui_edge(report, run_token, headless=not args.headed)
        expected_min_edges = 24 if args.skip_browser else 25
        validate(report, run_token, expected_min_edges)
        report["ok"] = True
        print(f"\nPASS e2e VZ Lupas Oakley Graph UI. Report: {report_path}")
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
