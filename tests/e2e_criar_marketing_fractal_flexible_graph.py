#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2E: CRIAR marketing fractal flexible graph.

Uses the existing repo E2E pattern: Python + HTTP API + optional Playwright
screenshot. It bypasses the LLM by writing a deterministic Sofia session with
a <knowledge_plan>, then calls the same /kb-intake/save endpoint used by the
frontend.

Required env:
  ADMIN_EMAIL / ADMIN_PASSWORD
  API_BASE (default http://localhost:8000)
  DASHBOARD_BASE (default http://localhost:3000, only for optional screenshot)

Run:
  python tests/e2e_criar_marketing_fractal_flexible_graph.py --skip-browser
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
SESSION_DIR = API_DIR / ".runtime" / "kb-intake-sessions"
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-criar-marketing-fractal-flexible-graph"
PERSONA_SLUG = "tock-fatal"
API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_BASE = os.environ.get("DASHBOARD_BASE", "http://localhost:3000").rstrip("/")

for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

load_dotenv(ROOT / ".env")
load_dotenv(API_DIR / ".env")

_COOKIE_JAR = http.cookiejar.CookieJar()
_HTTP = request.build_opener(request.HTTPCookieProcessor(_COOKIE_JAR))


class TestFailure(Exception):
    pass


def slugify(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def http_json(method: str, path: str, *, params: dict | None = None, body: dict | None = None, timeout: float = 60) -> Any:
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
        with _HTTP.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
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


def login(report: dict, identifier: str, password: str) -> None:
    session = http_json("POST", "/auth/login", body={"identifier": identifier, "password": password, "remember": False}, timeout=30)
    expect(report, bool((session or {}).get("user", {}).get("id")), "auth login ok")
    expect(report, any(cookie.name == "ai_brain_session" for cookie in _COOKIE_JAR), "session cookie captured")


def marketing_plan(run_token: str) -> dict:
    suffix = run_token.lower()
    briefing = f"briefing-tock-fatal-{suffix}"
    audience = f"audience-mulheres-simples-mato-grande-{suffix}"
    product = f"produto-kit-5-pecas-modal-{suffix}"
    copy = f"copy-kit-5-pecas-{suffix}"
    faq1 = f"faq-kit-5-pecas-modal-{suffix}"
    faq2 = f"faq-preco-kit-5-pecas-modal-{suffix}"
    return {
        "source": "https://tockfatal.com",
        "persona_slug": PERSONA_SLUG,
        "validation_policy": "human_validation_required",
        "entries": [
            {
                "content_type": "briefing",
                "title": f"Briefing Tock Fatal {run_token}",
                "slug": briefing,
                "status": "pendente_validacao",
                "content": "Briefing vendendo para mulheres simples do Mato Grande roupas elegantes em preco acessivel, buscando revendedoras de pequena escala.",
                "tags": ["briefing", run_token],
                "metadata": {"parent_slug": PERSONA_SLUG, "briefing_scope": "global", "governs_children": True},
            },
            {
                "content_type": "audience",
                "title": f"Mulheres simples do Mato Grande {run_token}",
                "slug": audience,
                "status": "pendente_validacao",
                "content": "Publico de mulheres simples do Mato Grande, com foco em revendedoras de pequena escala.",
                "tags": ["audience", "mato-grande", run_token],
                "metadata": {"parent_slug": briefing},
            },
            {
                "content_type": "product",
                "title": f"Kit 5 pecas de modal {run_token}",
                "slug": product,
                "status": "pendente_validacao",
                "content": "Produto kit de 5 pecas de modal de fabricacao propria. Preco deve ficar pendente de validacao.",
                "tags": ["product", "modal", run_token],
                "metadata": {"parent_slug": audience, "attributes": {"material": "modal", "pecas": 5}},
            },
            {
                "content_type": "copy",
                "title": f"Copy kit 5 pecas {run_token}",
                "slug": copy,
                "status": "pendente_validacao",
                "content": "Copy comercial para apresentar o kit de 5 pecas como opcao elegante e acessivel para revenda.",
                "tags": ["copy", run_token],
                "metadata": {"parent_slug": product},
            },
            {
                "content_type": "faq",
                "title": f"FAQ kit 5 pecas modal {run_token}",
                "slug": faq1,
                "status": "pendente_validacao",
                "content": "Pergunta: O que vem no kit de 5 pecas de modal?\nResposta: O kit reune 5 pecas de modal de fabricacao propria, pensado para revendedoras de pequena escala.",
                "tags": ["faq", "modal", run_token],
                "metadata": {"parent_slug": copy},
            },
            {
                "content_type": "faq",
                "title": f"FAQ preco kit 5 pecas modal {run_token}",
                "slug": faq2,
                "status": "pendente_validacao",
                "content": "Pergunta: Qual o preco do kit de 5 pecas de modal?\nResposta: O preco precisa ser confirmado na fonte ou pela equipe antes de ser tratado como fato aprovado.",
                "tags": ["faq", "preco", run_token],
                "metadata": {"parent_slug": copy},
            },
        ],
        "tree_mode": "single_branch",
        "branch_policy": "ask_before_new_branch",
    }


def write_session(run_token: str, plan: dict) -> str:
    session_id = f"e2e-criar-fractal-{run_token}"
    payload = json.dumps(plan, ensure_ascii=False)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session = {
        "id": session_id,
        "model": "gpt-4o-mini",
        "agent_key": "sofia",
        "stage": "ready_to_save",
        "classification": {
            "persona_slug": PERSONA_SLUG,
            "content_type": "briefing",
            "title": f"CRIAR fractal marketing {run_token}",
            "asset_type": None,
            "asset_function": None,
        },
        "context": (
            "persona=tock-fatal\n"
            "blocos=briefing,audience,product,copy,faq\n"
            "- faq: 2 variacoes\n"
            "fonte principal: https://tockfatal.com"
        ),
        "messages": [
            {"role": "user", "content": "briefing vendendo para mulheres simples do Mato Grande roupas elegantes em um preco acessivel, buscando revendedoras de pequena escala. produto kit de 5 pecas de modal fabricacao propria. fonte tockfatal.com"},
            {"role": "assistant", "content": f"<knowledge_plan>\n{payload}\n</knowledge_plan>\nPlano pronto. Clique em **Salvar** para persistir."},
        ],
        "last_proposed_plan": plan,
        "mission_state": {
            "persona": PERSONA_SLUG,
            "knowledge_blocks": ["briefing", "audience", "product", "copy", "faq"],
            "status": "ready_to_save",
        },
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": False},
    }
    (SESSION_DIR / f"{session_id}.json").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return session_id


def db_client():
    from services import supabase_client
    return supabase_client.get_client()


def persona_id_for(slug: str) -> str:
    rows = db_client().table("personas").select("id").eq("slug", slug).limit(1).execute().data or []
    if not rows:
        raise TestFailure(f"persona not found: {slug}")
    return rows[0]["id"]


def rows_by_session(table: str, session_id: str, persona_id: str) -> list[dict]:
    rows = db_client().table(table).select("*").eq("persona_id", persona_id).limit(5000).execute().data or []
    return [row for row in rows if (row.get("metadata") or {}).get("session_id") == session_id]


def fetch_edges_for_nodes(node_ids: list[str]) -> list[dict]:
    if not node_ids:
        return []
    return db_client().table("knowledge_edges").select("*").in_("source_node_id", node_ids).limit(5000).execute().data or []


def validate_db_after_save(report: dict, session_id: str, run_token: str, persona_id: str) -> tuple[list[dict], list[dict], list[dict]]:
    items = rows_by_session("knowledge_items", session_id, persona_id)
    expect(report, len(items) == 6, "DB has 6 knowledge_items for session", Counter(row.get("content_type") for row in items))
    counts = Counter(row.get("content_type") for row in items)
    expect(report, counts == {"briefing": 1, "audience": 1, "product": 1, "copy": 1, "faq": 2}, "DB item type counts match fractal marketing plan", dict(counts))
    for item in items:
        meta = item.get("metadata") or {}
        expect(report, item.get("persona_id") == persona_id, f"item persona scoped: {item.get('title')}")
        expect(report, meta.get("session_id") == session_id, f"item session scoped: {item.get('title')}")
        expect(report, (meta.get("classification") or {}).get("content_type") == item.get("content_type"), f"classification content_type matches item: {item.get('title')}")

    node_ids = [(item.get("metadata") or {}).get("knowledge_node_id") for item in items]
    node_ids = [node_id for node_id in node_ids if node_id]
    nodes = db_client().table("knowledge_nodes").select("*").in_("id", node_ids).limit(100).execute().data or []
    expect(report, len(nodes) == 6, "DB has 6 canonical graph nodes for session")
    expect(report, not any(node.get("node_type") == "mention" for node in nodes), "DB has 0 mention nodes for session")
    briefing = next(node for node in nodes if node.get("node_type") == "briefing")
    audience = next(node for node in nodes if node.get("node_type") == "audience")
    product = next(node for node in nodes if node.get("node_type") == "product")
    expect(report, (briefing.get("metadata") or {}).get("quarantine_state") != "structural", "briefing is not quarantined")
    expect(report, (audience.get("metadata") or {}).get("audience_source") == "manual", "audience has import/leads placeholder metadata")
    expect(report, "crm_filters" in (audience.get("metadata") or {}), "audience has crm_filters placeholder")
    expect(report, (product.get("metadata") or {}).get("product_source") == "manual", "product has product_source placeholder")
    expect(report, (product.get("metadata") or {}).get("price_status") == "pending_validation", "product price is pending validation")
    expect(report, (product.get("metadata") or {}).get("stock_status") == "unknown", "product stock is unknown")

    by_slug = {node["slug"]: node for node in nodes}
    persona_root = db_client().table("knowledge_nodes").select("*").eq("persona_id", persona_id).eq("node_type", "persona").eq("slug", "self").limit(1).execute().data[0]
    edges = fetch_edges_for_nodes([persona_root["id"], *[node["id"] for node in nodes]])
    expected_pairs = [
        (persona_root["id"], by_slug[f"briefing-tock-fatal-{run_token.lower()}"]["id"]),
        (by_slug[f"briefing-tock-fatal-{run_token.lower()}"]["id"], by_slug[f"audience-mulheres-simples-mato-grande-{run_token.lower()}"]["id"]),
        (by_slug[f"audience-mulheres-simples-mato-grande-{run_token.lower()}"]["id"], by_slug[f"produto-kit-5-pecas-modal-{run_token.lower()}"]["id"]),
        (by_slug[f"produto-kit-5-pecas-modal-{run_token.lower()}"]["id"], by_slug[f"copy-kit-5-pecas-{run_token.lower()}"]["id"]),
    ]
    faq_nodes = [node for node in nodes if node.get("node_type") == "faq"]
    expected_pairs.extend((by_slug[f"copy-kit-5-pecas-{run_token.lower()}"]["id"], faq["id"]) for faq in faq_nodes)
    edge_pairs = {(edge["source_node_id"], edge["target_node_id"]): edge for edge in edges}
    for pair in expected_pairs:
        edge = edge_pairs.get(pair)
        expect(report, bool(edge), f"primary edge exists {pair[0]} -> {pair[1]}")
        meta = (edge or {}).get("metadata") or {}
        expect(report, meta.get("active") is True and meta.get("primary_tree") is True and meta.get("visual_hidden") is not True, "primary edge is active visible")
    forbidden = [
        (persona_root["id"], by_slug[f"produto-kit-5-pecas-modal-{run_token.lower()}"]["id"]),
        (by_slug[f"produto-kit-5-pecas-modal-{run_token.lower()}"]["id"], persona_root["id"]),
    ]
    forbidden.extend((by_slug[f"produto-kit-5-pecas-modal-{run_token.lower()}"]["id"], faq["id"]) for faq in faq_nodes)
    for pair in forbidden:
        bad = [edge for edge in edges if (edge["source_node_id"], edge["target_node_id"]) == pair and (edge.get("metadata") or {}).get("primary_tree") is True and (edge.get("metadata") or {}).get("active") is not False]
        expect(report, not bad, f"forbidden visible primary edge absent {pair[0]} -> {pair[1]}")
    visible_primary_by_pair = Counter(
        (edge["source_node_id"], edge["target_node_id"])
        for edge in edges
        if (edge.get("metadata") or {}).get("primary_tree") is True
        and (edge.get("metadata") or {}).get("active") is not False
        and (edge.get("metadata") or {}).get("visual_hidden") is not True
    )
    duplicates = {pair: count for pair, count in visible_primary_by_pair.items() if count > 1}
    expect(report, not duplicates, "no duplicate visible primary_tree edges for the same source-target pair", duplicates)
    return items, nodes, edges


def validate_graph_data(report: dict, run_token: str) -> dict:
    graph = http_json("GET", "/knowledge/graph-data", params={"persona_slug": PERSONA_SLUG, "mode": "semantic_tree", "max_depth": 6}, timeout=60)
    token = run_token.lower()
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    token_nodes = [node for node in nodes if token in json.dumps(node, ensure_ascii=False).lower()]
    expect(report, len(token_nodes) >= 6, "graph-data returns the saved fractal subtree")
    for edge in edges:
        data = edge.get("data") or {}
        meta = data.get("metadata") or {}
        expect(report, meta.get("active") is not False, "graph-data does not return inactive edges")
        expect(report, meta.get("visual_hidden") is not True, "graph-data does not return visual_hidden edges")
        if not data.get("embedded_edge") and not data.get("gallery_edge") and not data.get("draft_terminal_edge"):
            expect(report, data.get("primary_tree") is True or meta.get("primary_tree") is True, "tree graph-data edge is primary")
    return graph


def approve_faqs_and_validate_rag(report: dict, items: list[dict], nodes: list[dict], persona_id: str) -> None:
    faq_items = [item for item in items if item.get("content_type") == "faq"]
    expect(report, len(faq_items) == 2, "two FAQ items ready for approval")
    for item in faq_items:
        result = http_json("POST", f"/knowledge/queue/{item['id']}/approve", body={"promote_to_kb": False}, timeout=120)
        expect(report, result.get("success") is True, "FAQ approval returns success=true", result)
        expect(report, bool(result.get("approved_snapshot_id")), "FAQ approval returns snapshot id")
        expect(report, bool(result.get("rag_entry_id")), "FAQ approval returns rag_entry_id")
        expect(report, bool(result.get("rag_chunk_ids")), "FAQ approval returns rag_chunk_ids")
        expect(report, bool(result.get("embedded_edge_id")), "FAQ approval materializes faq -> embedded edge")

        snapshot = db_client().table("approved_knowledge_snapshots").select("*").eq("id", result["approved_snapshot_id"]).limit(1).execute().data[0]
        expect(report, snapshot.get("status") == "active", "snapshot status active")
        expect(report, snapshot.get("content_type") == "faq", "snapshot content_type faq")
        root_node = db_client().table("knowledge_nodes").select("*").eq("id", snapshot.get("root_node_id")).limit(1).execute().data[0]
        expect(report, root_node.get("node_type") == "persona" and root_node.get("slug") == "self", "snapshot root_node_id is persona self")
        path = snapshot.get("hierarchy_path") or []
        types = [step.get("node_type") for step in path]
        expect(report, types.count("persona") == 1 and types[0] == "persona", "snapshot path has persona only at root", types)
        expect(report, "briefing" in types and "audience" in types and "product" in types and "copy" in types and "faq" in types, "snapshot path contains briefing/audience/product/copy/faq", types)

        chunks = db_client().table("knowledge_rag_chunks").select("*").eq("rag_entry_id", result["rag_entry_id"]).limit(20).execute().data or []
        expect(report, bool(chunks), "RAG chunks exist for approved FAQ")
        chunk = chunks[0]
        text = chunk.get("chunk_text") or ""
        meta = chunk.get("metadata") or {}
        expect(report, "Briefing:" in text and "Nao informado" not in text.split("Briefing:", 1)[1].splitlines()[0], "chunk includes briefing context")
        expect(report, "Publico:" in text and "Nao informado" not in text.split("Publico:", 1)[1].splitlines()[0], "chunk includes audience context")
        expect(report, "Produto:" in text and "Pergunta:" in text and "Resposta aprovada:" in text, "chunk includes product/question/answer")
        expect(report, meta.get("content_type") == "faq" and meta.get("status") == "active", "chunk metadata marks active FAQ")


def capture_browser(report: dict, run_token: str, *, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        report.setdefault("warnings", []).append("playwright not installed; browser screenshot skipped")
        print("  WARN playwright not installed; browser screenshot skipped")
        return
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    graph_url = f"{DASHBOARD_BASE}/knowledge/graph?persona={PERSONA_SLUG}&mode=semantic_tree&depth=6"
    shot = ARTIFACTS_DIR / f"graph-{run_token}.png"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.goto(graph_url, wait_until="networkidle", timeout=60000)
        page.screenshot(path=str(shot), full_page=True)
        browser.close()
    expect(report, shot.exists() and shot.stat().st_size > 10_000, "frontend graph screenshot captured", str(shot))
    report["screenshot"] = str(shot)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2efractal%Y%m%d%H%M%S"))
    parser.add_argument("--admin-email", default=os.environ.get("ADMIN_EMAIL") or "admin@aibrain.local")
    parser.add_argument("--admin-password", default=os.environ.get("ADMIN_PASSWORD") or "")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    report = {"run_token": args.run_token, "api_base": API_BASE, "persona_slug": PERSONA_SLUG, "checks": []}
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{args.run_token}.json"
    try:
        print(f"\n== E2E CRIAR marketing fractal flexible graph ({args.run_token}) ==")
        login(report, args.admin_email, args.admin_password)
        plan = marketing_plan(args.run_token)
        session_id = write_session(args.run_token, plan)
        report["session_id"] = session_id
        save_result = http_json("POST", "/kb-intake/save", body={"session_id": session_id, "content": ""}, timeout=300)
        expect(report, save_result.get("ok") is True and save_result.get("success") is True, "kb-intake/save returns success without false 500", save_result)
        expect(report, save_result.get("status") in {"saved", "saved_with_warnings"}, "save status is saved or saved_with_warnings", save_result.get("status"))
        persona_id = persona_id_for(PERSONA_SLUG)
        items, nodes, _ = validate_db_after_save(report, session_id, args.run_token, persona_id)
        validate_graph_data(report, args.run_token)
        approve_faqs_and_validate_rag(report, items, nodes, persona_id)
        if not args.skip_browser:
            capture_browser(report, args.run_token, headless=not args.headed)
        report["ok"] = True
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nPASS e2e-criar-marketing-fractal-flexible-graph. Report: {report_path}")
        return 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFAIL e2e-criar-marketing-fractal-flexible-graph: {exc}")
        print(f"Report: {report_path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
