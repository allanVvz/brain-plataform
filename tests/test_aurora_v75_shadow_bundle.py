from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts import build_aurora_shadow_bundle_from_v75 as builder  # noqa: E402


def test_importer_rejects_any_non_v75_or_fixture_baseline() -> None:
    with pytest.raises(ValueError, match="not the audited active Aurora v75"):
        builder._read_snapshot(
            {
                "publication": {
                    "version": 66,
                    "checksum": "sha256:fixture",
                },
                "document": {},
            }
        )


def test_shadow_builder_changes_only_persona_tone_and_rule(monkeypatch) -> None:
    publication = {
        "version": 75,
        "checksum": builder.ACTIVE_V75_CHECKSUM,
        "persona_id": "persona-aurora",
        "persona_slug": "aurora",
        "compiler_version": "graph-compiler-v3.6.3",
    }
    document = {
        "persona": {"id": "persona-aurora", "slug": "aurora"},
        "nodes": [
            {
                "id": "persona:aurora",
                "node_type": "persona",
                "slug": "aurora",
                "title": "Aurora",
                "summary": "Persona Aurora.",
                "status": "validated",
                "data": {
                    "source": "active-v75",
                    "status": "validated",
                    "conversation_policy": {
                        "mandatory_question_sequence": ["nome", "servico"],
                    },
                },
            },
            {
                "id": "tone:aurora",
                "node_type": "tone",
                "slug": "tom-aurora",
                "title": "Tom Aurora",
                "summary": "Tom publicado.",
                "status": "validated",
                "data": {
                    "source": "active-v75",
                    "status": "validated",
                    "guidelines": ["Quem pergunta controla a conversa.", "Seja clara."],
                },
            },
            {
                "id": "rule:aurora",
                "node_type": "rule",
                "slug": "regra-aurora",
                "title": "Regra Aurora",
                "summary": "Regra publicada.",
                "status": "validated",
                "data": {"source": "active-v75", "status": "validated"},
            },
            {
                "id": "faq:chapeacao",
                "node_type": "faq",
                "slug": "chapeacao",
                "title": "Chapeação",
                "summary": "Explicação publicada.",
                "status": "validated",
                "data": {"source": "active-v75", "status": "validated"},
            },
        ],
        "edges": [
            {
                "id": "edge:persona-tone",
                "source": "persona:aurora",
                "target": "tone:aurora",
                "relation_type": "contains",
            }
        ],
    }
    original_faq = copy.deepcopy(document["nodes"][3])
    monkeypatch.setattr(builder, "_read_snapshot", lambda _snapshot: (publication, document))

    bundle = builder.build(
        {
            "embedding_profile": {
                "embedding_provider": "local",
                "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                "embedding_dimension": 1536,
            }
        }
    )

    assert len(bundle["nodes"]) == len(document["nodes"])
    assert len(bundle["edges"]) == len(document["edges"])
    assert bundle["metadata"]["shadow_only"] is True
    assert bundle["metadata"]["publication_allowed"] is False
    assert bundle["metadata"]["activation_allowed"] is False

    by_id = {node["id"]: node for node in bundle["nodes"]}
    assert by_id["faq:chapeacao"] == original_faq
    assert by_id["persona:aurora"]["data"]["source"] == "active-v75"
    assert "mandatory_question_sequence" not in by_id["persona:aurora"]["data"]["conversation_policy"]
    assert by_id["persona:aurora"]["data"]["conversation_policy"]["question_policy"]["force_question"] is False
    assert by_id["tone:aurora"]["data"]["guidelines"][0] == "Seja clara."
    assert by_id["rule:aurora"]["data"]["model_conversation_policy"]["production_enforcement"] == "telemetry_only"
