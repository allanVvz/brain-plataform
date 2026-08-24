#!/usr/bin/env python3
"""Classify a change set for selective production deployment."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import PurePosixPath
from typing import Iterable


CONVERSATIONAL = re.compile(
    r"^(?:"
    r"api/(?:services/(?:conversation_runtime|graph_agent_runtime_v3|"
    r"graph_proof_checker_v3|wa_validator_service|whatsapp_outbox|"
    r"supabase_client)|routes/(?:messages|evolution_webhook|"
    r"whatsapp_webhook)|workers/(?:whatsapp_dispatch_worker|wa_validator_worker))\.py|"
    r"api/n8n-workflows/|"
    r"tests/(?:fixtures/(?:conversation_repetition_cases|sdr_flow_cases)\.json|"
    r"test_(?:graph_agent_runtime_v3|graph_proof_checker_v3|wa_validator_service|"
    r"whatsapp_exactly_once).*\.py)|"
    r"dashboard/(?:scripts/(?:conversation-repetition|wa-validator)|"
    r"e2e/wa-validator/)|"
    r"\.agents/skills/brain-agent-e2e/"
    r")"
)
MIGRATION = re.compile(r"^supabase/migrations/[^/]+\.sql$")
WORKER = re.compile(r"^api/workers/.*\.py$")
DASHBOARD = re.compile(r"^dashboard/")
GRAPH_CONTENT = re.compile(
    r"^(?:data/graph_bundles/|api/scripts/(?:publish|compile|plan)_.*graph.*\.py$)"
)
DOCUMENTATION = re.compile(
    r"^(?:docs/|README(?:\.[^/]+)?$|AGENTS\.md$|\.agents/(?:commands|skills)/.*\.md$)"
)
RELEASE_INFRA = re.compile(
    r"^(?:\.github/workflows/|ops/(?:vps|release)/|infra/|docker-compose\.yml$|"
    r"\.env\.compose\.example$|api/Dockerfile$|api/requirements(?:-[^/]+)?\.txt$)"
)
API = re.compile(r"^(?:api/|scripts/|tests/)")


def normalize(paths: Iterable[str]) -> list[str]:
    values: list[str] = []
    for raw in paths:
        value = str(PurePosixPath(str(raw).strip().replace("\\", "/")))
        if value and value != ".":
            values.append(value)
    return sorted(set(values))


def classify(paths: Iterable[str]) -> dict[str, object]:
    files = normalize(paths)
    matched = {
        "migration": any(MIGRATION.search(path) for path in files),
        "conversational": any(CONVERSATIONAL.search(path) for path in files),
        "worker": any(WORKER.search(path) for path in files),
        "dashboard": any(DASHBOARD.search(path) for path in files),
        "graph": any(GRAPH_CONTENT.search(path) for path in files),
        "documentation": bool(files) and all(DOCUMENTATION.search(path) for path in files),
        "release_infra": any(RELEASE_INFRA.search(path) for path in files),
        "api": any(
            API.search(path) and not WORKER.search(path)
            for path in files
        ),
    }
    graph_only = bool(files) and all(
        GRAPH_CONTENT.search(path) or DOCUMENTATION.search(path)
        for path in files
    )
    if not files or matched["documentation"]:
        impact = "documentation"
    elif matched["migration"]:
        impact = "migration"
    elif (
        matched["release_infra"]
        or matched["conversational"]
        or (matched["api"] and matched["worker"])
    ):
        impact = "conversational"
    elif matched["worker"]:
        impact = "worker"
    elif graph_only:
        impact = "graph"
    elif matched["api"]:
        impact = "api"
    elif matched["dashboard"]:
        impact = "dashboard"
    else:
        # Unknown production files fail closed through the complete path.
        impact = "migration"
    return {
        "class": impact,
        "files": files,
        "touch_vps": impact in {"api", "worker", "conversational", "migration"},
        "publish_api": impact in {"api", "conversational", "migration"},
        "publish_worker": impact in {"worker", "conversational", "migration"},
        "publish_migrate": impact == "migration",
        "pause_claims": impact in {"worker", "conversational", "migration"},
        "backup": impact == "migration",
        "wa_validator": impact == "conversational",
    }


def _git_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, head],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()
    files = args.file or (_git_files(args.base, args.head) if args.base else [])
    result = classify(files)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            for key in (
                "class", "touch_vps", "publish_api", "publish_worker",
                "publish_migrate", "pause_claims", "backup", "wa_validator",
            ):
                handle.write(f"{key}={str(result[key]).lower()}\n")


if __name__ == "__main__":
    main()
