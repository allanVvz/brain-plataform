from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import graph_bundle, graph_bundle_active_adapter


PERSONA_ID = "4acb2739-127e-4143-acf5-f5c3ea1aaa98"
PERSONA_SLUG = "adapter-test"


def _bundle() -> dict:
    return {
        "bundle_version": "1.0",
        "persona": {"id": PERSONA_ID, "slug": PERSONA_SLUG},
        "metadata": {
            "embedding_profile": {
                "embedding_provider": "local",
                "embedding_model": (
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                ),
                "embedding_dimension": 1536,
            },
        },
        "nodes": [
            {
                "id": f"persona:{PERSONA_SLUG}",
                "node_type": "persona",
                "slug": PERSONA_SLUG,
                "title": "Adapter Test",
                "summary": "Persona de teste.",
                "status": "validated",
                "data": {"source": "test"},
            },
            {
                "id": "audience:retail",
                "node_type": "audience",
                "slug": "retail",
                "title": "Retail",
                "summary": "Ramo de varejo.",
                "status": "validated",
                "data": {
                    "source": "test",
                    "capabilities": {"branch_anchor": True},
                },
            },
        ],
        "edges": [{
            "id": "edge:persona:audience",
            "source": f"persona:{PERSONA_SLUG}",
            "target": "audience:retail",
            "relation_type": "contains",
            "weight": 1.0,
            "metadata": {},
        }],
    }


def test_active_document_roundtrip_preserves_runtime_checksum():
    document = graph_bundle.compile_bundle(_bundle())
    draft = graph_bundle_active_adapter.active_document_to_draft(
        document,
        expected_persona_slug=PERSONA_SLUG,
        expected_runtime_checksum=document["checksum"],
    )
    assert draft["metadata"]["base_runtime_checksum"] == document["checksum"]
    assert graph_bundle.compile_bundle(draft)["checksum"] == document["checksum"]


def test_active_document_rejects_tampering_and_cross_persona_access():
    document = graph_bundle.compile_bundle(_bundle())
    tampered = deepcopy(document)
    tampered["nodes"][0]["title"] = "Alterado depois da compilacao"
    with pytest.raises(
        graph_bundle_active_adapter.ActivePublicationAdapterError,
        match="checksum_invalid",
    ):
        graph_bundle_active_adapter.active_document_to_draft(
            tampered,
            expected_persona_slug=PERSONA_SLUG,
        )

    with pytest.raises(
        graph_bundle_active_adapter.ActivePublicationAdapterError,
        match="persona_mismatch",
    ):
        graph_bundle_active_adapter.active_document_to_draft(
            document,
            expected_persona_slug="outra-persona",
        )
