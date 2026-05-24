#!/usr/bin/env python3
"""E2E: clone the VZ Lupas knowledge graph into the tock-fatal persona.

Used to validate that "send knowledge from persona A to persona B" works
end-to-end through the same canonical taxonomy that the cardapio reads:
- spine nodes (brand, briefing, campaign, audience)
- product_group / product nodes
- assets (database rows reusing the same Storage path; metadata flagged
  validation_status='approved' so list_gallery_assets surfaces them)
- canonical edges (product_group_has_product, uses_asset, product_image,
  brand_has_briefing, briefing_has_campaign, campaign_has_audience,
  gallery_asset to the destination gallery)

The operator allan (admin in QA, persona_access including tock-fatal)
sees the cloned graph on /persona when switching to tock-fatal in the
top bar, and `GET /api/menu/tock-fatal` returns 3 groups x 9 products.

Idempotent: every cloned row carries `metadata.cloned_from_persona = 'vz-lupas'`
plus `metadata.cloned_from_node_id` / `cloned_from_asset_id` / `cloned_from_edge_id`
so re-runs skip rows that already exist.

Auth: uses SUPABASE_SERVICE_KEY for the cloning DDL/DML (direct PostgREST
is not enough — we need raw SQL via PostgREST RPC `exec`, or apply via
psql, or via the Supabase MCP when running from Claude). For automation
the easiest is `psql "$SUPABASE_DB_URL"` with the connection string from
Supabase project settings. The script below prints the SQL when run with
`--dry-run` so the operator can pipe it into psql.

Validation talks to the AI-BRAIN API with the QA admin token.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "test-artifacts" / "e2e-clone-vz-to-tock-fatal"

SRC_SLUG = "vz-lupas"
DST_SLUG = "tock-fatal"
CLONE_PREFIX = "tf-clone-"


class TestFailure(Exception):
    pass


# ── Persona UUIDs (QA Supabase qhnepdcqtkjjslqqiyvp) ─────────────────────
SRC_PID = "46872921-6390-4d49-ae13-6eeb75bf4d21"
DST_PID = "409e5958-3a43-446a-9478-475b2f77ee18"


CLONE_SQL = f"""
-- Phase 1: clone spine + product nodes (skip asset nodes — handled below
-- so source_id can be wired to the new assets row).
WITH params AS (
  SELECT
    '{SRC_PID}'::uuid AS src_pid,
    '{DST_PID}'::uuid AS dst_pid,
    '{CLONE_PREFIX}'::text AS prefix
)
INSERT INTO knowledge_nodes (persona_id, node_type, slug, title, summary, tags, metadata, status, importance, level, confidence)
SELECT
  params.dst_pid, n.node_type, params.prefix || n.slug, n.title, n.summary, n.tags,
  COALESCE(n.metadata, '{{}}'::jsonb) || jsonb_build_object(
    'cloned_from_node_id', n.id::text, 'cloned_from_persona', '{SRC_SLUG}',
    'cloned_at', now()::text
  ),
  n.status, n.importance, n.level, n.confidence
FROM knowledge_nodes n, params
WHERE n.persona_id = params.src_pid
  AND n.node_type IN ('brand','briefing','campaign','audience','product_group','product')
  AND n.status != 'archived'
  AND n.slug NOT LIKE 'tf-clone-%'
  AND NOT EXISTS (
    SELECT 1 FROM knowledge_nodes existing
    WHERE existing.persona_id = params.dst_pid
      AND existing.slug = params.prefix || n.slug
  );

-- Phase 2: clone assets table rows, flagged approved so the menu surfaces them
WITH params AS (
  SELECT '{SRC_PID}'::uuid AS src_pid, '{DST_PID}'::uuid AS dst_pid
)
INSERT INTO assets (persona_id, type, name, url, metadata, source, asset_type, asset_function, tags, description, approval_status, storage_bucket, storage_path, mime_type, file_size, original_filename, status, upload_context, embedding_status)
SELECT
  params.dst_pid, a.type, a.name, a.url,
  COALESCE(a.metadata, '{{}}'::jsonb) || jsonb_build_object(
    'cloned_from_asset_id', a.id::text, 'cloned_from_persona', '{SRC_SLUG}',
    'cloned_at', now()::text, 'validation_status', 'approved',
    'approved_by', 'e2e-clone-vz-to-tf'
  ),
  a.source, a.asset_type, a.asset_function, a.tags, a.description,
  a.approval_status, a.storage_bucket, a.storage_path, a.mime_type,
  a.file_size, a.original_filename, a.status, a.upload_context, a.embedding_status
FROM assets a, params
WHERE a.persona_id = params.src_pid
  AND a.status = 'ready'
  AND (a.metadata->>'validation_status' = 'approved')
  AND NOT EXISTS (
    SELECT 1 FROM assets existing
    WHERE existing.persona_id = params.dst_pid
      AND existing.metadata->>'cloned_from_asset_id' = a.id::text
  );

-- Phase 3: clone asset knowledge_nodes, wiring source_id to the new assets row
WITH params AS (
  SELECT '{SRC_PID}'::uuid AS src_pid, '{DST_PID}'::uuid AS dst_pid, '{CLONE_PREFIX}'::text AS prefix
),
new_assets AS (
  SELECT a.id AS new_asset_id, (a.metadata->>'cloned_from_asset_id')::uuid AS src_asset_id
  FROM assets a, params
  WHERE a.persona_id = params.dst_pid AND a.metadata->>'cloned_from_persona' = '{SRC_SLUG}'
)
INSERT INTO knowledge_nodes (persona_id, source_table, source_id, node_type, slug, title, summary, tags, metadata, status, importance, level, confidence)
SELECT
  params.dst_pid, n.source_table, na.new_asset_id, n.node_type, params.prefix || n.slug,
  n.title, n.summary, n.tags,
  COALESCE(n.metadata, '{{}}'::jsonb) || jsonb_build_object(
    'cloned_from_node_id', n.id::text, 'cloned_from_persona', '{SRC_SLUG}',
    'cloned_at', now()::text, 'asset_id', na.new_asset_id::text
  ),
  n.status, n.importance, n.level, n.confidence
FROM knowledge_nodes n
JOIN new_assets na ON na.src_asset_id = n.source_id
CROSS JOIN params
WHERE n.persona_id = params.src_pid
  AND n.node_type = 'asset' AND n.status != 'archived'
  AND NOT EXISTS (
    SELECT 1 FROM knowledge_nodes existing
    WHERE existing.persona_id = params.dst_pid
      AND existing.slug = params.prefix || n.slug
  );

-- Phase 4: assets.knowledge_node_id reciprocal pointer
WITH params AS (SELECT '{DST_PID}'::uuid AS dst_pid)
UPDATE assets a
SET knowledge_node_id = n.id, updated_at = now()
FROM knowledge_nodes n, params
WHERE a.persona_id = params.dst_pid
  AND a.metadata->>'cloned_from_persona' = '{SRC_SLUG}'
  AND n.persona_id = params.dst_pid AND n.node_type = 'asset' AND n.source_id = a.id;

-- Phase 5: clone every edge between two cloned nodes, translating IDs
WITH params AS (SELECT '{SRC_PID}'::uuid AS src_pid, '{DST_PID}'::uuid AS dst_pid),
node_map AS (
  SELECT (dst_n.metadata->>'cloned_from_node_id')::uuid AS old_id, dst_n.id AS new_id
  FROM knowledge_nodes dst_n, params
  WHERE dst_n.persona_id = params.dst_pid
    AND dst_n.metadata->>'cloned_from_persona' = '{SRC_SLUG}'
)
INSERT INTO knowledge_edges (source_node_id, target_node_id, relation_type, weight, metadata, confidence)
SELECT
  m_src.new_id, m_tgt.new_id, e.relation_type, e.weight,
  COALESCE(e.metadata, '{{}}'::jsonb) || jsonb_build_object(
    'cloned_from_edge_id', e.id::text, 'cloned_from_persona', '{SRC_SLUG}',
    'cloned_at', now()::text
  ),
  e.confidence
FROM knowledge_edges e
JOIN node_map m_src ON m_src.old_id = e.source_node_id
JOIN node_map m_tgt ON m_tgt.old_id = e.target_node_id
WHERE COALESCE(e.metadata->>'active','true') != 'false'
  AND NOT EXISTS (
    SELECT 1 FROM knowledge_edges existing
    WHERE existing.source_node_id = m_src.new_id
      AND existing.target_node_id = m_tgt.new_id
      AND existing.relation_type = e.relation_type
  );

-- Phase 6: wire each cloned asset node to tock-fatal's gallery so
-- list_gallery_assets returns it
WITH params AS (SELECT '{DST_PID}'::uuid AS dst_pid),
gal AS (
  SELECT id FROM knowledge_nodes, params
  WHERE persona_id = params.dst_pid AND node_type='gallery' AND status='active' LIMIT 1
),
cloned_assets AS (
  SELECT n.id AS asset_node_id FROM knowledge_nodes n, params
  WHERE n.persona_id = params.dst_pid AND n.node_type='asset'
    AND n.metadata->>'cloned_from_persona'='{SRC_SLUG}'
)
INSERT INTO knowledge_edges (source_node_id, target_node_id, relation_type, weight, metadata, confidence)
SELECT cloned_assets.asset_node_id, gal.id, 'gallery_asset', 0.95,
       jsonb_build_object('cloned_from_persona','{SRC_SLUG}','active', true), 0.9
FROM cloned_assets, gal
WHERE NOT EXISTS (
  SELECT 1 FROM knowledge_edges existing
  WHERE existing.source_node_id = cloned_assets.asset_node_id
    AND existing.target_node_id = gal.id
    AND existing.relation_type = 'gallery_asset'
);

-- Phase 7: catalog_url on tock-fatal so the dashboard surfaces a link
UPDATE personas SET catalog_url='https://baita-cardapio-qa.vercel.app/cardapio/tock-fatal',
                    updated_at=now()
 WHERE slug='tock-fatal' AND catalog_url IS NULL;
"""


def http_json(method: str, base: str, path: str, *, params: dict | None = None,
              body: dict | None = None, admin_token: str | None = None,
              timeout: float = 90.0, retries: int = 2) -> Any:
    url = base.rstrip("/") + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    data = None
    headers = {"Accept": "application/json"}
    if admin_token:
        headers["X-AI-BRAIN-ADMIN-TOKEN"] = admin_token
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
            detail = exc.read().decode("utf-8", "replace")[:1500]
            if exc.code in {502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1)); continue
            raise TestFailure(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1)); continue
            raise TestFailure(f"{method} {path} -> connection failed: {exc}") from exc
    raise TestFailure(f"{method} {path} failed after retries")


def apply_clone_via_psql(report: dict) -> None:
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        report["clone_skipped"] = (
            "SUPABASE_DB_URL not set; run psql manually or use Supabase MCP. "
            "Print SQL with --dry-run."
        )
        return
    import subprocess
    res = subprocess.run(["psql", db_url, "-v", "ON_ERROR_STOP=1", "-c", CLONE_SQL],
                         capture_output=True, text=True, timeout=120)
    report["clone_psql"] = {"rc": res.returncode, "stdout": res.stdout[:2000], "stderr": res.stderr[:2000]}
    if res.returncode != 0:
        raise TestFailure(f"psql clone failed: {res.stderr[:600]}")


def validate_menu(base: str, admin_token: str, report: dict) -> dict:
    payload = http_json("GET", base, f"/api/menu/{DST_SLUG}",
                        params={"nocache": 1}, admin_token=admin_token)
    persona = (payload or {}).get("persona") or {}
    collections = persona.get("collections") or []
    if not collections:
        raise TestFailure("menu has no collections")
    collection = collections[0]
    categories = [c for c in (collection.get("categories") or []) if c.get("visible") is not False]
    total_products = sum(len(c.get("products") or []) for c in categories)
    products_without_assets = [
        p.get("slug") for c in categories for p in (c.get("products") or [])
        if not (p.get("assets") or [])
    ]
    summary = {
        "groups": len(categories),
        "products": total_products,
        "campaign_assets": len(collection.get("assets") or []),
        "products_without_assets": products_without_assets,
        "collection_slug": collection.get("slug"),
        "persona_name": persona.get("name"),
    }
    report["menu_summary"] = summary
    (ARTIFACTS / "menu.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if summary["groups"] != 3:
        raise TestFailure(f"expected 3 groups, got {summary['groups']}")
    if summary["products"] != 9:
        raise TestFailure(f"expected 9 products, got {summary['products']}")
    if products_without_assets:
        raise TestFailure(f"products missing assets: {products_without_assets}")
    if summary["campaign_assets"] < 1:
        raise TestFailure("campaign hero asset missing")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "https://ai-brain-api-qa-837167469397.us-central1.run.app"))
    parser.add_argument("--admin-token", default=os.environ.get("AI_BRAIN_ADMIN_TEST_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true", help="Print the clone SQL and exit (apply via psql or Supabase MCP).")
    parser.add_argument("--skip-clone", action="store_true", help="Skip the clone phase and only validate the menu (assumes already cloned).")
    args = parser.parse_args()

    if args.dry_run:
        print(CLONE_SQL)
        return 0

    if not args.admin_token:
        print("ERROR: AI_BRAIN_ADMIN_TEST_TOKEN env or --admin-token required for validation.")
        return 2

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "api_base": args.api_base,
        "src_persona": SRC_SLUG,
        "dst_persona": DST_SLUG,
    }
    try:
        if not args.skip_clone:
            print(f"[1/3] cloning {SRC_SLUG} -> {DST_SLUG} via psql (SUPABASE_DB_URL)")
            apply_clone_via_psql(report)
        else:
            print("[1/3] SKIPPED clone (--skip-clone)")

        print(f"[2/3] validating /api/menu/{DST_SLUG} ...")
        summary = validate_menu(args.api_base, args.admin_token, report)
        print(f"      OK -> {summary['groups']} groups, {summary['products']} products, {summary['campaign_assets']} campaign asset(s)")

        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "ok"
        print("[3/3] artifacts in", ARTIFACTS)
    except TestFailure as exc:
        report["status"] = "failed"; report["error"] = str(exc)
        print(f"FAILED: {exc}", file=sys.stderr)
    except Exception as exc:
        report["status"] = "crashed"; report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"CRASHED: {report['error']}", file=sys.stderr)
    finally:
        (ARTIFACTS / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
