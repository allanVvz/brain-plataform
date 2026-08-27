#!/usr/bin/env python3
"""Build the production release plan from a change set.

The detailed ``class`` says which components changed. ``release_class`` is the
small operational contract used by CI and production: frontend, API-only or
shared runtime.  Keeping those concepts separate avoids sending every change
through the most expensive release path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import PurePosixPath
from pathlib import Path
from typing import Iterable, Mapping


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
DESTRUCTIVE_SQL = re.compile(
    r"\b(?:drop\s+(?:table|column|schema|type)|truncate\s+table|"
    r"delete\s+from|update\s+[a-z0-9_.\"]+\s+set|"
    r"alter\s+table\b[\s\S]{0,200}\b(?:drop|type)\b)",
    re.IGNORECASE,
)


def migration_backup_mode(
    files: Iterable[str], migration_texts: Mapping[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Return evidence_only or fresh_required and the reasons.

    A migration can explicitly opt into either policy with a header. Without a
    header we detect common destructive statements. Missing source fails closed
    because a plan must never guess that an unread migration is harmless.
    """
    texts = migration_texts or {}
    reasons: list[str] = []
    migration_files = [path for path in files if MIGRATION.search(path)]
    if not migration_files:
        return "evidence_only", reasons
    for path in migration_files:
        text = texts.get(path)
        if text is None:
            reasons.append(f"unread_migration:{path}")
            continue
        header = "\n".join(text.splitlines()[:12]).lower()
        if "brain-release-risk: data-risk" in header:
            reasons.append(f"declared_data_risk:{path}")
        elif "brain-release-risk: compatible" in header:
            continue
        elif DESTRUCTIVE_SQL.search(text):
            reasons.append(f"destructive_sql:{path}")
    return ("fresh_required" if reasons else "evidence_only"), reasons


def normalize(paths: Iterable[str]) -> list[str]:
    values: list[str] = []
    for raw in paths:
        value = str(PurePosixPath(str(raw).strip().replace("\\", "/")))
        if value and value != ".":
            values.append(value)
    return sorted(set(values))


def classify(
    paths: Iterable[str], migration_texts: Mapping[str, str] | None = None,
) -> dict[str, object]:
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
    if impact in {"documentation", "dashboard", "graph"}:
        release_class = "frontend"
    elif impact == "api":
        release_class = "api"
    else:
        release_class = "runtime"
    backup_mode, backup_reasons = migration_backup_mode(files, migration_texts)
    resume_required = release_class == "runtime"
    components = {
        "frontend": impact == "dashboard",
        "content": impact == "graph",
        "api": impact in {"api", "conversational", "migration"},
        "worker": impact in {"worker", "conversational", "migration"},
        "migration": impact == "migration",
    }
    gates = ["ci"]
    if release_class == "frontend":
        gates.append("frontend_deploy" if components["frontend"] else "documentation")
    elif release_class == "api":
        gates.extend(["immutable_api_image", "api_readiness", "automatic_rollback"])
    else:
        gates.extend([
            "release_pause", "queue_drain", "immutable_images",
            "runtime_readiness", "release_report", "authorized_resume",
        ])
        if components["migration"]:
            gates.append("migration_manifest")
            gates.append(
                "fresh_backup" if backup_mode == "fresh_required"
                else "backup_evidence"
            )
    return {
        "schema_version": 1,
        "class": impact,
        "release_class": release_class,
        "files": files,
        "components": components,
        "gates": gates,
        "touch_vps": impact in {"api", "worker", "conversational", "migration"},
        "publish_api": impact in {"api", "conversational", "migration"},
        "publish_worker": impact in {"worker", "conversational", "migration"},
        "publish_migrate": impact == "migration",
        "pause_claims": impact in {"worker", "conversational", "migration"},
        "pause_type": "release_pause" if resume_required else "none",
        "pause": {
            "type": "release_pause" if resume_required else "none",
            "scope": "shared_runtime" if resume_required else "none",
        },
        "resume_required": resume_required,
        "backup_mode": backup_mode,
        "backup_reasons": backup_reasons,
        # Compatibility output for older workflows.
        "backup": backup_mode == "fresh_required",
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
    migration_texts: dict[str, str] = {}
    for path in normalize(files):
        if not MIGRATION.search(path):
            continue
        candidate = Path(path)
        if candidate.is_file():
            migration_texts[path] = candidate.read_text(encoding="utf-8")
    result = classify(files, migration_texts)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            for key in (
                "class", "release_class", "touch_vps", "publish_api",
                "publish_worker", "publish_migrate", "pause_claims", "backup",
                "backup_mode", "resume_required",
            ):
                handle.write(f"{key}={str(result[key]).lower()}\n")
            handle.write("plan_json=" + json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
