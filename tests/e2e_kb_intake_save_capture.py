#!/usr/bin/env python3
"""E2E: Capture (Sofia) → /kb-intake/save → knowledge_items + tree.

Reproduces the operator flow that was failing today:

  1. Login as authenticated user (cookie session).
  2. Start a Sofia session for persona=tock-fatal.
  3. Drive Sofia to emit a small <knowledge_plan> (briefing + audience +
     product + copy + faq).
  4. POST /kb-intake/save and require ok=True (no 4xx/5xx, no contract
     violations, no "insert not confirmed").
  5. Verify each persisted item has a knowledge_node mirror in the graph.

Modes:
  --skip-llm    Bypass Sofia by injecting a deterministic <knowledge_plan>
                directly into the session JSON on disk, then save. This
                isolates the parser + persist + graph paths from LLM
                non-determinism (useful for CI and post-fix verification).

  --use-fence   Same as --skip-llm but writes the plan inside a ```json
                fenced block instead of <knowledge_plan> tags. Verifies the
                permissive parser fallback (case Sofia formatted wrong on
                2026-05-07 and the operator hit "content must be a non-empty
                string").

Examples:
    python tests/e2e_kb_intake_save_capture.py \\
        --admin-email admin@brain.local --admin-password ******** \\
        --skip-llm

    python tests/e2e_kb_intake_save_capture.py --use-fence
"""
from __future__ import annotations

import argparse
import http.cookiejar
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
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-kb-intake-save-capture"
SESSION_DIR = ROOT / "api" / ".runtime" / "kb-intake-sessions"
PERSONA_SLUG = "tock-fatal"
CATALOG_URL = "https://tockfatal.com/pages/catalogo-modal"

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_BASE = os.environ.get("DASHBOARD_BASE", "http://localhost:3000").rstrip("/")

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
    cookie_present = any(c.name == "ai_brain_session" for c in _COOKIE_JAR)
    expect(report, cookie_present, "session cookie stored in jar")
    return session


def deterministic_plan(run_token: str) -> dict:
    """Plan covering each top-level + child type, all with non-empty content.

    Mirrors the structure operators usually produce in Capture: one briefing
    parent and a few children (audience/product/copy/faq). Once hierarchy
    enforcement lands, this should populate parent_slug/links accordingly.
    """
    return {
        "source": CATALOG_URL,
        "persona_slug": PERSONA_SLUG,
        "validation_policy": "human_validation_required",
        "entries": [
            {
                "content_type": "briefing",
                "title": f"Briefing Tock Fatal Modal [{run_token}]",
                "slug": f"briefing-tock-fatal-modal-{run_token}",
                "status": "confirmado",
                "content": (
                    "Catalogo Modal e a base de conhecimento. O crawler entrega evidencia "
                    "bruta; precos, cores e kits exigem validacao humana antes de ir ao agente."
                ),
                "tags": [run_token, "briefing"],
                "metadata": {"source_url": CATALOG_URL},
            },
            {
                "content_type": "audience",
                "title": f"Revendedoras Tock Fatal [{run_token}]",
                "slug": f"audiencia-revendedoras-{run_token}",
                "status": "confirmado",
                "content": (
                    "Lojistas que compram kits de 5+ pecas para revenda. Procuram preco competitivo, "
                    "consistencia de tecido e variedade de cores."
                ),
                "tags": [run_token, "atacado"],
                "metadata": {"parent_slug": f"briefing-tock-fatal-modal-{run_token}"},
            },
            {
                "content_type": "product",
                "title": f"Kit Modal 1 - 9 cores [{run_token}]",
                "slug": f"kit-modal-1-9-cores-{run_token}",
                "status": "confirmado",
                "content": (
                    "Blusa canelada de modal, modelagem ajustada, 9 cores: vermelho, vinho, bege, nude, "
                    "off-white, verde claro, azul claro, azul marinho e preto. Preco unitario R$ 59,90."
                ),
                "tags": [run_token, "produto", "modal"],
                "metadata": {"parent_slug": f"audiencia-revendedoras-{run_token}", "preco_unit": 59.9},
            },
            {
                "content_type": "copy",
                "title": f"Copy revenda Kit Modal 1 [{run_token}]",
                "slug": f"copy-kit-modal-1-revenda-{run_token}",
                "status": "confirmado",
                "content": (
                    "Kit Modal 1: tecido macio, 9 cores que viram, margem segura para revenda. "
                    "Garanta seu pedido com kit de 5 ou 10 pecas e antecipe a colecao de inverno."
                ),
                "tags": [run_token, "copy", "revenda"],
                "metadata": {"parent_slug": f"kit-modal-1-9-cores-{run_token}"},
            },
            {
                "content_type": "faq",
                "title": f"FAQ preco Kit Modal 1 [{run_token}]",
                "slug": f"faq-preco-kit-modal-1-{run_token}",
                "status": "confirmado",
                "content": (
                    "Pergunta: Qual o preco do Kit Modal 1?\n"
                    "Resposta: A unidade sai por R$ 59,90. Kit com 5 pecas R$ 249,00 e kit com 10 pecas R$ 459,00."
                ),
                "tags": [run_token, "faq", "preco"],
                "metadata": {"parent_slug": f"kit-modal-1-9-cores-{run_token}"},
            },
        ],
        "links": [],
        "missing_questions": [],
    }


def write_synthetic_session(plan: dict, *, use_fence: bool, model: str) -> str:
    """Build a complete session JSON on disk WITHOUT going through /kb-intake/start.

    Why: /kb-intake/start warms the in-memory session cache on the API process.
    If we then write to disk and call /save, the API still serves the stale
    cached version (no <knowledge_plan> in messages) and falls back to a
    single-entry plan. By skipping /start entirely we force the save handler
    into a cache-miss path → reads our fresh file from disk → sees the plan.

    Returns the session_id (a fresh UUID).
    """
    import uuid
    session_id = str(uuid.uuid4())
    payload = json.dumps(plan, ensure_ascii=False, indent=2)
    if use_fence:
        block = f"```json\n{payload}\n```"
    else:
        block = f"<knowledge_plan>\n{payload}\n</knowledge_plan>"
    assistant_msg = (
        "Plano gerado para validacao do operador. "
        "Clique em **Salvar** para persistir.\n\n"
        "<classification>{\"complete\": true, \"persona_slug\": \"tock-fatal\", "
        "\"content_type\": \"briefing\", \"title\": \"Briefing Tock Fatal Modal\"}"
        "</classification>\n\n"
        f"{block}"
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
            "content_type": "briefing",
            "asset_type": None,
            "asset_function": None,
            "title": "Briefing Tock Fatal Modal",
            "file_ext": None,
            "file_bytes": None,
        },
        "messages": [
            {"role": "user", "content": "Synthetic E2E session — bypassing /kb-intake/start."},
            {"role": "assistant", "content": assistant_msg},
        ],
        "context": "persona_slug: tock-fatal\nrun_token: e2e-synthetic\n",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": True},
    }
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSION_DIR / f"{session_id}.json"
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return session_id


def drive_sofia_for_plan(report: dict, run_token: str, *, model: str) -> str:
    """Real LLM path. Starts a Sofia session and asks for a small plan."""
    started = http_json("POST", "/kb-intake/start", body={
        "model": model,
        "agent_key": "sofia",
        "initial_context": (
            f"# Plano confirmado pelo operador (run_token: {run_token})\n"
            f"persona_slug: {PERSONA_SLUG}\n"
            f"objetivo: gerar conhecimento Modal pequeno (briefing + audience + product + copy + faq)\n"
            f"fonte principal: {CATALOG_URL}\n\n"
            "## Blocos solicitados\n"
            "- briefing\n- audience\n- product\n- copy\n- faq\n"
        ),
    }, timeout=60)
    sid = started.get("session_id")
    expect(report, bool(sid), "Sofia session started", {"agent": started.get("agent")})

    response = http_json("POST", "/kb-intake/message", body={
        "session_id": sid,
        "message": (
            f"Sofia, gere um plano com 5 entries (1 briefing, 1 audience, 1 product, 1 copy, 1 faq) "
            f"para tock-fatal usando {CATALOG_URL}. Use run_token \"{run_token}\" nas tags. "
            f"Lembre: o JSON precisa estar dentro das tags <knowledge_plan>...</knowledge_plan>."
        ),
    }, timeout=180)
    msg = response.get("message") or ""
    expect(report, "<knowledge_plan>" in msg or "```json" in msg, "Sofia returned a knowledge_plan candidate")
    return sid


def call_save(report: dict, session_id: str) -> dict:
    """POST /kb-intake/save and assert success. Surfaces violations on failure."""
    try:
        result = http_json("POST", "/kb-intake/save", body={"session_id": session_id, "content": ""}, timeout=300)
    except TestFailure as exc:
        # Extract the error body so the report shows the contract violations
        # instead of just the HTTP code.
        report["save_error_raw"] = str(exc)
        raise
    expect(report, result.get("ok") is True, "kb-intake/save returned ok=true", {"keys": sorted(result.keys())})
    planner_rewrite_warnings = [
        warning for warning in (result.get("warnings") or [])
        if isinstance(warning, dict) and warning.get("warning_type") == "planner_parent_rewrite"
    ]
    expect(report, not planner_rewrite_warnings, "save did not need single_branch parent rewrite", planner_rewrite_warnings)
    item_ids = result.get("knowledge_item_ids") or [
        ev.get("knowledge_item_id") for ev in (result.get("persistence_evidence") or [])
    ]
    item_ids = [i for i in item_ids if i]
    expect(report, len(item_ids) >= 1, "save persisted at least 1 knowledge_item", {"count": len(item_ids)})
    report["save_result"] = {
        "ok": result.get("ok"),
        "file_path": result.get("file_path"),
        "git": result.get("git"),
        "sync": result.get("sync"),
        "item_ids": item_ids,
        "node_ids": result.get("knowledge_node_ids") or [],
        "entries_written": result.get("entries_written") or len(item_ids),
    }
    return result


def validate_graph_for_token(report: dict, run_token: str, expected_min: int) -> dict:
    graph = http_json(
        "GET",
        "/knowledge/graph-data",
        params={"persona_slug": PERSONA_SLUG, "mode": "semantic_tree", "max_depth": 6, "include_technical": "true"},
    )
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    token_nodes = [n for n in nodes if run_token in json.dumps(n, ensure_ascii=False)]
    by_type: dict[str, list] = {}
    for n in token_nodes:
        ntype = (n.get("data") or {}).get("node_type") or n.get("data", {}).get("nodeClass")
        by_type.setdefault(ntype, []).append(n)
    expect(report, len(token_nodes) >= expected_min,
           f"graph has at least {expected_min} nodes carrying run_token (found {len(token_nodes)})",
           {"by_type": {k: len(v) for k, v in by_type.items()}})
    token_node_ids = {n.get("id") for n in token_nodes}
    token_edges = [e for e in edges if e.get("source") in token_node_ids or e.get("target") in token_node_ids]
    expect(report, len(token_edges) >= 1,
           "graph has at least 1 edge touching the new subtree (today: persona link)",
           {"edge_count": len(token_edges)})
    report["graph_summary"] = {
        "token_nodes": len(token_nodes),
        "token_edges": len(token_edges),
        "by_type": {k: len(v) for k, v in by_type.items()},
    }
    return graph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2ekbsave%Y%m%d%H%M%S"))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--skip-llm", action="store_true",
                        help="inject a deterministic <knowledge_plan> directly (no Sofia call)")
    parser.add_argument("--use-fence", action="store_true",
                        help="like --skip-llm but uses a ```json fence to test the permissive parser")
    parser.add_argument("--admin-email",
                        default=os.environ.get("ADMIN_EMAIL") or os.environ.get("AI_BRAIN_SEED_ADMIN_EMAIL"))
    parser.add_argument("--admin-password",
                        default=os.environ.get("ADMIN_PASSWORD") or os.environ.get("AI_BRAIN_SEED_ADMIN_PASSWORD"))
    args = parser.parse_args()
    if args.use_fence:
        args.skip_llm = True

    run_token = slugify(args.run_token)
    report: dict[str, Any] = {
        "ok": False,
        "run_token": run_token,
        "api_base": API_BASE,
        "mode": "fenced-json" if args.use_fence else ("deterministic" if args.skip_llm else "llm"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{run_token}.json"

    try:
        print(f"\n== E2E kb-intake/save capture ({run_token} :: {report['mode']}) ==")
        health = http_json("GET", "/health")
        expect(report, health.get("status") == "ok", "backend health ok")
        login(report, args.admin_email, args.admin_password)

        if args.skip_llm:
            sid = write_synthetic_session(
                deterministic_plan(run_token),
                use_fence=args.use_fence,
                model=args.model,
            )
            expect(report, bool(sid), "synthetic session written to disk", {"fence": args.use_fence, "session_id": sid[:8]})
        else:
            sid = drive_sofia_for_plan(report, run_token, model=args.model)

        result = call_save(report, sid)
        # Tree validation: 5 entries planned, but with current bootstrap each
        # also creates a persona-mirror + tag nodes; we expect at least 5
        # token-bearing nodes (the items themselves).
        validate_graph_for_token(report, run_token, expected_min=5)

        report["ok"] = True
        report.pop("error", None)
        print(f"\nPASS e2e-kb-intake-save-capture. Report: {report_path}")
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
