"""Graph editor: edit the active GraphBundle publication from the AKIA screen.

The SDR reads only the active ``graph_publications`` row. Every edit starts
from that publication: its ``document_json`` already carries the complete
bundle graph (nodes in bundle form, edges plus a compiler-derived ``primary``
flag), so the source bundle is rebuilt from it and checked by recompiling to
the same content before any edit is accepted.

The screen reads a *journey* (stages of the conversation and their questions)
and a *knowledge* index, both built from the compiled document. It writes
semantic *changes*; the server expands them into graph operations (the
``apply_operations`` vocabulary), validates, compiles and publishes in one
call. See akia/docs/architecture/engenharia-de-grafo.md, "Revisão 2026-10-03
(tarde)".
"""
from __future__ import annotations

import copy
import re
from typing import Any

from services import graph_bundle, graph_compiler_v3

BUNDLE_VERSION = "1.0"
EDITOR_SOURCE = "akia_graph_editor"


class GraphEditorError(ValueError):
    """An edit or base that the editor refuses, with a stable code."""


class GraphEditorConflict(GraphEditorError):
    """The base is no longer the active publication."""


def _embedding_profile(document: dict[str, Any]) -> dict[str, Any]:
    manifest = document.get("projection_manifest") or {}
    profile = {
        "embedding_provider": manifest.get("embedding_provider"),
        "embedding_model": manifest.get("embedding_model"),
        "embedding_dimension": manifest.get("embedding_dimension"),
    }
    if not all(profile.values()):
        raise GraphEditorError("base_embedding_profile_missing")
    return profile


def _document(publication: dict[str, Any]) -> dict[str, Any]:
    return publication.get("document_json") or publication.get("document") or {}


def bundle_from_publication(publication: dict[str, Any], *, purpose: str = "") -> dict[str, Any]:
    """Rebuild the source bundle of an active publication.

    ``primary`` on edges is derived by the compiler and is dropped; nodes are
    kept as published (including ``projection_node_id``).
    """
    document = _document(publication)
    persona = document.get("persona") or {}
    if not persona.get("id") or not persona.get("slug"):
        raise GraphEditorError("base_persona_missing")
    nodes = document.get("nodes")
    edges = document.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
        raise GraphEditorError("base_graph_missing")
    return {
        "bundle_version": BUNDLE_VERSION,
        "persona": {"id": str(persona["id"]), "slug": str(persona["slug"])},
        "metadata": {
            "baseline_publication": {
                "publication_id": str(publication.get("id") or ""),
                "version": int(publication.get("version") or 0),
                "checksum": str(publication.get("checksum") or ""),
            },
            "embedding_profile": _embedding_profile(document),
            "internal_wa_validator_test_allowed": False,
            "publication_allowed": True,
            "purpose": purpose or "Edição pelo editor de grafo do AKIA",
            "source": EDITOR_SOURCE,
        },
        "nodes": copy.deepcopy(nodes),
        "edges": [{key: value for key, value in edge.items() if key != "primary"} for edge in edges],
    }


def _base_check(publication: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the bundle and recompile it against the active document."""
    document = _document(publication)
    bundle = bundle_from_publication(publication)
    plan = graph_bundle.build_publication_plan(bundle, current_document=document)
    changes = {key: plan.get(key) for key in ("node_changes", "edge_changes")}
    changed = any((changes[section] or {}).get(kind) for section in ("node_changes", "edge_changes")
                  for kind in ("added", "changed", "removed"))
    errors = list(plan.get("validation_errors") or [])
    published_with = publication.get("compiler_version") or document.get("compiler_version")
    compiler_now = graph_compiler_v3.COMPILER_VERSION
    def version(value):
        matched = re.fullmatch(r"graph-compiler-v(\d+)\.(\d+)\.(\d+)", str(value or ""))
        return tuple(map(int, matched.groups())) if matched else None
    before, after = version(published_with), version(compiler_now)
    upgrade = {"from": published_with, "to": compiler_now} if before and after and before < after else None
    same_checksum = plan.get("runtime_checksum") == publication.get("checksum")
    if not same_checksum and not upgrade:
        errors.append("base_recompile_checksum_mismatch")
    return {
        "bundle": bundle,
        # Editable when the rebuilt bundle carries no content change; a newer
        # compiler alone changes the checksum and is surfaced, not hidden.
        "editable": not errors and not changed,
        "blocked_reasons": errors + (["base_content_changed_on_rebuild"] if changed and not errors else []),
        "validation_errors": errors,
        "runtime_checksum": plan.get("runtime_checksum"),
        "same_checksum": same_checksum, "compiler_upgrade": upgrade,
        "changes": changes,
        "document": plan.get("candidate_document"),
    }


def verify_round_trip(publication: dict[str, Any]) -> dict[str, Any]:
    """Verify stored integrity and unchanged content; expose compiler upgrades."""
    check = _base_check(publication)
    same_checksum = check["runtime_checksum"] == publication.get("checksum")
    return {
        "editable": check["editable"],
        "same_checksum": same_checksum,
        "compiler_upgrade": check["compiler_upgrade"],
        "runtime_checksum": check["runtime_checksum"],
        "active_checksum": publication.get("checksum"),
        "validation_errors": check["validation_errors"],
        "changes": check["changes"],
    }


# ── Journey and knowledge (what the screen reads) ──────────────────────────
# Port of graph-engineering/data/journey_reference.py, the specification that
# produced the frozen fixtures; behavior must stay identical.

_HIDDEN_KNOWLEDGE_TYPES = {"persona", "embedded", "gallery"}
_EDITABLE_KNOWLEDGE_TYPES = {"rule", "tone", "product", "brand", "campaign", "audience", "copy", "faq"}
_CONFIRMATION_DEFAULT = "O agente escreve o resumo com as respostas da lead e pede confirmação antes de encaminhar."
_NAME_KEYS = {"nome_cliente", "nome", "customer_name"}
QUESTION_STAGES = ("identification", "classification", "service")


def _document_persona(document: dict[str, Any]) -> dict[str, Any]:
    return next(node for node in document["nodes"] if node["node_type"] == "persona")


def _document_declarations(document: dict[str, Any]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    result: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for node in document["nodes"]:
        data = node.get("data") or {}
        for field in list(data.get("fields") or []) + list((data.get("qualification") or {}).get("fields") or []):
            if isinstance(field, dict) and field.get("key"):
                result.setdefault(field["key"], []).append((node["id"], field))
    return result


def _knowledge_text(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    question, answer = graph_compiler_v3._faq_question_answer(node) if node.get("node_type") == "faq" else (data.get("question"), data.get("answer"))
    if isinstance(question, str) and isinstance(answer, str) and answer.strip():
        return f"{question.strip()}\n{answer.strip()}"
    if isinstance(question, str) and question.strip():
        return question.strip()
    return str(node.get("summary") or "").strip()


def journey_view(document: dict[str, Any]) -> dict[str, Any]:
    """``{journey, knowledge}`` of a compiled publication document."""
    nodes = {node["id"]: node for node in document["nodes"]}
    persona = _document_persona(document)
    policy = (persona.get("data") or {}).get("conversation_policy") or {}
    common = document.get("common_contract") or {}
    contracts = document.get("branch_contracts") or {}
    coordinates = document.get("coordinates") or {}
    declarations = _document_declarations(document)

    def path_labels(node_id: str) -> list[str]:
        ids = (coordinates.get(node_id) or {}).get("path_node_ids") or [node_id]
        return [nodes[i]["title"] for i in ids if i in nodes and nodes[i]["node_type"] != "persona"]

    anchors = sorted(contracts, key=lambda anchor: " › ".join(path_labels(anchor)))
    branches = [{"branch_node_id": a, "label": nodes[a]["title"], "path": path_labels(a)} for a in anchors]

    # Knowledge index first: questions report how many items are linked.
    by_question: dict[str, list[str]] = {}
    for key, decls in declarations.items():
        qid = next((f.get("question_node_id") for _, f in decls if f.get("question_node_id")), None)
        linked = [n["id"] for n in document["nodes"] if key in ((n.get("data") or {}).get("field_keys") or [])]
        by_question[key] = ([qid] if qid in nodes else []) + linked
    labels = {**(common.get("field_labels") or {})}
    for contract in contracts.values():
        for key, label in (contract.get("field_labels") or {}).items():
            labels.setdefault(key, label)
    texts: dict[str, str] = {}
    for contract in [common, *contracts.values()]:
        for question in (contract.get("questions") or {}).values():
            texts.setdefault(question["field_key"], question.get("text") or "")

    def tracked(key: str) -> bool:
        return any(field.get("tracking") is True for _, field in declarations.get(key, []))

    def question(field: dict[str, Any], *, branch_ids: list[str] | None = None, per_branch=None) -> dict[str, Any]:
        key = field["key"]
        decls = declarations.get(key, [])
        mode = field.get("question_mode") or ("required" if field.get("required") else "optional")
        result = {
            "key": key,
            "label": labels.get(key) or key,
            "text": texts.get(key, ""),
            "question_node_id": field.get("question_node_id"),
            "active": mode != "disabled",
            "essential": bool(field.get("required")),
            "scope": "branches" if branch_ids is not None else "all",
            "tracking": tracked(key),
            "validation_mode": (field.get("validation") or {}).get("mode"),
            "owner_node_ids": sorted({node_id for node_id, _ in decls}),
            "knowledge_count": len(by_question.get(key, [])),
        }
        if branch_ids is not None:
            result["branches"] = branch_ids
            result["per_branch"] = per_branch or {}
        return result

    common_fields = list(common.get("fields") or [])
    selector_field = next((f for f in common_fields if f.get("branch_selection_field")), None)
    general = [f for f in common_fields if f is not selector_field]
    general.sort(key=lambda f: 0 if f["key"] in _NAME_KEYS else 1)  # stable: name first, rest keep compiled order
    identification = [question(f) for f in general if not tracked(f["key"])]
    classification = [question(f) for f in general if tracked(f["key"])]

    common_keys = {f["key"] for f in common_fields}
    specific: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        for field in contracts[anchor].get("fields") or []:
            if field["key"] in common_keys:
                continue
            entry = specific.setdefault(field["key"], {"field": field, "branches": [], "per_branch": {}})
            entry["branches"].append(anchor)
            entry["per_branch"][anchor] = {"essential": bool(field.get("required")),
                "editable": any(not any(owner_id in (contract.get("closure_node_ids") or [])
                    for other, contract in contracts.items() if other != anchor)
                    for owner_id, _ in declarations.get(field["key"], [])
                    if owner_id in (contracts[anchor].get("closure_node_ids") or []))}
    service_questions = sorted(
        (question(v["field"], branch_ids=v["branches"], per_branch=v["per_branch"]) for v in specific.values()),
        key=lambda q: (-len(q["branches"]), q["label"]),
    )

    handoff_rule_ids: list[str] = []
    for contract in contracts.values():
        for node_id in contract.get("handoff_rule_node_ids") or []:
            if node_id not in handoff_rule_ids:
                handoff_rule_ids.append(node_id)
    opening = (policy.get("opening") or {}).get("first_turn")
    closing = (policy.get("post_qualification_support") or {}).get("transition")
    confirmation_rule = next((n for n in document["nodes"] if n.get("node_type") == "rule" and
        ((n.get("data") or {}).get("capabilities") or {}).get("journey_stage") == "confirmation"), None)
    stages = [
        {"key": "opening", "label": "Abertura", "rule_node_id": None,
         "texts": [{"key": "opening", "label": "Primeira mensagem", "value": opening, "editable": True}]
         if isinstance(opening, str) else []},
        {"key": "identification", "label": "Identificação", "rule_node_id": None, "questions": identification},
        {"key": "classification", "label": "Classificação", "rule_node_id": None, "questions": classification,
         "selector": None if selector_field is None else {
             "field_key": selector_field["key"], "question": question(selector_field), "options": branches}},
        {"key": "service", "label": "Perguntas do serviço", "rule_node_id": None,
         "questions": service_questions, "branches": branches},
        {"key": "confirmation", "label": "Confirmação",
         "rule_node_id": confirmation_rule["id"] if confirmation_rule else None,
         "description": _CONFIRMATION_DEFAULT,
         "texts": [{"key": "confirmation", "label": "Resumo e confirmação",
             "value": _knowledge_text(confirmation_rule) if confirmation_rule else _CONFIRMATION_DEFAULT, "editable": True}]},
        {"key": "handoff", "label": "Encaminhamento", "rule_node_id": None,
         "texts": [{"key": "closing", "label": "Encerramento", "value": closing, "editable": True}]
         if isinstance(closing, str) else [],
         "rules": [{"node_id": i, "title": nodes[i]["title"], "text": str(nodes[i].get("summary") or ""), "editable": nodes[i]["node_type"] in _EDITABLE_KNOWLEDGE_TYPES}
                   for i in handoff_rule_ids if i in nodes]},
    ]
    model = "venda" if any(nodes[a]["node_type"] == "audience" for a in anchors) else ("agendamento" if anchors else None)

    memberships = document.get("branch_memberships") or {}
    used = set()
    for contract in contracts.values():
        used.update(contract.get("eligible_faq_node_ids") or [])
        used.update(f.get("question_node_id") for f in contract.get("fields") or [] if f.get("question_node_id"))
    knowledge_nodes = [{
        "id": node["id"], "node_type": node["node_type"], "title": node["title"],
        "status": node.get("status") or "", "text": _knowledge_text(node),
        "editable": node["node_type"] in _EDITABLE_KNOWLEDGE_TYPES, "path": path_labels(node["id"]),
        "branch_node_ids": [a for a in anchors if node["id"] in (memberships.get(a) or {})],
        "used_by_sdr": node["id"] in used,
    } for node in document["nodes"] if node["node_type"] not in _HIDDEN_KNOWLEDGE_TYPES]
    knowledge = {
        "nodes": knowledge_nodes,
        "by_branch": {a: list(contracts[a].get("eligible_faq_node_ids") or []) for a in anchors},
        "by_question": by_question,
        "by_stage": {"opening": [], "confirmation": [confirmation_rule["id"]] if confirmation_rule else [], "handoff": handoff_rule_ids},
    }
    return {"journey": {"model": model, "branch_count": len(anchors), "stages": stages}, "knowledge": knowledge}


def _stage(journey: dict[str, Any], key: str) -> dict[str, Any]:
    return next(stage for stage in journey["stages"] if stage["key"] == key)


# ── Operations (the only graph writes the editor makes) ────────────────────


def _persona_node(bundle: dict[str, Any]) -> dict[str, Any]:
    persona = next((node for node in bundle["nodes"] if node.get("node_type") == "persona"), None)
    if persona is None:
        raise GraphEditorError("base_persona_node_missing")
    return persona
