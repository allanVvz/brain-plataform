#!/usr/bin/env python3
"""Parametric E2E-ish graph test for a product sales scenario.

The default fixture is Moosi/Winter 2026, but the code intentionally reads all
business terms from JSON. Dry-run never touches the database. Apply mode is
idempotent and can run before migration 009; artifact/version checks are then
reported as blocked instead of being faked.

Usage:
  python tests/integration_moosi_winter26_graph.py --scenario tests/fixtures/knowledge_moosi_winter26.json --dry-run
  python tests/integration_moosi_winter26_graph.py --scenario tests/fixtures/knowledge_moosi_winter26.json --apply --catalog-url https://example.test/catalog
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIO = ROOT / "tests" / "fixtures" / "knowledge_moosi_winter26.json"
ARTIFACTS_DIR = ROOT / "test-artifacts"
REPORT_PATH = ARTIFACTS_DIR / "moosi_winter26_graph_test.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CheckFailure(Exception):
    pass


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def slugify(value: str | None) -> str:
    text = (value or "").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def canonical_hash(persona_id: str | None, content_type: str, title: str) -> str:
    seed = "|".join([persona_id or "global", content_type or "other", slugify(title)])
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def content_hash(content: str) -> str:
    return hashlib.md5((content or "").encode("utf-8")).hexdigest()


def expect(report: dict, cond: bool, msg: str, details: Any = None, *, fatal: bool = True) -> None:
    entry = {"ok": bool(cond), "msg": msg}
    if details is not None:
        entry["details"] = details
    report.setdefault("checks", []).append(entry)
    print(("  ok " if cond else "  FAIL ") + msg)
    if not cond and fatal:
        raise CheckFailure(msg)


def warn(report: dict, msg: str, details: Any = None) -> None:
    entry = {"msg": msg}
    if details is not None:
        entry["details"] = details
    report.setdefault("warnings", []).append(entry)
    print("  WARN " + msg)


def load_scenario(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def flatten_json(obj: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {prefix: obj} if prefix else {}
    out: dict[str, Any] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(flatten_json(value, path))
        else:
            out[path] = value
    return out


def fill_template(template: str, values: dict[str, Any]) -> str:
    out = template or ""
    for key, value in flatten_json(values).items():
        out = out.replace("{" + key + "}", str(value))
    return out


def catalog_url_for(scenario: dict, args, *, require: bool, report: dict) -> str | None:
    product = scenario.get("product") or {}
    env_name = product.get("catalog_url_env")
    value = args.catalog_url or (os.environ.get(env_name) if env_name else None) or product.get("catalog_url_default")
    if not value and require:
        raise CheckFailure(
            f"Catalog URL is required for --apply. Pass --catalog-url or set {env_name or 'the configured env var'}."
        )
    if not value:
        warn(report, "catalog URL not configured; dry-run keeps this as a pending runtime value",
             {"env": env_name})
    return value


def edge_tuple(edge: Any) -> tuple[str, str, str]:
    if isinstance(edge, (list, tuple)) and len(edge) == 3:
        return str(edge[0]), str(edge[1]), str(edge[2])
    if isinstance(edge, dict):
        return str(edge.get("src_slug")), str(edge.get("relation_type")), str(edge.get("tgt_slug"))
    raise ValueError(f"Invalid edge spec: {edge!r}")


def scenario_nodes(scenario: dict, catalog_url: str | None) -> list[dict]:
    nodes: list[dict] = []

    def add(raw: dict, role: str, content: str | None = None) -> None:
        node = dict(raw)
        node["role"] = role
        node.setdefault("node_type", role)
        node.setdefault("tags", [])
        metadata = dict(node.get("metadata") or {})
        if node.get("aliases"):
            metadata["aliases"] = node.get("aliases")
        metadata["slug"] = node.get("slug")
        if catalog_url and role == "product":
            metadata["catalog_url"] = catalog_url
        node["metadata"] = metadata
        node["content"] = content or node.get("body") or node.get("title") or node.get("slug")
        nodes.append(node)

    if scenario.get("brand"):
        add(scenario["brand"], "brand")
    if scenario.get("campaign"):
        add(scenario["campaign"], "campaign")

    product = dict(scenario.get("product") or {})
    product_values = dict(product.get("metadata") or {})
    if catalog_url:
        product_values["catalog_url"] = catalog_url
    product_content = "\n".join([
        product.get("title") or "",
        json.dumps(product_values, ensure_ascii=False, sort_keys=True),
    ]).strip()
    add(product, "product", product_content)

    for raw in scenario.get("related") or []:
        add(raw, raw.get("node_type") or "related")
    for raw in scenario.get("copies") or scenario.get("copy") or []:
        add(raw, raw.get("node_type") or "copy", raw.get("body"))
    for raw in scenario.get("faqs") or scenario.get("faq") or []:
        values = dict(product_values)
        answer = fill_template(raw.get("answer_template") or "", values)
        content = "\n".join([
            f"Pergunta: {raw.get('question') or raw.get('title') or ''}",
            f"Resposta: {answer}",
        ]).strip()
        add(raw, raw.get("node_type") or "faq", content)

    return nodes


def validate_scenario(report: dict, scenario: dict, nodes: list[dict]) -> None:
    print("\n-- Scenario checks --")
    required_top = ["persona_slug", "product", "expected_edges", "search_queries"]
    for key in required_top:
        expect(report, key in scenario, f"scenario defines {key}")

    product = scenario.get("product") or {}
    metadata = product.get("metadata") or {}
    price = metadata.get("price") or {}
    if (scenario.get("validation_rules") or {}).get("product_must_have_price"):
        expect(report, isinstance(price, dict) and bool(price.get("display")), "product fixture has display price")
        expect(report, isinstance(price.get("amount"), (int, float)) and price["amount"] > 0,
               "product fixture has positive price amount")
        expect(report, bool(price.get("currency")), "product fixture has currency")

    slugs = {n.get("slug") for n in nodes if n.get("slug")}
    for edge in scenario.get("expected_edges") or []:
        src, relation, tgt = edge_tuple(edge)
        expect(report, src in slugs, f"edge source exists: {src}", {"relation_type": relation})
        expect(report, tgt == "self" or tgt in slugs, f"edge target exists: {tgt}", {"relation_type": relation})

    node_types = {n.get("node_type") for n in nodes}
    for expected in ["product", "campaign", "copy", "faq"]:
        expect(report, expected in node_types, f"scenario includes {expected} node")


def table_exists(client, table: str) -> bool:
    try:
        client.table(table).select("*").limit(1).execute()
        return True
    except Exception:
        return False


def query_one_by_slug(client, table: str, persona_id: str | None, node_type: str, slug: str) -> dict | None:
    q = client.table(table).select("*").eq("node_type", node_type).eq("slug", slug)
    q = q.eq("persona_id", persona_id) if persona_id else q.is_("persona_id", "null")
    rows = q.limit(1).execute().data or []
    return rows[0] if rows else None


def upsert_item_for_node(client, supabase_client, knowledge_graph, node: dict, persona_id: str, source_id: str | None) -> dict:
    rows = (
        client.table("knowledge_items")
        .select("*")
        .eq("persona_id", persona_id)
        .eq("content_type", node["node_type"])
        .eq("title", node["title"])
        .limit(1)
        .execute()
        .data
        or []
    )
    payload = {
        "persona_id": persona_id,
        "source_id": source_id,
        "status": "approved",
        "content_type": node["node_type"],
        "title": node["title"],
        "content": node.get("content") or node["title"],
        "metadata": {
            **(node.get("metadata") or {}),
            "slug": node.get("slug"),
            "aliases": node.get("aliases") or (node.get("metadata") or {}).get("aliases"),
        },
        "file_type": "text",
        "tags": node.get("tags") or [],
    }
    payload["metadata"] = {k: v for k, v in payload["metadata"].items() if v is not None}

    if rows:
        item = rows[0]
        supabase_client.update_knowledge_item(item["id"], payload)
        item = supabase_client.get_knowledge_item(item["id"]) or {**item, **payload}
    else:
        item = supabase_client.insert_knowledge_item(payload)

    knowledge_graph.bootstrap_from_item(
        item,
        frontmatter=payload["metadata"],
        body=payload["content"],
        persona_id=persona_id,
        source_table="knowledge_items",
    )
    return item


def upsert_graph_node(supabase_client, node: dict, persona_id: str) -> dict:
    row = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": node["node_type"],
        "slug": node["slug"],
        "title": node["title"],
        "summary": (node.get("content") or "")[:400] or None,
        "tags": node.get("tags") or [],
        "metadata": node.get("metadata") or {},
        "status": "active",
    })
    if not row:
        raise CheckFailure("knowledge_nodes is unavailable; apply migration 008 first")
    return row


def upsert_artifact_if_available(
    report: dict,
    client,
    node: dict,
    item: dict,
    persona_id: str,
) -> dict | None:
    if not table_exists(client, "knowledge_artifacts"):
        warn(report, "migration 009 not applied; artifact/version checks skipped")
        return None

    c_hash = canonical_hash(persona_id, node["node_type"], node["title"])
    c_key = ":".join([persona_id or "global", node["node_type"], slugify(node["title"])])
    body = item.get("content") or node.get("content") or ""
    metadata = node.get("metadata") or {}

    q = client.table("knowledge_artifacts").select("*").eq("canonical_hash", c_hash)
    q = q.eq("persona_id", persona_id) if persona_id else q.is_("persona_id", "null")
    existing = (q.limit(1).execute().data or [None])[0]
    payload = {
        "persona_id": persona_id,
        "canonical_key": c_key,
        "canonical_hash": c_hash,
        "title": node["title"],
        "content_type": node["node_type"],
        "summary": body[:500],
        "curation_status": "validated",
        "importance": metadata.get("importance", 0.85 if node["node_type"] == "product" else 0.50),
        "level": metadata.get("level", 40 if node["node_type"] == "product" else 50),
        "confidence": metadata.get("confidence", 0.95),
        "current_knowledge_item_id": item.get("id"),
        "content_hash": content_hash(body),
        "metadata": metadata,
    }
    if existing:
        client.table("knowledge_artifacts").update({
            "current_knowledge_item_id": item.get("id"),
            "content_hash": payload["content_hash"],
            "metadata": metadata,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", existing["id"]).execute()
        artifact = {**existing, **payload, "id": existing["id"]}
    else:
        artifact = (client.table("knowledge_artifacts").insert(payload).execute().data or [{}])[0]

    if artifact.get("id") and table_exists(client, "knowledge_artifact_versions"):
        version_rows = (
            client.table("knowledge_artifact_versions")
            .select("id")
            .eq("source_table", "knowledge_items")
            .eq("source_id", item.get("id"))
            .limit(1)
            .execute()
            .data
            or []
        )
        if not version_rows:
            max_rows = (
                client.table("knowledge_artifact_versions")
                .select("version_no")
                .eq("artifact_id", artifact["id"])
                .order("version_no", desc=True)
                .limit(1)
                .execute()
                .data
                or []
            )
            version_no = int((max_rows[0] or {}).get("version_no") or 0) + 1 if max_rows else 1
            client.table("knowledge_artifact_versions").insert({
                "artifact_id": artifact["id"],
                "version_no": version_no,
                "source_table": "knowledge_items",
                "source_id": item.get("id"),
                "title": node["title"],
                "content_type": node["node_type"],
                "content_hash": payload["content_hash"],
                "raw_content": body,
                "classification": metadata,
            }).execute()

        try:
            client.table("knowledge_items").update({
                "artifact_id": artifact["id"],
                "canonical_key": c_key,
                "canonical_hash": c_hash,
                "content_hash": payload["content_hash"],
                "curation_status": "validated",
                "importance": payload["importance"],
                "level": payload["level"],
                "confidence": payload["confidence"],
            }).eq("id", item.get("id")).execute()
        except Exception as exc:
            warn(report, "artifact columns could not be backfilled on knowledge_items", repr(exc))

    return artifact


def apply_scenario(report: dict, scenario: dict, nodes: list[dict], args) -> None:
    print("\n-- Apply scenario --")
    load_env()
    from services import knowledge_graph, supabase_client

    client = supabase_client.get_client()
    persona_slug = args.persona_slug or scenario.get("persona_slug")
    persona = supabase_client.get_persona(persona_slug)
    expect(report, bool(persona and persona.get("id")), f"persona exists: {persona_slug}")
    persona_id = persona["id"]
    report["persona"] = {"slug": persona_slug, "id": persona_id}

    expect(report, table_exists(client, "knowledge_nodes"), "knowledge_nodes table exists")
    expect(report, table_exists(client, "knowledge_edges"), "knowledge_edges table exists")

    source = supabase_client.get_or_create_manual_source()
    source_id = source.get("id") if source else None
    node_rows: dict[str, dict] = {}
    item_rows: dict[str, dict] = {}
    artifacts: dict[str, dict | None] = {}

    for node in nodes:
        item = upsert_item_for_node(client, supabase_client, knowledge_graph, node, persona_id, source_id)
        graph_node = upsert_graph_node(supabase_client, node, persona_id)
        node_rows[node["slug"]] = graph_node
        item_rows[node["slug"]] = item
        artifacts[node["slug"]] = upsert_artifact_if_available(report, client, node, item, persona_id)

    persona_node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "persona",
        "slug": "self",
        "title": "Persona",
        "metadata": {"role": "root"},
    })
    if persona_node:
        node_rows["self"] = persona_node

    for edge in scenario.get("expected_edges") or []:
        src, relation, tgt = edge_tuple(edge)
        src_node = node_rows.get(src) or query_one_by_slug(client, "knowledge_nodes", persona_id, "product", src)
        tgt_node = node_rows.get(tgt)
        if not tgt_node and tgt != "self":
            # Slugs are unique per node_type, so resolve from the scenario map first.
            spec = next((n for n in nodes if n.get("slug") == tgt), None)
            if spec:
                tgt_node = query_one_by_slug(client, "knowledge_nodes", persona_id, spec["node_type"], tgt)
        expect(report, bool(src_node), f"edge source resolved: {src}")
        expect(report, bool(tgt_node), f"edge target resolved: {tgt}")
        supabase_client.upsert_knowledge_edge(
            src_node["id"], tgt_node["id"], relation, persona_id=persona_id, metadata={"scenario": "integration_fixture"}
        )

    report["applied_nodes"] = {slug: row.get("id") for slug, row in node_rows.items()}
    report["applied_items"] = {slug: row.get("id") for slug, row in item_rows.items()}
    report["applied_artifacts"] = {
        slug: (row or {}).get("id") if isinstance(row, dict) else None
        for slug, row in artifacts.items()
    }

    validate_database_state(report, client, scenario, nodes, persona_id)
    validate_chat_context(report, knowledge_graph, scenario, persona_id)


def validate_database_state(report: dict, client, scenario: dict, nodes: list[dict], persona_id: str) -> None:
    print("\n-- Database graph checks --")
    by_slug = {n["slug"]: n for n in nodes}
    product = scenario["product"]
    product_row = query_one_by_slug(client, "knowledge_nodes", persona_id, "product", product["slug"])
    expect(report, bool(product_row), "product node exists")
    price = ((product_row or {}).get("metadata") or {}).get("price") or {}
    expect(report, price.get("display") == product["metadata"]["price"]["display"], "product node carries display price")
    expect(report, float(price.get("amount") or 0) == float(product["metadata"]["price"]["amount"]),
           "product node carries numeric price")

    campaign = scenario.get("campaign") or {}
    if campaign.get("slug"):
        expect(report, bool(query_one_by_slug(client, "knowledge_nodes", persona_id, "campaign", campaign["slug"])),
               "campaign node exists")

    for edge in scenario.get("expected_edges") or []:
        src, relation, tgt = edge_tuple(edge)
        src_spec = by_slug.get(src) or {"node_type": "persona" if src == "self" else "product"}
        tgt_spec = by_slug.get(tgt) or {"node_type": "persona" if tgt == "self" else "product"}
        src_row = query_one_by_slug(client, "knowledge_nodes", persona_id, src_spec["node_type"], src)
        tgt_row = query_one_by_slug(client, "knowledge_nodes", persona_id, tgt_spec["node_type"], tgt)
        if not src_row or not tgt_row:
            expect(report, False, f"expected edge endpoints exist: {src} - {relation} - {tgt}")
            continue
        rows = (
            client.table("knowledge_edges")
            .select("id,relation_type")
            .eq("source_node_id", src_row["id"])
            .eq("target_node_id", tgt_row["id"])
            .eq("relation_type", relation)
            .limit(1)
            .execute()
            .data
            or []
        )
        expect(report, bool(rows), f"expected edge exists: {src} --{relation}--> {tgt}")

    # Report legacy product nodes without price, but do not fail the scenario:
    # older data can predate migration 010. The migration/view is the hard gate.
    product_nodes = (
        client.table("knowledge_nodes")
        .select("id,slug,title,metadata,status")
        .eq("persona_id", persona_id)
        .eq("node_type", "product")
        .limit(500)
        .execute()
        .data
        or []
    )
    missing = [
        {"id": n.get("id"), "slug": n.get("slug"), "title": n.get("title")}
        for n in product_nodes
        if not (((n.get("metadata") or {}).get("price") or {}).get("display"))
    ]
    if missing:
        warn(report, "legacy product nodes without price detected; migration 010 should gate future validation", missing[:20])


def validate_chat_context(report: dict, knowledge_graph, scenario: dict, persona_id: str) -> None:
    print("\n-- Chat context graph checks --")
    product_slug = scenario["product"]["slug"]
    expected_related = {
        item["slug"] for item in scenario.get("related") or []
    }
    for question in scenario.get("search_queries") or []:
        ctx = knowledge_graph.get_chat_context(
            lead_ref=None,
            persona_id=persona_id,
            user_text=question,
            limit=20,
        )
        nodes = ctx.get("nodes") or []
        similar = ctx.get("similar") or []
        report.setdefault("chat_context", []).append({
            "question": question,
            "query_terms": ctx.get("query_terms"),
            "node_slugs": [n.get("slug") for n in nodes],
            "similar": [
                {
                    "slug": n.get("slug"),
                    "node_type": n.get("node_type"),
                    "graph_distance": n.get("graph_distance"),
                    "path_slugs": n.get("path_slugs"),
                    "path_relations": n.get("path_relations"),
                }
                for n in similar
            ],
        })
        product_hits = [n for n in nodes if n.get("slug") == product_slug and n.get("node_type") == "product"]
        expect(report, bool(product_hits), f"chat-context finds product for query: {question[:48]}")
        if product_hits:
            expect(report, product_hits[0].get("graph_distance") == 0,
                   "product focus has graph_distance=0")
            price = ((product_hits[0].get("metadata") or {}).get("price") or {})
            expect(report, bool(price.get("display")), "product focus exposes price metadata")

        related_hits = {n.get("slug"): n for n in [*similar, *nodes] if n.get("slug") in expected_related}
        for slug in sorted(expected_related):
            hit = related_hits.get(slug)
            expect(report, bool(hit), f"related node returned by graph traversal: {slug}")
            if hit:
                expect(report, hit.get("graph_distance") is not None and hit.get("graph_distance") >= 1,
                       f"related node has graph distance: {slug}",
                       {"graph_distance": hit.get("graph_distance")})
                expect(report, bool(hit.get("path_slugs") or hit.get("path")),
                       f"related node has traversal path: {slug}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--persona-slug", default=None)
    parser.add_argument("--catalog-url", default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    scenario_path = Path(args.scenario)
    if not scenario_path.is_absolute():
        scenario_path = ROOT / scenario_path
    report: dict = {
        "scenario": str(scenario_path),
        "mode": "apply" if args.apply else "dry-run",
        "checks": [],
        "warnings": [],
    }

    try:
        if args.apply:
            load_env()
        scenario = load_scenario(scenario_path)
        catalog_url = catalog_url_for(scenario, args, require=args.apply, report=report)
        nodes = scenario_nodes(scenario, catalog_url)
        report["planned_nodes"] = [
            {"node_type": n["node_type"], "slug": n["slug"], "title": n["title"]}
            for n in nodes
        ]
        report["planned_edges"] = [edge_tuple(e) for e in scenario.get("expected_edges") or []]
        validate_scenario(report, scenario, nodes)

        if args.apply:
            apply_scenario(report, scenario, nodes, args)
        else:
            print("\n-- Dry-run plan --")
            print(json.dumps({
                "nodes": report["planned_nodes"],
                "edges": report["planned_edges"],
                "catalog_url_configured": bool(catalog_url),
            }, ensure_ascii=False, indent=2))

    except CheckFailure as exc:
        report["ok"] = False
        report["error"] = str(exc)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFAIL: {exc}")
        print(f"WROTE {REPORT_PATH}")
        return 1
    except Exception as exc:
        report["ok"] = False
        report["error"] = repr(exc)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nERROR: {exc}")
        print(f"WROTE {REPORT_PATH}")
        return 1

    report["ok"] = True
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOK: {report['mode']}")
    print(f"WROTE {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
