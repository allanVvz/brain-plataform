"""Build a safe Utzig POC from the audited Aurora v75 publication.

This is deliberately a local authoring tool.  It imports only service facts
that have a matching, already-published Utzig service anchor.  Aurora's
persona, rules, tone, bindings, credentials, leads and commercial commitments
are never copied.  The source snapshot remains the complete audit record.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.prepare_graph_bundle_candidate import (  # noqa: E402
    reconstruct_bundle,
    validate_active_export,
)
from services.graph_compiler_v3 import canonical_checksum  # noqa: E402


UTZIG_PUBLICATION_ID = "df1bbf86-05be-4a5d-a507-256a4b2155c5"
UTZIG_CHECKSUM = "sha256:6ded5d383b8cc455be3e937bb8e869041d7f654bbafa1d4ae3c80fa37dec14a4"
AURORA_PUBLICATION_ID = "d5c7afd7-24ea-44d6-90e9-8532fd3fc303"
AURORA_CHECKSUM = "sha256:3f727095819f75836453af2e3bbee42c1138b50a6dc99a59f502b5a1917811ec"
IMPORT_SOURCE = "aurora_active_graph_publication_v75_2026_09_23"

# These are identical services in the two audited graphs.  A missing entry is
# intentionally not guessed: importing a claim without a Utzig anchor would
# turn a competitor's fact into an unsupported Utzig promise.
SERVICE_MAP = {
    "bodywork": "aurora-product-bodywork",
    "engine-bay-wash": "aurora-product-engine-wash",
    "evaluation": "aurora-product-evaluation",
    "glass-polish": "aurora-product-glass-polish",
    "interior-cleaning": "aurora-product-interior",
    "painting": "aurora-product-paint",
    "technical-polish": "aurora-product-polish",
    "commercial-polish": "aurora-product-polish-commercial",
    "headlight-restoration": "aurora-product-polish-headlight",
    "ppf": "aurora-product-ppf",
    "vitrification": "aurora-product-vitrification",
    "detailed-wash": "aurora-product-wash",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object_required:{path}")
    return value


def _nodes(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(node["id"]): node for node in document.get("nodes") or []}


def _validate_aurora_source(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate identity/integrity without pretending v75 used today's compiler."""
    publication = snapshot.get("publication") or {}
    document = snapshot.get("document") or {}
    if (
        str(publication.get("id") or "") != AURORA_PUBLICATION_ID
        or int(publication.get("version") or 0) != 75
        or str(publication.get("status") or "").lower() != "active"
        or str(publication.get("checksum") or "") != AURORA_CHECKSUM
        or str(document.get("checksum") or "") != AURORA_CHECKSUM
    ):
        raise ValueError("aurora_active_v75_identity_mismatch")
    unsigned = copy.deepcopy(document)
    unsigned.pop("checksum", None)
    if canonical_checksum(unsigned) != AURORA_CHECKSUM:
        raise ValueError("aurora_active_v75_integrity_mismatch")
    return document


def _source_data(node: dict[str, Any]) -> dict[str, Any]:
    """Keep factual detail, excluding Aurora's execution policy and markdown."""
    data = copy.deepcopy(node.get("data") or {})
    for key in (
        "markdown", "markdown_checksum", "markdown_renderer", "graph_json_node_id",
        "booking", "completion", "qualification", "handoff", "capabilities", "claims",
    ):
        data.pop(key, None)
    return data


def _provenance(source_node: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": IMPORT_SOURCE,
        "source_publication_id": AURORA_PUBLICATION_ID,
        "source_publication_version": 75,
        "source_publication_checksum": AURORA_CHECKSUM,
        "source_node_id": str(source_node["id"]),
        "source_node_type": str(source_node["node_type"]),
        "source_validation_status": str(source_node.get("status") or ""),
    }


def _safe_target_text(value: str, *, target_slug: str) -> str:
    """Retain service facts while removing Aurora-only commercial promises."""
    text = value.replace("Equipe Aurora", "equipe da Utzig Garage").replace(
        "A Aurora oferece", "A Utzig Garage oferece"
    )
    if target_slug == "evaluation":
        return "Avaliação presencial do veículo para orientar os próximos passos."
    if target_slug == "engine-bay-wash":
        return "Lavagem técnica do motor e do cofre. A equipe avalia a condição antes de orientar os próximos passos."
    if target_slug == "commercial-polish":
        return text.replace("Tem preço mais acessível, mas ", "")
    if target_slug == "vitrification":
        return "Vitrificação com camada de proteção química."
    return text


def build(utzig_snapshot: dict[str, Any], aurora_snapshot: dict[str, Any]) -> dict[str, Any]:
    utzig_publication, utzig_document = validate_active_export(
        utzig_snapshot,
        expected_publication_id=UTZIG_PUBLICATION_ID,
        expected_version=2,
        expected_runtime_checksum=UTZIG_CHECKSUM,
    )
    aurora_document = _validate_aurora_source(aurora_snapshot)
    bundle = reconstruct_bundle(utzig_publication, utzig_document)
    bundle["metadata"].update({
        "purpose": "utzig_safe_service-detail_poc",
        "publication_allowed": False,
        "internal_wa_validator_test_allowed": False,
        "aurora_source_inventory": {
            "publication_id": AURORA_PUBLICATION_ID,
            "version": 75,
            "checksum": AURORA_CHECKSUM,
            "nodes": len(aurora_document.get("nodes") or []),
            "edges": len(aurora_document.get("edges") or []),
            "rag_chunks": int(aurora_snapshot.get("chunk_count") or 0),
        },
        "import_scope": "matching_service_details_only",
        "excluded_source_types": ["persona", "tone", "rule", "service"],
        "commercial_commitment_policy": "human_handoff_for_price_schedule_stock_availability",
    })

    target_nodes = {str(node["id"]): node for node in bundle["nodes"]}
    source_nodes = _nodes(aurora_document)
    imported = []
    for target_slug, source_product_id in SERVICE_MAP.items():
        target_product = target_nodes[f"product:{target_slug}"]
        target_copy = target_nodes[f"copy:{target_slug}"]
        target_faq = target_nodes[f"faq:service:{target_slug}"]
        source_product = source_nodes[source_product_id]
        source_copy = next(
            node for node in source_nodes.values()
            if node.get("node_type") == "copy"
            and any(
                edge.get("source") == source_product_id and edge.get("target") == node.get("id")
                for edge in aurora_document.get("edges") or []
            )
        )
        factual_data = _source_data(source_product)
        detail = _safe_target_text(
            str(source_product.get("summary") or factual_data.get("summary") or "").strip(),
            target_slug=target_slug,
        )
        copy_content = _safe_target_text(
            str((source_copy.get("data") or {}).get("content") or source_copy.get("summary") or detail).strip(),
            target_slug=target_slug,
        )
        provenance = _provenance(source_product)

        target_product["summary"] = detail
        target_product["data"].update({
            "source": IMPORT_SOURCE,
            "status": "approved",
            "aliases": factual_data.get("aliases") or target_product["data"].get("aliases") or [],
            "summary": detail,
            "requires_in_person_evaluation": bool(factual_data.get("requires_in_person_evaluation")),
            "import_provenance": provenance,
        })
        target_copy["summary"] = copy_content
        target_copy["data"].update({
            "source": IMPORT_SOURCE,
            "status": "approved",
            "content": copy_content,
            "import_provenance": _provenance(source_copy),
        })
        # The prior Utzig graph had availability only.  The fact itself and its
        # exact copy are now both authorized as service_detail evidence, which
        # is the claim rejected by the proof checker in the rollback canary.
        target_faq["summary"] = f"{detail} Peça uma avaliação para a equipe orientar o cuidado adequado ao veículo."
        target_faq["data"].update({
            "source": IMPORT_SOURCE,
            "status": "approved",
            "answer": target_faq["summary"],
            "import_provenance": provenance,
            "claims": [
                {
                    "claim_type": "availability",
                    "policy": "published_service_anchor",
                    "evidence_node_ids": [target_faq["id"]],
                },
                {
                    "claim_type": "service_detail",
                    "policy": "published_service_detail_with_source_provenance",
                    "evidence_node_ids": [target_faq["id"]],
                },
            ],
        })
        imported.append({"target": target_product["id"], "source": source_product_id})
    bundle["metadata"]["imported_service_details"] = imported
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("utzig_snapshot", type=Path)
    parser.add_argument("aurora_snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline-document-output", type=Path)
    args = parser.parse_args()
    result = build(_load(args.utzig_snapshot), _load(args.aurora_snapshot))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.baseline_document_output:
        baseline = _load(args.utzig_snapshot)["document"]
        args.baseline_document_output.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_document_output.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"output": str(args.output), "imported_services": len(SERVICE_MAP)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
