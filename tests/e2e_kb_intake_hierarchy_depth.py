#!/usr/bin/env python3
"""E2E: hierarchical knowledge tree — measure & assert deepest path.

A solid brand structure is hierarchical: persona → brand → campaign →
product → (copy|faq). Today bootstrap_from_item only links each new node
to the persona, so the tree looks "horizontalized" — every leaf has
depth=1. This test makes the regression visible by:

  1. Logging in as an authenticated user.
  2. Starting a Sofia session and injecting a deterministic 6-entry plan
     where every non-top entry carries `metadata.parent_slug` chaining to
     the next level up: brand → campaign → audience/product → copy/faq.
  3. Saving via /kb-intake/save.
  4. Pulling /knowledge/graph-data and computing the deepest primary-edge
     path from the persona root.
  5. Logging the depth and the path itself, then asserting >= --min-depth
     (default 4 hops, i.e. 5 nodes). The expected chain is:
        persona → brand → campaign → product → faq

Until the hierarchy enforcement lands (parent_slug + links → primary
parent→child edges), this test will FAIL with depth 1 — that is the
documented breakage. After the fix it should hit depth 4+ deterministically.

The deepest path is printed near the bottom of stdout and stored in the
JSON report under `report["depth"] = {"levels": N, "path": [...]}` for
easy grepping in CI logs.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-kb-intake-hierarchy-depth"
SESSION_DIR = ROOT / "api" / ".runtime" / "kb-intake-sessions"
PERSONA_SLUG = "tock-fatal"
CATALOG_URL = "https://tockfatal.com/pages/catalogo-modal"

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")

# Mirrors api.routes.graph:_compute_primary_depths logic. Edges are walked
# only if relation_type is structural OR metadata.primary_tree=true.
PRIMARY_RELATIONS = frozenset({
    "belongs_to_persona", "contains", "part_of_campaign", "about_product",
    "briefed_by", "answers_question", "supports_copy", "uses_asset",
    "manual", "parent_of", "belongs_to", "part_of",
})

_COOKIE_JAR = http.cookiejar.CookieJar()
_HTTP_OPENER = request.build_opener(request.HTTPCookieProcessor(_COOKIE_JAR))


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
        with _HTTP_OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
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


def login(report: dict, identifier: str, password: str) -> dict:
    if not identifier or not password:
        raise TestFailure(
            "auth credentials missing — pass --admin-email/--admin-password "
            "or set ADMIN_EMAIL / ADMIN_PASSWORD env vars"
        )
    session = http_json(
        "POST",
        "/auth/login",
        body={"identifier": identifier, "password": password, "remember": False},
        timeout=20,
    )
    user = (session or {}).get("user") or {}
    expect(report, bool(user.get("id")), f"auth login ok ({identifier})", {"role": user.get("role")})
    expect(report, any(c.name == "ai_brain_session" for c in _COOKIE_JAR), "session cookie stored in jar")
    return session


def hierarchical_plan(run_token: str) -> dict:
    """6-entry plan with explicit parent_slug chain.

    Topology:
        brand (top)
        └── campaign
            ├── audience          (sibling leaf)
            └── product
                ├── copy          (sibling leaf)
                └── faq           (deepest leaf — 4 hops from persona)
    """
    brand_slug = f"tock-fatal-brand-{run_token}"
    campaign_slug = f"tock-fatal-modal-2026-{run_token}"
    audience_slug = f"revendedoras-{run_token}"
    product_slug = f"kit-modal-1-{run_token}"
    copy_slug = f"copy-kit-modal-1-{run_token}"
    faq_slug = f"faq-preco-kit-modal-1-{run_token}"
    entries = [
        {
            "content_type": "brand",
            "slug": brand_slug,
            "title": f"Tock Fatal Brand [{run_token}]",
            "status": "confirmado",
            "content": "Marca Tock Fatal: moda urbana acessivel para o mercado brasileiro.",
            "tags": [run_token, "brand"],
            "metadata": {},
        },
        {
            "content_type": "campaign",
            "slug": campaign_slug,
            "title": f"Modal Inverno 2026 [{run_token}]",
            "status": "confirmado",
            "content": "Catalogo Modal Inverno 2026 com kits para revenda e varejo.",
            "tags": [run_token, "campaign"],
            "metadata": {"parent_slug": brand_slug, "parent_type": "brand"},
        },
        {
            "content_type": "audience",
            "slug": audience_slug,
            "title": f"Revendedoras [{run_token}]",
            "status": "confirmado",
            "content": "Lojistas que compram kits de 5+ pecas. Procuram preco competitivo e variedade.",
            "tags": [run_token, "audience"],
            "metadata": {"parent_slug": campaign_slug, "parent_type": "campaign"},
        },
        {
            "content_type": "product",
            "slug": product_slug,
            "title": f"Kit Modal 1 - 9 cores [{run_token}]",
            "status": "confirmado",
            "content": "Blusa canelada de modal, 9 cores. Preco unitario R$ 59,90.",
            "tags": [run_token, "product"],
            "metadata": {"parent_slug": campaign_slug, "parent_type": "campaign"},
        },
        {
            "content_type": "copy",
            "slug": copy_slug,
            "title": f"Copy revenda Kit Modal 1 [{run_token}]",
            "status": "confirmado",
            "content": "Kit Modal 1: 9 cores prontas pra girar. Garanta sua margem com kit de 5 ou 10 pecas.",
            "tags": [run_token, "copy"],
            "metadata": {"parent_slug": product_slug, "parent_type": "product"},
        },
        {
            "content_type": "faq",
            "slug": faq_slug,
            "title": f"FAQ preco Kit Modal 1 [{run_token}]",
            "status": "confirmado",
            "content": (
                "Pergunta: Qual o preco do Kit Modal 1?\n"
                "Resposta: Unidade R$ 59,90, kit de 5 R$ 249,00, kit de 10 R$ 459,00."
            ),
            "tags": [run_token, "faq"],
            "metadata": {"parent_slug": product_slug, "parent_type": "product"},
        },
    ]
    return {
        "source": CATALOG_URL,
        "persona_slug": PERSONA_SLUG,
        "validation_policy": "human_validation_required",
        "entries": entries,
        "links": [
            {"source_slug": brand_slug, "target_slug": campaign_slug, "relation_type": "contains"},
            {"source_slug": campaign_slug, "target_slug": audience_slug, "relation_type": "contains"},
            {"source_slug": campaign_slug, "target_slug": product_slug, "relation_type": "contains"},
            {"source_slug": product_slug, "target_slug": copy_slug, "relation_type": "supports_copy"},
            {"source_slug": product_slug, "target_slug": faq_slug, "relation_type": "answers_question"},
        ],
        "missing_questions": [],
        "_expected_deepest_chain": [
            "persona", brand_slug, campaign_slug, product_slug, faq_slug,
        ],
    }


def write_synthetic_session(plan: dict, *, model: str) -> str:
    """Build a complete session JSON on disk WITHOUT calling /kb-intake/start.

    Bypasses /start to avoid the in-memory session cache contaminating the
    save handler. With this approach, save() experiences a cache miss and
    loads the freshly-written session — including the knowledge_plan we
    pre-cooked here.
    """
    import uuid
    session_id = str(uuid.uuid4())
    payload = json.dumps({k: v for k, v in plan.items() if not k.startswith("_")}, ensure_ascii=False, indent=2)
    assistant_msg = (
        "Plano hierarquizado pronto. Clique em **Salvar** para persistir.\n\n"
        "<classification>{\"complete\": true, \"persona_slug\": \"tock-fatal\", "
        "\"content_type\": \"brand\", \"title\": \"Tock Fatal Brand\"}</classification>\n\n"
        f"<knowledge_plan>\n{payload}\n</knowledge_plan>"
    )
    session = {
        "id": session_id,
        "model": model,
        "agent_key": "sofia",
        "agent_name": "Sofia",
        "agent_role": "agente de inteligencia marketing comercial",
        "stage": "ready_to_save",
        "classification": {
            "persona_slug": "tock-fatal",
            "content_type": "brand",
            "asset_type": None,
            "asset_function": None,
            "title": "Tock Fatal Brand",
            "file_ext": None,
            "file_bytes": None,
        },
        "messages": [
            {"role": "user", "content": "Synthetic E2E hierarchy session."},
            {"role": "assistant", "content": assistant_msg},
        ],
        "context": "persona_slug: tock-fatal\nrun_token: e2e-hierarchy\n",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": True},
    }
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSION_DIR / f"{session_id}.json"
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return session_id


def call_save(report: dict, session_id: str) -> dict:
    result = http_json("POST", "/kb-intake/save", body={"session_id": session_id, "content": ""}, timeout=300)
    expect(report, result.get("ok") is True, "kb-intake/save returned ok=true",
           {"keys": sorted(result.keys()), "error": result.get("error"), "violations": result.get("violations")})
    item_ids = result.get("knowledge_item_ids") or [
        ev.get("knowledge_item_id") for ev in (result.get("persistence_evidence") or [])
    ]
    item_ids = [i for i in item_ids if i]
    expect(report, len(item_ids) >= 6, "save persisted all 6 knowledge_items", {"count": len(item_ids)})
    return result


def fetch_graph(report: dict) -> dict:
    return http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": PERSONA_SLUG, "mode": "semantic_tree", "max_depth": 6, "include_technical": "true"},
    )


def compute_deepest_path(graph: dict, run_token: str) -> tuple[int, list[dict]]:
    """BFS from each persona node along PRIMARY edges; return deepest reach.

    Only edges whose relation_type is in PRIMARY_RELATIONS *or* whose
    metadata.primary_tree=true are walked. This mirrors how the production
    layout computes the structural tree.
    """
    raw_nodes = graph.get("nodes") or []
    raw_edges = graph.get("edges") or []
    nodes_by_id: dict[str, dict] = {}
    for n in raw_nodes:
        nid = n.get("id")
        if not nid:
            continue
        data = n.get("data") or {}
        nodes_by_id[nid] = {
            "id": nid,
            "node_type": data.get("node_type") or data.get("nodeClass") or n.get("type"),
            "slug": data.get("slug") or n.get("slug") or "",
            "title": data.get("title") or n.get("title") or "",
            "raw": n,
        }
    children: dict[str, list[tuple[str, str]]] = {}
    for e in raw_edges:
        src = e.get("source") or e.get("source_node_id")
        tgt = e.get("target") or e.get("target_node_id")
        if not src or not tgt or src not in nodes_by_id or tgt not in nodes_by_id:
            continue
        rel = (e.get("relation_type") or e.get("label") or "").lower()
        meta = e.get("metadata") or e.get("data") or {}
        is_primary = bool(meta.get("primary_tree")) if isinstance(meta, dict) else False
        if rel not in PRIMARY_RELATIONS and not is_primary:
            continue
        children.setdefault(src, []).append((tgt, rel))

    persona_ids = [nid for nid, n in nodes_by_id.items() if n["node_type"] == "persona"]
    if not persona_ids:
        return 0, []

    best_depth = 0
    best_path: list[dict] = []
    for pid in persona_ids:
        # BFS keeping the longest path per visited node — token-bearing only
        # to keep noise out (other personas/global subtrees may exist).
        queue: deque[tuple[str, list[dict]]] = deque()
        queue.append((pid, [{"node_id": pid, "slug": "self", "title": "Persona", "node_type": "persona", "via": None}]))
        visited: dict[str, int] = {pid: 0}
        while queue:
            current, path = queue.popleft()
            depth = len(path) - 1
            # Token guard: skip nodes that don't carry our run_token (besides persona).
            node = nodes_by_id.get(current) or {}
            blob = json.dumps(node["raw"], ensure_ascii=False) if depth > 0 else ""
            if depth > 0 and run_token not in blob:
                continue
            if depth > best_depth:
                best_depth = depth
                best_path = path
            for nxt, rel in children.get(current, []):
                if nxt in visited and visited[nxt] >= depth + 1:
                    continue
                visited[nxt] = depth + 1
                nxt_node = nodes_by_id.get(nxt) or {}
                queue.append((nxt, path + [{
                    "node_id": nxt,
                    "slug": nxt_node.get("slug"),
                    "title": nxt_node.get("title"),
                    "node_type": nxt_node.get("node_type"),
                    "via": rel,
                }]))
    return best_depth, best_path


def render_path(path: list[dict]) -> str:
    parts: list[str] = []
    for step in path:
        ntype = step.get("node_type") or "?"
        slug = step.get("slug") or step.get("node_id") or "?"
        if step.get("via"):
            parts.append(f"--[{step['via']}]--> {ntype}:{slug}")
        else:
            parts.append(f"{ntype}:{slug}")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2ehier%Y%m%d%H%M%S"))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--min-depth", type=int, default=int(os.environ.get("MIN_DEPTH", "4")),
                        help="Minimum acceptable hops from persona to deepest leaf (default 4 = 5 nodes)")
    parser.add_argument("--admin-email",
                        default=os.environ.get("ADMIN_EMAIL") or os.environ.get("AI_BRAIN_SEED_ADMIN_EMAIL"))
    parser.add_argument("--admin-password",
                        default=os.environ.get("ADMIN_PASSWORD") or os.environ.get("AI_BRAIN_SEED_ADMIN_PASSWORD"))
    args = parser.parse_args()

    run_token = slugify(args.run_token)
    report: dict[str, Any] = {
        "ok": False,
        "run_token": run_token,
        "api_base": API_BASE,
        "min_depth": args.min_depth,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{run_token}.json"

    try:
        print(f"\n== E2E kb-intake hierarchy depth ({run_token}) ==")
        health = http_json("GET", "/health")
        expect(report, health.get("status") == "ok", "backend health ok")
        login(report, args.admin_email, args.admin_password)

        plan = hierarchical_plan(run_token)
        sid = write_synthetic_session(plan, model=args.model)
        expect(report, bool(sid), "synthetic hierarchical session written to disk",
               {"entries": len(plan["entries"]), "links": len(plan["links"]), "session_id": sid[:8]})

        save_result = call_save(report, sid)
        report["save_result"] = {
            "ok": save_result.get("ok"),
            "entries_written": save_result.get("entries_written"),
            "knowledge_item_ids": save_result.get("knowledge_item_ids") or [],
            "knowledge_node_ids": save_result.get("knowledge_node_ids") or [],
        }

        graph = fetch_graph(report)
        depth, path = compute_deepest_path(graph, run_token)
        rendered = render_path(path)
        report["depth"] = {
            "levels": depth,
            "node_count": len(path),
            "expected_chain_hint": plan.get("_expected_deepest_chain"),
            "path": [
                {
                    "step": idx,
                    "node_type": p.get("node_type"),
                    "slug": p.get("slug"),
                    "title": p.get("title"),
                    "via_relation": p.get("via"),
                }
                for idx, p in enumerate(path)
            ],
            "rendered": rendered,
        }

        # ── HEADLINE LOG: prominent so it's easy to grep in CI output ─────
        print()
        print("=" * 78)
        print(f"DEEPEST PATH: {depth} hops ({len(path)} levels)")
        print(f"  {rendered if rendered else '(no token-bearing path found from persona)'}")
        print("=" * 78)
        print()

        expect(report, depth >= args.min_depth,
               f"deepest path has at least {args.min_depth} hops (got {depth})",
               {"path": rendered, "by_type_in_path": [p.get("node_type") for p in path]})

        report["ok"] = True
        report.pop("error", None)
        print(f"\nPASS e2e-kb-intake-hierarchy-depth (depth={depth}). Report: {report_path}")
        return 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        print(f"\nFAIL {exc}")
        if "depth" in report:
            print(f"  observed depth: {report['depth'].get('levels')} — {report['depth'].get('rendered')}")
        return 1
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
