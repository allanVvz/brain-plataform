"""Revert the previous graph publication through the transactional CAS writer.

Runtime/binding rollback uses the service release workflow, never a graph CLI.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import graph_editor


def rollback(persona_slug: str, target_version: int, *, actor: str,
             base_publication_id: str, idempotency_key: str) -> dict:
    previous = graph_editor.previous_publication(persona_slug, base_publication_id)
    if not previous or int(previous["version"]) != target_version:
        raise graph_editor.GraphEditorConflict("revert_target_not_previous")
    return graph_editor.revert(persona_slug=persona_slug, to_publication_id=str(previous["id"]),
        base_publication_id=base_publication_id, actor=actor, idempotency_key=idempotency_key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("persona_slug")
    parser.add_argument("target_version", type=int)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--expected-base-publication-id", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args()
    print(json.dumps(rollback(args.persona_slug, args.target_version, actor=args.actor,
        base_publication_id=args.expected_base_publication_id, idempotency_key=args.idempotency_key),
        ensure_ascii=False, default=str))
