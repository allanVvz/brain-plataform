#!/usr/bin/env python3
"""Report the Python modules reachable from service production entrypoints."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


def module_name(api_root: Path, path: Path) -> str:
    relative = path.relative_to(api_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def module_index(api_root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in api_root.rglob("*.py"):
        relative = path.relative_to(api_root)
        if relative.parts[0] in {"tests", "scripts"} or "__pycache__" in relative.parts:
            continue
        name = module_name(api_root, path)
        if name:
            result[name] = path
    return result


def package_for(module: str, path: Path) -> str:
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def resolve_from(package: str, level: int, imported: str | None) -> str:
    if level == 0:
        return imported or ""
    parts = package.split(".") if package else []
    keep = max(0, len(parts) - level + 1)
    parts = parts[:keep]
    if imported:
        parts.extend(imported.split("."))
    return ".".join(part for part in parts if part)


def internal_imports(module: str, path: Path, modules: dict[str, Path]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    package = package_for(module, path)
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    dependencies.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_from(package, node.level, node.module)
            if base in modules:
                dependencies.add(base)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base else alias.name
                if candidate in modules:
                    dependencies.add(candidate)
    return dependencies


def audit(api_root: Path, roots: list[str]) -> dict:
    modules = module_index(api_root)
    missing_roots = sorted(set(roots) - modules.keys())
    if missing_roots:
        raise SystemExit(f"unknown production roots: {', '.join(missing_roots)}")
    reachable: set[str] = set()
    pending = list(roots)
    while pending:
        module = pending.pop()
        if module in reachable:
            continue
        reachable.add(module)
        pending.extend(internal_imports(module, modules[module], modules) - reachable)
    unreachable = set(modules) - reachable
    return {
        "api_root": str(api_root.resolve()),
        "roots": roots,
        "reachable": sorted(reachable),
        "unreachable": sorted(unreachable),
        "counts": {
            "all": len(modules),
            "reachable": len(reachable),
            "unreachable": len(unreachable),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("api_root", type=Path)
    parser.add_argument("--root", action="append", dest="roots")
    args = parser.parse_args()
    roots = args.roots or ["main", "workers.runner"]
    print(json.dumps(audit(args.api_root.resolve(), roots), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
