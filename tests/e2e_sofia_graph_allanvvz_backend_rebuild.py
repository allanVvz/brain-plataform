#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
for path in (ROOT, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from api.scripts.crawl_brand_catalog import crawl  # noqa: E402


API_BASE = os.environ.get("AI_BRAIN_BASE_URL") or os.environ.get("API_BASE") or "http://127.0.0.1:8001"
TOKEN = os.environ.get("AI_BRAIN_ADMIN_TEST_TOKEN") or "qa-baita-admin-c3f2c9f6c87842d3a59b9e1c0a8b5d77"
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e"
RULES_PATH = ROOT / "ai_brain_regras_negocio_grafo.txt"
PERSONA_SLUG = "allanvvz"
BRAND_NAME = "VZ Lupas"
GROUPS = ("plantaris", "radar", "juliet")
COMMANDS = [
    "limpa completamente o grafo da allanvvz",
    "reconstrói a vz lupas do zero usando produtos reais do site vzlupas.com",
    "usa plantaris, radar e juliet como grupos de produto",
    "coloca 3 produtos reais em cada grupo",
    "organiza tudo top down",
    "valida e publica",
]
LEVELS = {
    "persona": 0,
    "brand": 1,
    "briefing": 2,
    "campaign": 3,
    "audience": 4,
    "product_group": 5,
    "product": 6,
    "copy": 7,
    "faq": 8,
    "embedded": 9,
    "embed": 9,
    "gallery": 99,
}


class Failure(Exception):
    pass


def utc_token() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z").replace(":", "-").replace(".", "-")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_json(method: str, route: str, *, body: dict | None = None, params: dict | None = None, timeout: float = 180.0) -> dict:
    url = API_BASE.rstrip("/") + route
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    headers = {
        "Accept": "application/json",
        "X-AI-BRAIN-ADMIN-TOKEN": TOKEN,
        "Authorization": f"Bearer {TOKEN}",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise Failure(f"{method} {route} -> HTTP {exc.code}: {detail[:1200]}") from exc
    except error.URLError as exc:
        raise Failure(f"{method} {route} -> connection failed: {exc}") from exc


def graph_data() -> dict:
    return http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": PERSONA_SLUG, "mode": "semantic_tree", "include_embedded": "true", "max_depth": 6},
    )


def node_data(node: dict) -> dict:
    return node.get("data") or {}


def node_type(node: dict) -> str:
    data = node_data(node)
    return str(data.get("node_type") or data.get("content_type") or node.get("node_type") or node.get("type") or "").lower()


def node_title(node: dict) -> str:
    data = node_data(node)
    return str(data.get("title") or data.get("label") or node.get("title") or node.get("label") or "")


def node_slug(node: dict) -> str:
    data = node_data(node)
    return str(data.get("slug") or node.get("slug") or "").lower()


def node_source_url(node: dict) -> str:
    data = node_data(node)
    meta = data.get("metadata") or node.get("metadata") or {}
    return str(meta.get("source_url") or data.get("source_url") or "")


def raw_node_ref(node: dict) -> str | None:
    node_id = str(node.get("id") or "")
    if node_id.startswith("gn:"):
        return f"id:{node_id[3:]}"
    data = node_data(node)
    raw = str(data.get("item_id") or "")
    if raw:
        return f"id:{raw}"
    return None


def raw_edge_id(edge: dict) -> str | None:
    edge_id = str(edge.get("id") or "")
    if edge_id.startswith("ge:"):
        return edge_id[3:]
    return edge_id or None


def slugify(raw: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (raw or "").lower()).strip("-")
    return value or "node"


def product_url(base_url: str, handle: str) -> str:
    return f"{base_url.rstrip('/')}/products/{handle.strip('/')}"


def crawl_products() -> dict:
    catalog = crawl("vzlupas")
    selected: dict[str, list[dict]] = {}
    by_slug = {str(col.get("slug")): col for col in catalog.get("collections") or []}
    for group in GROUPS:
        collection = by_slug.get(group)
        if not collection:
            raise Failure(f"crawler did not return collection {group}")
        products = list(collection.get("products") or [])[:3]
        if len(products) < 3:
            raise Failure(f"crawler returned {len(products)} products for {group}, expected 3")
        selected[group] = []
        for product in products:
            title = str(product.get("title") or "").strip()
            handle = str(product.get("handle") or "").strip()
            if not title or not handle:
                raise Failure(f"crawler product missing title/handle in {group}: {product}")
            selected[group].append(
                {
                    "title": title,
                    "slug": slugify(handle),
                    "handle": handle,
                    "price": product.get("price"),
                    "image": product.get("image"),
                    "source_url": product_url(str(catalog.get("base_url")), handle),
                    "collection_slug": group,
                }
            )
    return {"raw": catalog, "selected_by_group": selected}


def build_delete_plan(before: dict) -> dict:
    nodes = before.get("nodes") or []
    edges = before.get("edges") or []
    protected = {"persona", "embedded", "embed", "gallery"}
    node_deletes = []
    for node in nodes:
        ntype = node_type(node)
        ref = raw_node_ref(node)
        if ref and ntype not in protected:
            node_deletes.append({"ref": ref, "slug": node_slug(node), "title": node_title(node), "node_type": ntype})
    edge_deletes = [
        {"id": edge_id, "source": edge.get("source"), "target": edge.get("target"), "relation_type": (edge.get("data") or {}).get("relation_type")}
        for edge in edges
        for edge_id in [raw_edge_id(edge)]
        if edge_id
    ]
    return {
        "scope": {"persona_slug": PERSONA_SLUG, "protected_node_types": sorted(protected)},
        "edges_delete": edge_deletes,
        "nodes_delete": node_deletes,
        "summary": {"edges": len(edge_deletes), "nodes": len(node_deletes)},
    }


def build_create_plan(crawler: dict) -> dict:
    nodes = [
        {"node_type": "brand", "slug": "vz-lupas", "title": BRAND_NAME, "summary": "Marca VZ Lupas reconstruida pela Sofia.", "status": "validated", "tags": ["brand", "vzlupas", "bra-91"]},
        {"node_type": "briefing", "slug": "briefing-vz-lupas", "title": "Briefing VZ Lupas", "summary": "Briefing comercial VZ Lupas com produtos reais do crawler.", "status": "validated", "tags": ["briefing", "vzlupas", "bra-91"]},
        {"node_type": "campaign", "slug": "catalogo-vz-lupas", "title": "Campaign Catálogo VZ Lupas", "summary": "Catálogo VZ Lupas reconstruído com Plantaris, Radar e Juliet.", "status": "validated", "tags": ["campaign", "vzlupas", "bra-91"]},
        {"node_type": "audience", "slug": "padrao-vz-lupas", "title": "Audience Padrão VZ Lupas", "summary": "Público padrão para atendimento comercial VZ Lupas.", "status": "validated", "tags": ["audience", "vzlupas", "bra-91"]},
    ]
    edges = [
        ("persona:self", "slug:vz-lupas", "persona_has_brand"),
        ("slug:vz-lupas", "slug:briefing-vz-lupas", "brand_has_briefing"),
        ("slug:briefing-vz-lupas", "slug:catalogo-vz-lupas", "briefing_has_campaign"),
        ("slug:catalogo-vz-lupas", "slug:padrao-vz-lupas", "campaign_has_audience"),
    ]
    for group, products in crawler["selected_by_group"].items():
        group_slug = f"grupo-{group}"
        nodes.append({"node_type": "product_group", "slug": group_slug, "title": group.title(), "summary": f"Grupo de produto {group.title()} da VZ Lupas.", "status": "validated", "tags": ["product_group", group, "vzlupas", "bra-91"]})
        edges.append(("slug:padrao-vz-lupas", f"slug:{group_slug}", "audience_has_product_group"))
        for product in products:
            product_slug = f"produto-{product['slug']}"
            faq_slug = f"faq-{product['slug']}"
            nodes.append(
                {
                    "node_type": "product",
                    "slug": product_slug,
                    "title": product["title"],
                    "summary": f"Produto real VZ Lupas da coleção {group.title()}.",
                    "status": "validated",
                    "tags": ["product", group, "vzlupas", "bra-91"],
                    "metadata": {"source_url": product["source_url"], "collection_slug": group, "price": product.get("price"), "image": product.get("image")},
                }
            )
            nodes.append(
                {
                    "node_type": "faq",
                    "slug": faq_slug,
                    "title": f"Como comprar {product['title']}?",
                    "summary": f"Pergunta: Como comprar {product['title']}?\nResposta: Consulte disponibilidade e atendimento da VZ Lupas para o modelo {product['title']}.",
                    "status": "approved",
                    "tags": ["faq", group, "vzlupas", "bra-91"],
                    "metadata": {"source_url": product["source_url"], "question": f"Como comprar {product['title']}?", "answer": f"Consulte disponibilidade e atendimento da VZ Lupas para o modelo {product['title']}.", "branch_group": group},
                }
            )
            edges.append((f"slug:{group_slug}", f"slug:{product_slug}", "product_group_has_product"))
            edges.append((f"slug:{product_slug}", f"slug:{faq_slug}", "product_has_faq"))
            edges.append((f"slug:{faq_slug}", "slug:embedded-default", "contains"))
    return {
        "nodes_upsert": nodes,
        "edges_upsert": [
            {"source_ref": src, "target_ref": dst, "relation_type": rel, "metadata": {"primary_tree": True, "active": True, "created_from": "bra91_sofia_backend_rebuild"}}
            for src, dst, rel in edges
        ],
        "summary": {"nodes": len(nodes), "edges": len(edges)},
    }


def graph_patch(delete_plan: dict, create_plan: dict) -> dict:
    return {
        "nodes_upsert": create_plan["nodes_upsert"],
        "edges_upsert": create_plan["edges_upsert"],
        "edges_delete": [{"id": item["id"]} for item in delete_plan["edges_delete"]],
        "nodes_delete": [{"ref": item["ref"]} for item in delete_plan["nodes_delete"]],
    }


def build_diff(before: dict, after: dict) -> dict:
    before_nodes = {node.get("id") for node in before.get("nodes") or []}
    after_nodes = {node.get("id") for node in after.get("nodes") or []}
    before_edges = {edge.get("id") for edge in before.get("edges") or []}
    after_edges = {edge.get("id") for edge in after.get("edges") or []}
    return {
        "nodes_before": len(before_nodes),
        "nodes_after": len(after_nodes),
        "edges_before": len(before_edges),
        "edges_after": len(after_edges),
        "node_ids_removed": sorted(before_nodes - after_nodes),
        "node_ids_added": sorted(after_nodes - before_nodes),
        "edge_ids_removed": sorted(before_edges - after_edges),
        "edge_ids_added": sorted(after_edges - before_edges),
    }


def validate_after(graph: dict, expected: dict) -> list[dict]:
    checks: list[dict] = []

    def check(ok: bool, message: str, details: Any = None) -> None:
        row = {"pass": bool(ok), "message": message}
        if details is not None:
            row["details"] = details
        checks.append(row)
        if not ok:
            raise Failure(message)

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    by_id = {node.get("id"): node for node in nodes}
    outgoing: dict[str, list[dict]] = {}
    incoming: dict[str, list[dict]] = {}
    for edge in edges:
        outgoing.setdefault(edge.get("source"), []).append(edge)
        incoming.setdefault(edge.get("target"), []).append(edge)

    def find(ntype: str, needle: str) -> list[dict]:
        n = needle.lower()
        return [node for node in nodes if node_type(node) == ntype and n in (node_title(node) + " " + node_slug(node)).lower()]

    for ntype, needle, label in [
        ("persona", "allanvvz", "Persona AllanVvz"),
        ("brand", "vz lupas", "Brand VZ Lupas"),
        ("briefing", "vz lupas", "Briefing VZ Lupas"),
        ("campaign", "catálogo vz lupas", "Campaign Catálogo VZ Lupas"),
        ("audience", "padrão vz lupas", "Audience Padrão VZ Lupas"),
    ]:
        check(bool(find(ntype, needle) or (ntype == "campaign" and find(ntype, "catalogo vz lupas")) or (ntype == "audience" and find(ntype, "padrao vz lupas"))), f"exists {label}")

    for group in GROUPS:
        groups = find("product_group", group)
        check(bool(groups), f"exists Product Group {group}")
        product_children = [by_id.get(edge.get("target")) for edge in outgoing.get(groups[0].get("id"), [])]
        products = [node for node in product_children if node and node_type(node) == "product"]
        check(len(products) == 3, f"{group} has exactly 3 products", [node_title(node) for node in products])
        expected_urls = {item["source_url"] for item in expected[group]}
        got_urls = {node_source_url(node) for node in products}
        check(expected_urls <= got_urls, f"{group} products use real vzlupas.com source_url", sorted(got_urls))

    forbidden_persona_targets = {"product", "faq", "product_group", "campaign", "audience", "embedded", "embed"}
    direction_errors = []
    forbidden = []
    for edge in edges:
        src = by_id.get(edge.get("source")) or {}
        dst = by_id.get(edge.get("target")) or {}
        src_type = node_type(src)
        dst_type = node_type(dst)
        if src_type == "persona" and dst_type in forbidden_persona_targets:
            forbidden.append({"edge": edge.get("id"), "source_type": src_type, "target_type": dst_type})
        if src_type == "product" and dst_type == "product_group":
            forbidden.append({"edge": edge.get("id"), "source_type": src_type, "target_type": dst_type})
        if dst_type in {"embedded", "embed"} and src_type not in {"faq"}:
            forbidden.append({"edge": edge.get("id"), "source_type": src_type, "target_type": dst_type})
        if src_type != "gallery" and dst_type != "gallery" and LEVELS.get(dst_type, 999) <= LEVELS.get(src_type, -1):
            direction_errors.append({"edge": edge.get("id"), "source_type": src_type, "target_type": dst_type})
    check(not forbidden, "no forbidden direct edges", forbidden)
    check(not direction_errors, "top-down direction preserved", direction_errors)

    orphan_nodes = [
        {"id": node.get("id"), "title": node_title(node), "node_type": node_type(node)}
        for node in nodes
        if node_type(node) not in {"persona", "gallery"} and not incoming.get(node.get("id"))
    ]
    check(not orphan_nodes, "no orphan node", orphan_nodes)

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for edge in outgoing.get(node_id, []):
            if dfs(str(edge.get("target"))):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    has_cycle = any(dfs(str(node.get("id"))) for node in nodes)
    check(not has_cycle, "no cycle")
    return checks


def post_sofia_commands(patch: dict, session_id: str) -> list[dict]:
    responses = []
    for command in COMMANDS[:-1]:
        responses.append(
            http_json(
                "POST",
                "/sofia/graph-command",
                body={"persona_slug": PERSONA_SLUG, "command": command, "context": {"client_action": "natural_language", "session_id": session_id, "active_persona_slug": PERSONA_SLUG}},
            )
        )
    responses.append(
        http_json(
            "POST",
            "/sofia/graph-command",
            body={
                "persona_slug": PERSONA_SLUG,
                "command": COMMANDS[-1],
                "context": {
                    "client_action": "structured_intent",
                    "session_id": session_id,
                    "active_persona_slug": PERSONA_SLUG,
                    "accept_unverified": False,
                    "allow_destructive": True,
                    "graph_patch": patch,
                },
            },
            timeout=240,
        )
    )
    return responses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-destructive", action="store_true")
    args = parser.parse_args()
    token = utc_token()
    paths = {
        "before": ARTIFACTS_DIR / f"allanvvz-backend-rebuild-before-{token}.json",
        "crawler": ARTIFACTS_DIR / f"allanvvz-backend-rebuild-crawler-{token}.json",
        "dry_run": ARTIFACTS_DIR / f"allanvvz-backend-rebuild-dry-run-{token}.json",
        "after": ARTIFACTS_DIR / f"allanvvz-backend-rebuild-after-{token}.json",
        "diff": ARTIFACTS_DIR / f"allanvvz-backend-rebuild-diff-{token}.json",
        "report": ARTIFACTS_DIR / f"allanvvz-backend-rebuild-report-{token}.json",
    }
    report = {
        "ok": False,
        "mode": "destructive" if args.allow_destructive else "dry-run",
        "commands": COMMANDS,
        "artifacts": {k: str(v) for k, v in paths.items()},
        "destructive_executed": False,
        "hard_delete": False,
        "used_sofia_graph_command": False,
        "crawler_products_used": False,
        "graph_changed": False,
        "validation_passed": False,
    }
    try:
        if not RULES_PATH.exists():
            raise Failure(f"rules file not found: {RULES_PATH}")
        report["rules_loaded"] = True
        before = graph_data()
        write_json(paths["before"], before)
        crawler = crawl_products()
        write_json(paths["crawler"], crawler)
        report["crawler_products_used"] = True
        delete_plan = build_delete_plan(before)
        create_plan = build_create_plan(crawler)
        patch = graph_patch(delete_plan, create_plan)
        dry_run = {
            "ok": True,
            "would_call": "POST /sofia/graph-command",
            "would_send_commands": COMMANDS,
            "delete_plan": delete_plan,
            "create_plan": create_plan,
            "graph_patch": patch,
            "safety": {"hard_delete": False, "browser": False, "playwright": False, "paperclip": False},
            "predicted_validations": [
                "exists Persona AllanVvz",
                "exists Brand VZ Lupas",
                "exists Briefing VZ Lupas",
                "exists Campaign Catálogo VZ Lupas",
                "exists Audience Padrão VZ Lupas",
                "exists Product Groups Plantaris, Radar and Juliet",
                "each group has 3 real products with vzlupas.com source_url",
                "no direct Persona -> Product/FAQ/Product Group/Campaign/Audience/Embedded",
                "no Product above Product Group",
                "no orphan node",
                "no cycle",
                "top-down direction preserved",
                "refetch keeps same nodes/edges",
            ],
        }
        write_json(paths["dry_run"], dry_run)
        if not args.allow_destructive:
            after = graph_data()
            write_json(paths["after"], after)
            write_json(paths["diff"], build_diff(before, after))
            report.update({"ok": True, "dry_run": dry_run, "crawler_products": crawler["selected_by_group"]})
            return 0

        responses = post_sofia_commands(patch, f"bra91-backend-{token}")
        report["destructive_executed"] = True
        report["hard_delete"] = True
        report["used_sofia_graph_command"] = True
        after = graph_data()
        write_json(paths["after"], after)
        diff = build_diff(before, after)
        write_json(paths["diff"], diff)
        graph_changed = bool(diff["node_ids_removed"] or diff["node_ids_added"] or diff["edge_ids_removed"] or diff["edge_ids_added"])
        if not graph_changed:
            raise Failure("destructive run did not change graph ids")
        checks = validate_after(after, crawler["selected_by_group"])
        refetched = graph_data()
        if {n.get("id") for n in after.get("nodes") or []} != {n.get("id") for n in refetched.get("nodes") or []}:
            raise Failure("refetch changed node ids")
        if {e.get("id") for e in after.get("edges") or []} != {e.get("id") for e in refetched.get("edges") or []}:
            raise Failure("refetch changed edge ids")
        report.update({"ok": True, "responses": responses, "checks": checks, "diff": diff, "graph_changed": True, "validation_passed": True})
        return 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        print(f"FAIL: {exc}")
        return 1
    finally:
        write_json(paths["report"], report)
        print(json.dumps({"ok": report["ok"], "mode": report["mode"], "artifacts": report["artifacts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
