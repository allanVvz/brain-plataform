"""Enrich the approved Utzig graph with source-backed service FAQ coverage."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from build_utzig_aurora_poc_bundle import (
    AURORA_CHECKSUM,
    AURORA_PUBLICATION_ID,
    IMPORT_SOURCE,
    SERVICE_MAP,
)


SKIP_SOURCE_FAQS = {
    # The existing Utzig service FAQ already covers availability.
    "aurora-faq-chapeacao-disponivel", "aurora-faq-motor-disponivel",
    "aurora-faq-vidros-disponivel", "aurora-faq-higienizacao-disponivel",
    "aurora-faq-pintura-disponivel", "aurora-faq-polimento-tecnico-disponivel",
    "aurora-faq-farois-disponivel", "aurora-faq-ppf-disponivel",
    "aurora-faq-vitrificacao-disponivel", "aurora-faq-lavagem-detalhada-disponivel",
    # This source lists subtypes as unavailable and adds no useful Utzig fact.
    "aurora-faq-polimento-subtipos",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def target_text(value: str) -> str:
    return (
        value.replace("A Aurora", "A Utzig Garage")
        .replace("da Aurora", "da Utzig Garage")
        .replace("pela Lia", "pela assistente virtual")
        .replace("a Lia", "a assistente virtual")
        .replace("Lia", "assistente virtual")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("aurora_snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    bundle = load(args.bundle)
    snapshot = load(args.aurora_snapshot)
    publication = snapshot["publication"]
    document = snapshot["document"]
    assert publication["id"] == AURORA_PUBLICATION_ID
    assert publication["checksum"] == AURORA_CHECKSUM

    source_nodes = {node["id"]: node for node in document["nodes"]}
    outgoing: dict[str, list[str]] = {}
    for edge in document["edges"]:
        if edge.get("relation_type") == "contains":
            outgoing.setdefault(edge["source"], []).append(edge["target"])

    existing_ids = {node["id"] for node in bundle["nodes"]}
    added_faqs: list[str] = []
    enriched_copies: list[str] = []
    for target_slug, source_product_id in SERVICE_MAP.items():
        copy_id = f"copy:{target_slug}"
        copy_node = next(node for node in bundle["nodes"] if node["id"] == copy_id)
        service_answers: list[str] = []
        for source_id in outgoing.get(source_product_id, []):
            source = source_nodes[source_id]
            if (
                source.get("node_type") != "faq"
                or source.get("status") != "approved"
                or source_id in SKIP_SOURCE_FAQS
            ):
                continue
            suffix = source_id.removeprefix("aurora-faq-")
            faq_id = f"faq:service:{target_slug}:{suffix}"
            if faq_id in existing_ids:
                continue
            question = target_text(str((source.get("data") or {}).get("question") or source.get("title") or "").strip())
            answer = target_text(str((source.get("data") or {}).get("answer") or source.get("summary") or "").strip())
            if not question or not answer:
                continue
            provenance = {
                "source": IMPORT_SOURCE,
                "source_publication_id": AURORA_PUBLICATION_ID,
                "source_publication_version": 75,
                "source_publication_checksum": AURORA_CHECKSUM,
                "source_node_id": source_id,
                "source_node_type": "faq",
                "source_validation_status": "approved",
            }
            node = {
                "id": faq_id,
                "node_type": "faq",
                "slug": faq_id.replace(":", "-"),
                "title": question,
                "summary": answer,
                "tags": copy.deepcopy(source.get("tags") or []),
                "status": "approved",
                "projection_node_id": str(uuid5(NAMESPACE_URL, f"brain-ai:{faq_id}")),
                "data": {
                    "question": question,
                    "question_aliases": copy.deepcopy((source.get("data") or {}).get("question_aliases") or []),
                    "answer": answer,
                    "source": IMPORT_SOURCE,
                    "status": "approved",
                    "source_node_id": f"product:{target_slug}",
                    "source_node_type": "product",
                    "branch_path": [f"product:{target_slug}", faq_id],
                    "import_provenance": provenance,
                    "claims": [{
                        "claim_type": "service_detail",
                        "policy": "published_service_detail_with_source_provenance",
                        "evidence_node_ids": [faq_id],
                    }],
                    "validation_status": "approved",
                    "graph_json_node_id": faq_id,
                },
            }
            bundle["nodes"].append(node)
            bundle["edges"].extend([
                {
                    "id": f"edge:{target_slug}:{suffix}:contains", "source": f"product:{target_slug}",
                    "target": faq_id, "relation_type": "contains", "weight": 1.0, "primary": True,
                    "metadata": {
                        "active": True,
                        "primary": True,
                        "graph_json_edge_id": f"edge:{target_slug}:{suffix}:contains",
                    },
                },
                {
                    "id": f"edge:{target_slug}:{suffix}", "source": f"product:{target_slug}",
                    "target": faq_id, "relation_type": "answers_question", "weight": 1.0,
                    "metadata": {"active": True, "graph_json_edge_id": f"edge:{target_slug}:{suffix}"},
                },
                {
                    "id": f"edge:{target_slug}:{suffix}:embedded", "source": faq_id,
                    "target": "embedded:utzig", "relation_type": "publishes_to", "weight": 1.0,
                    "metadata": {"active": True, "graph_json_edge_id": f"edge:{target_slug}:{suffix}:embedded"},
                },
            ])
            existing_ids.add(faq_id)
            added_faqs.append(faq_id)
            service_answers.append(answer)

        if service_answers:
            data = copy_node.setdefault("data", {})
            data["conversation_variants"] = [
                {"purpose": "explain", "content": service_answers[0]},
                {"purpose": "set_expectation", "content": service_answers[-1]},
                {"purpose": "next_step", "content": "Conte o que você quer melhorar no veículo; a equipe confirma avaliação, preço, prazo e agenda."},
            ]
            data["content_approval"] = {
                "status": "approved", "source": IMPORT_SOURCE,
                "approved_scope": "matching_service_facts_and_human_confirmation_limits",
            }
            enriched_copies.append(copy_id)

    bundle["metadata"].update({
        "purpose": "utzig_complete_approved_service_knowledge",
        "publication_allowed": True,
        "content_approval": {
            "status": "operator_approved",
            "source_publication_id": AURORA_PUBLICATION_ID,
            "source_publication_checksum": AURORA_CHECKSUM,
            "approved_faq_count": len(added_faqs),
            "enriched_copy_count": len(enriched_copies),
        },
    })
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"faqs_added": len(added_faqs), "copies_enriched": len(enriched_copies)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
