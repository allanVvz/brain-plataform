#!/usr/bin/env python3
"""Classify changed paths from the single declarative release policy."""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "ops/release/release-services.json"


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify(paths: list[str], policy: dict) -> dict:
    normalized = [path.replace("\\", "/") for path in paths if path]
    paths = sorted({path[2:] if path.startswith("./") else path for path in normalized})
    deploy_paths = [
        path for path in paths
        if not matches(path, policy["ci_only"])
    ]
    services = [
        name for name, config in policy["services"].items()
        if any(matches(path, config["paths"]) for path in deploy_paths)
    ]
    dashboard = any(matches(path, policy["dashboard"]) for path in deploy_paths)
    schema = any(matches(path, policy["schema"]) for path in deploy_paths)
    infrastructure = any(matches(path, policy["infrastructure"]) for path in deploy_paths)
    recognized = [
        path for path in paths
        if matches(path, policy["ci_only"])
        or matches(path, policy["dashboard"])
        or matches(path, policy["schema"])
        or matches(path, policy["infrastructure"])
        or any(matches(path, config["paths"]) for config in policy["services"].values())
    ]
    unknown = sorted(set(paths) - set(recognized))
    if unknown:
        raise ValueError("unclassified release paths: " + ", ".join(unknown))
    runtime_approval = any(
        matches(path, policy["runtime_approval_paths"]) for path in paths
    ) or any(policy["services"][name]["pause_policy"] == "global" for name in services) or schema or infrastructure
    return {
        "paths": paths,
        "services": services,
        "deploy_services": list(policy["services"]) if infrastructure else services,
        "build_images": bool(services),
        "dashboard": dashboard,
        "schema": schema,
        "infrastructure": infrastructure,
        "runtime_approval": runtime_approval,
        "content_only": bool(paths) and not services and all(
            matches(path, policy["ci_only"]) for path in paths
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = classify(args.paths, json.loads(args.policy.read_text(encoding="utf-8")))
    rendered = json.dumps(result, separators=(",", ":"))
    print(rendered)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"classification={rendered}\n")
            output.write(f"services={json.dumps(result['services'], separators=(',', ':'))}\n")
            output.write(f"deploy_services={json.dumps(result['deploy_services'], separators=(',', ':'))}\n")
            for key in ("build_images", "dashboard", "schema", "infrastructure", "runtime_approval", "content_only"):
                output.write(f"{key}={str(result[key]).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
