#!/usr/bin/env python3
"""Audit repository functions and literal DB objects reachable in production."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SURFACE_SCRIPT = HERE / "audit-python-surface.py"


def _load_surface_module():
    spec = importlib.util.spec_from_file_location("audit_python_surface", SURFACE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _attribute_root(node: ast.Attribute) -> str | None:
    value = node.value
    while isinstance(value, ast.Attribute):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def _external_roots(paths: list[Path], repository_names: set[str]) -> set[str]:
    roots: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        aliases = {"supabase_client"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for item in node.names:
                    if item.name in repository_names:
                        aliases.add(item.asname or item.name.rsplit(".", 1)[-1])
            elif isinstance(node, ast.Import):
                for item in node.names:
                    if item.name in repository_names:
                        aliases.add(item.asname or item.name.rsplit(".", 1)[-1])
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _attribute_root(node) in aliases:
                roots.add(node.attr)
    return roots


def _literal_db_objects(node: ast.AST) -> tuple[set[str], set[str]]:
    tables: set[str] = set()
    rpcs: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr not in {"table", "rpc"} or not child.args:
            continue
        first = child.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        (tables if child.func.attr == "table" else rpcs).add(first.value)
    return tables, rpcs


def audit(api_root: Path, repository_module: str, roots: list[str] | None = None) -> dict:
    surface = _load_surface_module()
    production = surface.audit(api_root, roots or ["main", "workers.runner"])
    modules = surface.module_index(api_root)
    repository_path = modules[repository_module]
    tree = ast.parse(repository_path.read_text(encoding="utf-8-sig"), filename=str(repository_path))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    production_paths = [
        modules[name]
        for name in production["reachable"]
        if name != repository_module
    ]
    pending = list(_external_roots(
        production_paths,
        {repository_module, "services.supabase_client"},
    ) & functions.keys())
    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in functions and node.func.id not in reachable:
                    pending.append(node.func.id)
    tables: set[str] = set()
    rpcs: set[str] = set()
    for name in reachable:
        function_tables, function_rpcs = _literal_db_objects(functions[name])
        tables.update(function_tables)
        rpcs.update(function_rpcs)
    return {
        "api_root": str(api_root.resolve()),
        "repository_module": repository_module,
        "root_functions": sorted(_external_roots(
            production_paths, {repository_module, "services.supabase_client"}
        ) & functions.keys()),
        "reachable_functions": sorted(reachable),
        "unreachable_functions": sorted(set(functions) - reachable),
        "literal_tables": sorted(tables),
        "literal_rpcs": sorted(rpcs),
        "counts": {
            "all_functions": len(functions),
            "reachable_functions": len(reachable),
            "unreachable_functions": len(functions) - len(reachable),
            "literal_tables": len(tables),
            "literal_rpcs": len(rpcs),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("api_root", type=Path)
    parser.add_argument("repository_module")
    args = parser.parse_args()
    print(json.dumps(
        audit(args.api_root.resolve(), args.repository_module),
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
