#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reprocessa knowledge_items + kb_entries existentes para o grafo semântico
(`knowledge_nodes`/`knowledge_edges`).

Quando rodar:
  • Logo após aplicar a migration 008 (a primeira vez).
  • Sempre que itens forem inseridos por caminho que pula bootstrap_from_item
    (sync direto via SQL, importação em batch, etc.).
  • Se a sidebar de /messages não exibir entidades que sabidamente existem
    em knowledge_items / kb_entries.

Uso:
    python tests/rebuild_graph.py                       # global (todas personas)
    python tests/rebuild_graph.py --persona tock-fatal  # só tock-fatal
    API_BASE=http://localhost:8000 python tests/rebuild_graph.py --persona tock-fatal
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, parse, request

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _post(path: str, params: dict | None = None, timeout: float = 600.0) -> dict | list | None:
    url = API_BASE + path
    if params:
        url += ("&" if "?" in url else "?") + parse.urlencode(params)
    req = request.Request(url, method="POST", headers={"Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"HTTP {e.code} {path}: {body}")
    except error.URLError as e:
        raise SystemExit(f"connection failed {path}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild knowledge graph from existing items.")
    parser.add_argument("--persona", help="persona slug (ex: tock-fatal). Omita pra global.")
    args = parser.parse_args()

    params: dict = {}
    if args.persona:
        params["persona_slug"] = args.persona

    print(f"→ POST /knowledge/graph/rebuild "
          f"{('persona=' + args.persona) if args.persona else '(global)'}")
    result = _post("/knowledge/graph/rebuild", params)
    counts = (result or {}).get("counts") or {}

    print(f"\nPersona      : {result.get('persona_slug') or '(global)'}")
    print(f"items_seen   : {counts.get('items_seen', 0)}")
    print(f"items_mirror : {counts.get('items_mirrored', 0)}")
    print(f"items_skip   : {counts.get('items_skipped', 0)}")
    print(f"kb_seen      : {counts.get('kb_seen', 0)}")
    print(f"kb_mirror    : {counts.get('kb_mirrored', 0)}")
    print(f"kb_skip      : {counts.get('kb_skipped', 0)}")

    errors = counts.get("errors") or []
    if errors:
        print(f"\nERRORS ({len(errors)} mostrados):")
        for e in errors:
            print(f"  - {e}")
        return 1

    if (counts.get("items_mirrored", 0) + counts.get("kb_mirrored", 0)) == 0:
        print("\nWARN  Nenhum item espelhado. Possíveis causas:")
        print("  - Migration 008 não aplicada (knowledge_nodes/edges ausentes).")
        print("  - Tabelas knowledge_items / kb_entries vazias para essa persona.")
        return 2

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
