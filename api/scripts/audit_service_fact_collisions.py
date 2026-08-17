"""Read-only dry-run for non-service facts that equal a published service.

This script never repairs or deletes rows. Historical correction remains a
separate, explicitly authorized CAS operation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from services import supabase_client  # noqa: E402


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _published_service_values(document: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    node_by_id = document.get("node_by_id") or {}
    for anchor in document.get("branch_anchors") or []:
        node = node_by_id.get(anchor) or {}
        values = {
            _fold(value)
            for value in (
                node.get("title"), node.get("slug"),
                *((node.get("data") or {}).get("aliases") or []),
            )
            if _fold(value)
        }
        for value in values:
            result.setdefault(value, set()).add(str(anchor))
    return result


def find_collisions(
    *,
    facts: list[dict[str, Any]],
    service_values: dict[str, set[str]],
) -> list[dict[str, Any]]:
    collisions: list[dict[str, Any]] = []
    for fact in facts:
        if str(fact.get("field_key") or "") == "servico" or fact.get("status") != "known":
            continue
        value = fact.get("value_json", fact.get("value"))
        anchors = service_values.get(_fold(value)) or set()
        if not anchors:
            continue
        collisions.append({
            "fact_id": fact.get("id"),
            "ledger_id": fact.get("ledger_id"),
            "field_key": fact.get("field_key"),
            "owner_node_id": fact.get("owner_node_id"),
            "source_message_id": fact.get("source_message_id"),
            "revision": fact.get("revision"),
            "matched_service_anchor_ids": sorted(anchors),
            "created_at": fact.get("created_at"),
        })
    return collisions


def find_operation_span_gaps(proofs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return technical identities for historical service mutations without proof spans."""
    gaps: list[dict[str, Any]] = []
    for proof_row in proofs:
        proof = proof_row.get("proof_result") or {}
        operations = (
            proof.get("applied_service_operations")
            if isinstance(proof.get("applied_service_operations"), list)
            else proof.get("service_operations") or []
        )
        consumed = {
            _fold(span.get("text"))
            for span in proof.get("consumed_service_spans") or []
            if _fold(span.get("text"))
        }
        missing = [
            {
                "action": operation.get("action"),
                "branch_anchor_node_id": operation.get("branch_anchor_node_id"),
                "branch_path_checksum": operation.get("branch_path_checksum"),
                "evidence_span": operation.get("evidence_span"),
            }
            for operation in operations
            if _fold(operation.get("evidence_span")) not in consumed
        ]
        if missing:
            gaps.append({
                "proof_id": proof_row.get("id"),
                "ledger_id": proof_row.get("ledger_id"),
                "canonical_inbound_id": proof_row.get("canonical_inbound_id"),
                "created_at": proof_row.get("created_at"),
                "operations_without_consumed_span": missing,
            })
    return gaps


def audit(*, persona_slug: str | None, lead_ref: int | None) -> dict[str, Any]:
    client = supabase_client.get_client()
    persona = supabase_client.get_persona(persona_slug) if persona_slug else None
    persona_id = str((persona or {}).get("id") or "") or None
    ledger_query = client.table("conversation_ledgers").select(
        "id,persona_id,lead_ref,publication_id,revision"
    )
    if persona_id:
        ledger_query = ledger_query.eq("persona_id", persona_id)
    if lead_ref is not None:
        ledger_query = ledger_query.eq("lead_ref", int(lead_ref))
    ledgers = ledger_query.execute().data or []
    ledger_ids = [str(row["id"]) for row in ledgers if row.get("id")]
    if not ledger_ids:
        return {
            "dry_run": True, "ledger_count": 0,
            "collision_count": 0, "collisions": [],
            "service_operation_span_gap_count": 0,
            "service_operation_span_gaps": [], "mutation_performed": False,
        }

    facts = (
        client.table("conversation_facts")
        .select("id,ledger_id,field_key,owner_node_id,status,value_json,source_message_id,revision,created_at")
        .in_("ledger_id", ledger_ids)
        .execute().data
        or []
    )
    proofs = (
        client.table("conversation_turn_proofs")
        .select("id,ledger_id,canonical_inbound_id,proof_result,created_at")
        .in_("ledger_id", ledger_ids)
        .execute().data
        or []
    )
    publications: dict[str, dict[str, Any]] = {}
    for ledger in ledgers:
        publication_id = str(ledger.get("publication_id") or "")
        if publication_id and publication_id not in publications:
            row = (
                client.table("graph_publications")
                .select("id,document_json,checksum,version")
                .eq("id", publication_id)
                .maybe_single().execute().data
                or {}
            )
            publications[publication_id] = row

    ledger_by_id = {str(row.get("id")): row for row in ledgers}
    all_collisions: list[dict[str, Any]] = []
    for publication_id, publication in publications.items():
        matching_ledger_ids = {
            str(row.get("id")) for row in ledgers
            if str(row.get("publication_id") or "") == publication_id
        }
        found = find_collisions(
            facts=[row for row in facts if str(row.get("ledger_id")) in matching_ledger_ids],
            service_values=_published_service_values(publication.get("document_json") or {}),
        )
        for row in found:
            ledger = ledger_by_id.get(str(row.get("ledger_id"))) or {}
            row.update({
                "lead_ref": ledger.get("lead_ref"),
                "publication_id": publication_id,
                "graph_version": publication.get("version"),
                "graph_checksum": publication.get("checksum"),
            })
        all_collisions.extend(found)
    operation_span_gaps = find_operation_span_gaps(proofs)
    return {
        "dry_run": True,
        "persona_slug": persona_slug,
        "lead_ref_filter": lead_ref,
        "ledger_count": len(ledgers),
        "fact_count": len(facts),
        "collision_count": len(all_collisions),
        "collisions": all_collisions,
        "service_operation_span_gap_count": len(operation_span_gaps),
        "service_operation_span_gaps": operation_span_gaps,
        "mutation_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona-slug")
    parser.add_argument("--lead-ref", type=int)
    args = parser.parse_args()
    print(json.dumps(
        audit(persona_slug=args.persona_slug, lead_ref=args.lead_ref),
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()
