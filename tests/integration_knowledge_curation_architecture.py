#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration checks for migration 009 knowledge curation architecture.

The test is intentionally usable before and after applying the migration:

1. Always validates the migration file for the structural mistakes that already
   bit us while designing it.
2. Audits the current Supabase data and computes the expected canonical
   artifact groups.
3. If migration 009 is applied, validates the new tables/views and lineage.
4. Optional --apply applies the SQL migration only when a direct Postgres URL
   and either psql or psycopg/psycopg2 are available.

Usage:
  python tests/integration_knowledge_curation_architecture.py
  python tests/integration_knowledge_curation_architecture.py --require-applied
  python tests/integration_knowledge_curation_architecture.py --apply --require-applied
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "supabase" / "migrations" / "009_knowledge_curation_architecture.sql"
MIGRATION_010 = ROOT / "supabase" / "migrations" / "010_knowledge_validation_rules.sql"
ARTIFACTS_DIR = ROOT / "test-artifacts"
REPORT_PATH = ARTIFACTS_DIR / "knowledge_curation_architecture_test.json"

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


def canonical_hash(persona_id: str | None, content_type: str | None, title: str | None) -> str:
    seed = "|".join([persona_id or "global", content_type or "other", slugify(title)])
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def expect(report: dict, cond: bool, msg: str, details: Any = None) -> None:
    entry = {"ok": bool(cond), "msg": msg}
    if details is not None:
        entry["details"] = details
    report.setdefault("checks", []).append(entry)
    print(("  ok " if cond else "  FAIL ") + msg)
    if not cond:
        raise CheckFailure(msg)


def warn(report: dict, msg: str, details: Any = None) -> None:
    entry = {"msg": msg}
    if details is not None:
        entry["details"] = details
    report.setdefault("warnings", []).append(entry)
    print("  WARN " + msg)


def static_sql_checks(report: dict) -> None:
    print("\n-- Static SQL checks --")
    sql = MIGRATION.read_text(encoding="utf-8")
    expect(report, "CREATE TABLE IF NOT EXISTS public.knowledge_artifacts" in sql,
           "migration defines knowledge_artifacts")
    expect(report, "CREATE TABLE IF NOT EXISTS public.knowledge_curation_proposals" in sql,
           "migration defines knowledge_curation_proposals")
    expect(report, "CREATE TABLE IF NOT EXISTS public.agent_prompt_profiles" in sql,
           "migration defines agent_prompt_profiles")
    expect(report, "CREATE OR REPLACE VIEW public.v_knowledge_lineage" in sql,
           "migration defines v_knowledge_lineage")
    expect(report, "CREATE OR REPLACE VIEW public.v_knowledge_curation_backlog" in sql,
           "migration defines v_knowledge_curation_backlog")

    duplicated_cte = re.search(
        r"WITH\s+kb_norm\s+AS\s*\([\s\S]*?\)\s*WITH\s+kb_norm\s+AS",
        sql,
        flags=re.IGNORECASE,
    )
    expect(report, duplicated_cte is None, "migration has no consecutive duplicate kb_norm CTE")
    expression_conflict = "ON CONFLICT ((COALESCE(persona_id::text, '')), canonical_hash)"
    expect(report, expression_conflict not in sql,
           "migration avoids expression-index conflict inference for canonical artifact hash")
    expect(report, "ON CONFLICT (source_table, source_id)" not in sql,
           "migration avoids partial-index conflict inference for artifact versions")
    expect(report, sql.count("ON CONFLICT DO NOTHING") >= 4,
           "migration uses conflictless inserts plus explicit backfill updates")
    expect(report, "WITH ki_current AS" in sql and "WITH kb_current AS" in sql,
           "migration backfills existing artifact fields after conflictless inserts")
    expect(report, "max(version_no) AS max_version_no" in sql,
           "migration offsets KB version numbers after existing artifact versions")
    expect(report, "a.id AS artifact_id" in sql,
           "backlog/lineage views expose artifact_id alias")


def static_sql_checks_010(report: dict) -> None:
    print("\n-- Static SQL checks migration 010 --")
    expect(report, MIGRATION_010.exists(), "migration 010 file exists")
    sql = MIGRATION_010.read_text(encoding="utf-8")
    expect(report, "CREATE TABLE IF NOT EXISTS public.knowledge_validation_rules" in sql,
           "migration 010 defines knowledge_validation_rules")
    expect(report, "'product.price.required'" in sql,
           "migration 010 seeds product price required rule")
    expect(report, "CREATE OR REPLACE VIEW public.v_knowledge_validation_failures" in sql,
           "migration 010 defines validation failures view")
    expect(report, "CREATE OR REPLACE VIEW public.v_knowledge_products_missing_price" in sql,
           "migration 010 defines products missing price view")
    expect(report, "IS DISTINCT FROM 'object'" in sql,
           "migration 010 treats missing jsonb objects as violations")
    direct_jsonb_numeric_cast = [
        line.strip()
        for line in sql.splitlines()
        if "jsonb_extract_path(" in line
        and "::numeric" in line
        and "jsonb_extract_path_text(" not in line
    ]
    expect(report, not direct_jsonb_numeric_cast,
           "migration 010 avoids direct jsonb-to-numeric casts")
    expect(report, "VARIADIC string_to_array(field_path, '.')," not in sql,
           "migration 010 avoids invalid VARIADIC path extension syntax")
    expect(report, "#> string_to_array" in sql and "#>> string_to_array" in sql,
           "migration 010 uses jsonb path operators for dynamic field paths")


def get_supabase_client():
    from services import supabase_client
    return supabase_client.get_client()


def table_rows(client, table: str, select: str = "*", limit: int = 5000) -> list[dict]:
    return client.table(table).select(select).limit(limit).execute().data or []


def table_count(client, table: str) -> int:
    res = client.table(table).select("id", count="exact").limit(1).execute()
    return int(res.count or 0)


def table_exists(client, table: str) -> bool:
    try:
        client.table(table).select("*").limit(1).execute()
        return True
    except Exception:
        return False


def audit_current_data(report: dict, client) -> dict:
    print("\n-- Current data audit --")
    items = table_rows(
        client,
        "knowledge_items",
        "id,persona_id,status,content_type,title,file_path,metadata,created_at,updated_at",
    )
    entries = table_rows(
        client,
        "kb_entries",
        "id,persona_id,kb_id,tipo,categoria,titulo,status,source,tags,updated_at",
    )
    nodes = table_rows(
        client,
        "knowledge_nodes",
        "id,persona_id,source_table,source_id,node_type,slug,title,status,tags,metadata",
    )

    item_groups: dict[tuple[str | None, str, str], list[str]] = defaultdict(list)
    for row in items:
        item_groups[(row.get("persona_id"), row.get("content_type") or "other", slugify(row.get("title")))].append(row["id"])

    kb_groups: dict[tuple[str | None, str, str], list[str]] = defaultdict(list)
    for row in entries:
        tipo = (row.get("tipo") or row.get("categoria") or "other").lower()
        normalized = {
            "produto": "product",
            "campanha": "campaign",
            "tom": "tone",
            "regra": "rule",
            "maker": "maker_material",
            "geral": "other",
        }.get(tipo, tipo)
        kb_groups[(row.get("persona_id"), normalized, slugify(row.get("titulo")))].append(row["id"])

    node_sources = {
        (row.get("source_table"), str(row.get("source_id")))
        for row in nodes
        if row.get("source_table") and row.get("source_id")
    }

    audit = {
        "counts": {
            "knowledge_items": len(items),
            "kb_entries": len(entries),
            "knowledge_nodes": len(nodes),
        },
        "knowledge_items_by_status": dict(Counter(row.get("status") for row in items)),
        "knowledge_items_by_type": dict(Counter(row.get("content_type") for row in items)),
        "kb_entries_by_tipo": dict(Counter(row.get("tipo") for row in entries)),
        "knowledge_nodes_by_type": dict(Counter(row.get("node_type") for row in nodes)),
        "expected_item_artifact_groups": len(item_groups),
        "expected_kb_artifact_groups": len(kb_groups),
        "duplicate_item_groups": [
            {"persona_id": key[0], "content_type": key[1], "title_slug": key[2], "count": len(ids), "ids": ids[:10]}
            for key, ids in item_groups.items()
            if len(ids) > 1
        ],
        "knowledge_items_without_graph_node": len([
            row for row in items if ("knowledge_items", str(row.get("id"))) not in node_sources
        ]),
        "kb_entries_without_graph_node": len([
            row for row in entries if ("kb_entries", str(row.get("id"))) not in node_sources
        ]),
    }
    report["current_audit"] = audit

    expect(report, len(items) > 0, "database has knowledge_items", audit["counts"])
    expect(report, audit["expected_item_artifact_groups"] <= len(items),
           "canonical grouping collapses item duplicates",
           {"groups": audit["expected_item_artifact_groups"], "items": len(items)})
    if audit["duplicate_item_groups"]:
        warn(report, "duplicate knowledge item groups detected", audit["duplicate_item_groups"][:5])
    if audit["knowledge_items_without_graph_node"] > 0:
        warn(report, "knowledge_items missing graph nodes", audit["knowledge_items_without_graph_node"])
    if audit["kb_entries_without_graph_node"] > 0:
        warn(report, "kb_entries missing graph nodes", audit["kb_entries_without_graph_node"])
    return audit


def postgres_url() -> str | None:
    for key in ("DATABASE_URL", "SUPABASE_DB_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL", "POSTGRES_URL_NON_POOLING"):
        if os.environ.get(key):
            return os.environ[key]
    return None


def apply_migration(report: dict) -> None:
    print("\n-- Apply migration --")
    url = postgres_url()
    if not url:
        raise CheckFailure(
            "Cannot apply migration: no direct Postgres URL found. Set DATABASE_URL or SUPABASE_DB_URL."
        )

    sql = MIGRATION.read_text(encoding="utf-8")
    psql = shutil.which("psql")
    if psql:
        subprocess.run([psql, url, "-v", "ON_ERROR_STOP=1", "-f", str(MIGRATION)], check=True)
        report["apply"] = {"method": "psql", "ok": True}
        print("  ok migration applied with psql")
        return

    if importlib.util.find_spec("psycopg"):
        import psycopg  # type: ignore
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        report["apply"] = {"method": "psycopg", "ok": True}
        print("  ok migration applied with psycopg")
        return

    if importlib.util.find_spec("psycopg2"):
        import psycopg2  # type: ignore
        conn = psycopg2.connect(url)
        try:
            cur = conn.cursor()
            cur.execute(sql)
            conn.commit()
        finally:
            conn.close()
        report["apply"] = {"method": "psycopg2", "ok": True}
        print("  ok migration applied with psycopg2")
        return

    raise CheckFailure("Cannot apply migration: psql/psycopg/psycopg2 not available.")


def validate_applied_schema(report: dict, client, require_applied: bool) -> bool:
    print("\n-- Applied schema checks --")
    required_tables = [
        "knowledge_node_type_registry",
        "knowledge_relation_type_registry",
        "knowledge_artifacts",
        "knowledge_artifact_versions",
        "agent_prompt_profiles",
        "knowledge_curation_runs",
        "knowledge_curation_proposals",
    ]
    exists = {table: table_exists(client, table) for table in required_tables}
    report["schema_exists"] = exists
    missing = [table for table, ok in exists.items() if not ok]
    if missing:
        msg = "migration 009 is not applied yet"
        print("  missing " + ", ".join(missing))
        if require_applied:
            expect(report, False, msg, {"missing": missing})
        warn(report, msg, {"missing": missing})
        return False

    for table in required_tables:
        expect(report, exists[table], f"{table} exists")

    node_types = table_rows(client, "knowledge_node_type_registry", "node_type,label,default_level,default_importance", 200)
    relation_types = table_rows(client, "knowledge_relation_type_registry", "relation_type,label,default_weight", 200)
    artifacts = table_rows(client, "knowledge_artifacts", "id,persona_id,canonical_hash,title,content_type,curation_status", 10000)
    versions = table_rows(client, "knowledge_artifact_versions", "id,artifact_id,source_table,source_id,version_no", 10000)
    prompt_profiles = table_rows(client, "agent_prompt_profiles", "agent_role,name,version,tools,skills,active", 100)
    lineage = table_rows(client, "v_knowledge_lineage", "artifact_id,persona_slug,title,content_type,graph_nodes,versions", 10000)
    try:
        backlog = table_rows(client, "v_knowledge_curation_backlog", "artifact_id,persona_slug,title,backlog_reason", 10000)
        report["backlog_view_current"] = True
    except Exception as exc:
        report["backlog_view_current"] = False
        msg = "v_knowledge_curation_backlog is stale; re-run migration 009 to expose artifact_id"
        if require_applied:
            expect(report, False, msg, repr(exc))
        warn(report, msg, repr(exc))
        backlog = table_rows(client, "v_knowledge_curation_backlog", "id,persona_slug,title,backlog_reason", 10000)

    applied = {
        "node_type_count": len(node_types),
        "relation_type_count": len(relation_types),
        "artifact_count": len(artifacts),
        "version_count": len(versions),
        "prompt_profiles": prompt_profiles,
        "lineage_count": len(lineage),
        "backlog_count": len(backlog),
    }
    report["applied_audit"] = applied

    expect(report, len(node_types) >= 15, "node type registry seeded", applied["node_type_count"])
    expect(report, len(relation_types) >= 13, "relation type registry seeded", applied["relation_type_count"])
    expect(report, any(p.get("name") == "kb-classifier-curator" for p in prompt_profiles),
           "KB Classifier/Curator prompt profile seeded", prompt_profiles)
    expect(report, len(artifacts) > 0, "knowledge_artifacts backfilled", applied["artifact_count"])
    expect(report, len(versions) > 0, "knowledge_artifact_versions backfilled", applied["version_count"])
    expect(report, len(lineage) == len(artifacts), "lineage view covers all artifacts",
           {"lineage": len(lineage), "artifacts": len(artifacts)})

    by_hash: dict[tuple[str | None, str], list[str]] = defaultdict(list)
    for row in artifacts:
        by_hash[(row.get("persona_id"), row.get("canonical_hash"))].append(row["id"])
    duplicated_artifacts = [
        {"persona_id": key[0], "canonical_hash": key[1], "ids": ids}
        for key, ids in by_hash.items()
        if len(ids) > 1
    ]
    expect(report, not duplicated_artifacts, "no duplicate artifacts by persona/hash", duplicated_artifacts[:10])
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply migration SQL before validating.")
    parser.add_argument("--require-applied", action="store_true", help="Fail if migration 009 tables are missing.")
    args = parser.parse_args()

    load_env()
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    report: dict = {
        "migration": str(MIGRATION),
        "apply_requested": args.apply,
        "require_applied": args.require_applied,
        "checks": [],
        "warnings": [],
    }

    try:
        static_sql_checks(report)
        static_sql_checks_010(report)
        client = get_supabase_client()
        audit_current_data(report, client)
        if args.apply:
            apply_migration(report)
            client = get_supabase_client()
        applied = validate_applied_schema(report, client, args.require_applied)
        report["applied"] = applied
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
    print(f"\nALL CHECKS COMPLETED. applied={report['applied']}")
    print(f"WROTE {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
