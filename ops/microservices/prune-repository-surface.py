#!/usr/bin/env python3
"""Remove repository functions unreachable from production entrypoints.

Dry-run is the default. The input repository remains untouched unless
``--apply`` is provided. Non-function top-level declarations are preserved.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
AUDITOR_PATH = HERE / "audit-repository-surface.py"


def _auditor():
    spec = importlib.util.spec_from_file_location("repository_surface_auditor", AUDITOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prune(api_root: Path, repository_module: str, *, apply: bool = False) -> dict:
    audit = _auditor().audit(api_root, repository_module)
    repository_path = api_root / Path(*repository_module.split(".")).with_suffix(".py")
    source = repository_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(repository_path))
    unreachable = set(audit["unreachable_functions"])
    ranges: list[tuple[int, int, str]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in unreachable:
            continue
        decorated = [item.lineno for item in node.decorator_list]
        start = min([node.lineno, *decorated]) - 1
        # Section banners immediately preceding a removed function otherwise
        # survive as misleading empty domains. Stop at real code/imports.
        while start > 0:
            previous = source.splitlines()[start - 1].strip()
            if previous and not previous.startswith("#"):
                break
            start -= 1
        ranges.append((start, node.end_lineno or node.lineno, node.name))

    lines = source.splitlines(keepends=True)
    for start, end, _name in sorted(ranges, reverse=True):
        del lines[start:end]
        while start < len(lines) - 2 and lines[start].strip() == "" and lines[start + 1].strip() == "":
            del lines[start]
    result_source = "".join(lines)
    result = {
        "repository": str(repository_path.resolve()),
        "applied": apply,
        "removed_count": len(ranges),
        "removed_functions": sorted(name for _start, _end, name in ranges),
        "before_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(result_source.encode()).hexdigest(),
        "before_bytes": len(source.encode()),
        "after_bytes": len(result_source.encode()),
    }
    if apply:
        repository_path.write_text(result_source, encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("api_root", type=Path)
    parser.add_argument("repository_module")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(
        prune(args.api_root.resolve(), args.repository_module, apply=args.apply),
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
