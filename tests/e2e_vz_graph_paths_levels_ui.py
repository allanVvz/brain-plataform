#!/usr/bin/env python3
"""E2E: VZ graph path deletion/recreation and dynamic depth levels.

Creates 3, 6 and 10-level VZ chains, then uses Chromium to delete and recreate
a real graph edge visually. The test verifies the recreated path recalculates
the child level/importance and that focus keeps the ancestor path to persona.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse

from e2e_vz_lupas_oakley_graph_ui import (
    API_BASE,
    DASHBOARD_BASE,
    PERSONA_SLUG,
    TestFailure,
    expect,
    http_json,
    resolve_persona,
    slugify,
)


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ROOT / "test-artifacts" / "e2e-vz-graph-paths-levels-ui"

CHAIN_TYPES = [
    ("brand", "Brand"),
    ("campaign", "Campanha"),
    ("product", "Produto"),
    ("briefing", "Briefing"),
    ("audience", "Audiencia"),
    ("tone", "Tom"),
    ("rule", "Regra"),
    ("copy", "Copy"),
    ("faq", "FAQ"),
    ("asset", "Asset"),
]


def graph_data(run_token: str, focus: str | None = None) -> dict:
    params = {"persona_slug": PERSONA_SLUG, "mode": "graph", "max_depth": 6}
    if focus:
        params["focus"] = focus
    return http_json("GET", "/knowledge/graph-data", params=params)


def nodes_by_slug(graph: dict, run_token: str) -> dict[str, dict]:
    out = {}
    for node in graph.get("nodes") or []:
        data = node.get("data") or {}
        slug = data.get("slug") or ""
        if run_token in slug:
            out[slug] = node
    return out


def create_chain(report: dict, persona_id: str, run_token: str, depth: int) -> list[str]:
    entries = []
    slugs = []
    for index, (content_type, label) in enumerate(CHAIN_TYPES[:depth], start=1):
        slug = f"nivel-{depth}-{index}-{content_type}-{run_token}"
        slugs.append(slug)
        entries.append({
            "content_type": content_type,
            "slug": slug,
            "title": f"{label} VZ nivel {depth}.{index} [{run_token}]",
            "content": f"{label} da cadeia VZ com profundidade {depth}, posicao {index}.",
            "tags": [run_token, PERSONA_SLUG, content_type],
            "metadata": {"slug": slug, "tags": [run_token, PERSONA_SLUG, content_type]},
        })
    result = http_json("POST", "/knowledge/intake/plan", body={
        "persona_id": persona_id,
        "run_token": run_token,
        "source": "e2e_vz_graph_paths_levels_ui",
        "source_ref": run_token,
        "entries": entries,
        "links": [],
        "submitted_by": "e2e",
        "validate": True,
    }, timeout=180)
    expect(report, result.get("ok") is True, f"created {depth}-level chain entries", result)
    time.sleep(1.2)
    graph = graph_data(run_token)
    by_slug = nodes_by_slug(graph, run_token)
    for slug in slugs:
        expect(report, slug in by_slug, f"graph contains {slug}")
    for parent_slug, child_slug in zip(slugs, slugs[1:]):
        parent_id = by_slug[parent_slug]["id"]
        child_id = by_slug[child_slug]["id"]
        created = http_json("POST", "/knowledge/graph-edges", body={
            "source_node_id": parent_id,
            "target_node_id": child_id,
            "relation_type": "manual",
            "persona_id": persona_id,
            "weight": 1,
            "metadata": {"run_token": run_token, "source": "e2e_depth_chain"},
        })
        expect(report, bool((created.get("edge") or {}).get("id")), f"linked {parent_slug} -> {child_slug}")
    return slugs


def validate_levels_and_focus(report: dict, run_token: str, depth: int, slugs: list[str]) -> None:
    graph = graph_data(run_token, focus=f"{CHAIN_TYPES[depth - 1][0]}:{slugs[-1]}")
    by_slug = nodes_by_slug(graph, run_token)
    levels = [int((by_slug[slug].get("data") or {}).get("level")) for slug in slugs if slug in by_slug]
    expect(report, levels[0] == 99, f"{depth}-level chain starts at L99", levels)
    expect(report, all(a > b for a, b in zip(levels, levels[1:])), f"{depth}-level chain levels decrease by depth", levels)
    last_importance = float((by_slug[slugs[-1]].get("data") or {}).get("importance"))
    expect(report, 0 < last_importance < 1, f"{depth}-level last node has recalculated importance", last_importance)
    focus_path = graph.get("meta", {}).get("focus_path") or []
    focus_slugs = [step.get("slug") for step in focus_path]
    expect(report, all(slug in focus_slugs for slug in slugs), f"focus includes all {depth} ancestors", focus_slugs)
    expect(report, any(step.get("node_type") == "persona" for step in focus_path), "focus path includes persona")


def visual_delete_and_recreate(report: dict, run_token: str, slugs: list[str], *, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise TestFailure("playwright is required for this E2E") from exc

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{DASHBOARD_BASE}/knowledge/graph?" + parse.urlencode({"mode": "graph"})
    shot_deleted = ARTIFACTS_DIR / f"deleted-{run_token}.png"
    shot_recreated = ARTIFACTS_DIR / f"recreated-{run_token}.png"

    parent_title = f"{CHAIN_TYPES[0][1]} VZ nivel 3.1 [{run_token}]"
    child_title = f"{CHAIN_TYPES[1][1]} VZ nivel 3.2 [{run_token}]"

    graph = graph_data(run_token)
    by_slug = nodes_by_slug(graph, run_token)
    parent_id = by_slug[slugs[0]]["id"]
    child_id = by_slug[slugs[1]]["id"]
    edge = next(
        (
            edge for edge in graph.get("edges") or []
            if edge.get("source") == parent_id and edge.get("target") == child_id
        ),
        None,
    )
    expect(report, bool(edge and edge.get("id")), "real UI edge exists before delete", edge)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.add_init_script(
            "window.localStorage.setItem('ai-brain-persona-slug', 'vz-lupas');"
        )
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.get_by_placeholder(re.compile("Buscar")).fill(run_token)
        page.wait_for_timeout(1200)

        edge_group = page.locator(f'.react-flow__edge[data-id="{edge["id"]}"]').first
        expect(report, edge_group.count() > 0, "edge is selectable in ReactFlow DOM")
        edge_group.click(force=True)
        delete_button = page.get_by_test_id(f'delete-edge-{edge["id"]}')
        expect(report, delete_button.count() > 0, "delete edge button appears visually")
        delete_button.click()
        page.wait_for_timeout(1800)
        page.screenshot(path=str(shot_deleted), full_page=True)

        graph_after_delete = graph_data(run_token)
        deleted = not any(
            edge.get("source") == parent_id and edge.get("target") == child_id
            for edge in graph_after_delete.get("edges") or []
        )
        expect(report, deleted, "edge deleted through Chrome UI")

        source = page.locator(".react-flow__node", has_text=parent_title).first
        target = page.locator(".react-flow__node", has_text=child_title).first
        expect(report, source.count() > 0 and target.count() > 0, "source and target cards visible after delete")
        src_box = source.locator(".react-flow__handle-bottom").bounding_box()
        tgt_box = target.locator(".react-flow__handle-top").bounding_box()
        if not src_box or not tgt_box:
            raise TestFailure("Could not locate handles to recreate edge")
        page.mouse.move(src_box["x"] + src_box["width"] / 2, src_box["y"] + src_box["height"] / 2)
        page.mouse.down()
        page.mouse.move(tgt_box["x"] + tgt_box["width"] / 2, tgt_box["y"] + tgt_box["height"] / 2, steps=18)
        page.mouse.up()
        page.wait_for_timeout(2200)
        page.screenshot(path=str(shot_recreated), full_page=True)
        browser.close()

    graph_after_recreate = graph_data(run_token)
    recreated = any(
        edge.get("source") == parent_id and edge.get("target") == child_id
        for edge in graph_after_recreate.get("edges") or []
    )
    expect(report, recreated, "edge recreated visually with Chrome")
    validate_levels_and_focus(report, run_token, 3, slugs)
    report["screenshots"] = {"deleted": str(shot_deleted), "recreated": str(shot_recreated)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-token", default=os.environ.get("RUN_TOKEN") or datetime.now(timezone.utc).strftime("e2evzlevels%Y%m%d%H%M%S"))
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    run_token = slugify(args.run_token)
    report = {
        "ok": False,
        "run_token": run_token,
        "api_base": API_BASE,
        "dashboard_base": DASHBOARD_BASE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [],
    }
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / f"report-{run_token}.json"
    try:
        print(f"\n== E2E VZ Graph Paths Levels UI ({run_token}) ==")
        expect(report, http_json("GET", "/health").get("status") == "ok", "backend health ok")
        persona = resolve_persona(report)
        chains = {
            depth: create_chain(report, persona["id"], run_token, depth)
            for depth in (3, 6, 10)
        }
        for depth, slugs in chains.items():
            validate_levels_and_focus(report, run_token, depth, slugs)
        visual_delete_and_recreate(report, run_token, chains[3], headless=not args.headed)
        report["ok"] = True
        print(f"\nPASS e2e VZ Graph Paths Levels UI. Report: {report_path}")
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
