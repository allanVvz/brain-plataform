from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
for path in (API_ROOT, REPO_ROOT / "packages" / "brain-contracts", REPO_ROOT / "packages" / "brain-shared"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services import graph_bundle, graph_editor  # noqa: E402

UTZIG_V17 = REPO_ROOT / "data/graph_bundles/utzig-garage/utzig-concise-closing-v17.json"
OFF = ["condicao", "estrada_de_chao", "evaluation_route", "foco_brilho_riscos",
       "procedimento_anterior", "revestimento_bancos", "vazamento_oleo"]
ADDRESS = "faq:qualification:endereco_cliente"


@lru_cache(maxsize=1)
def _compiled() -> str:
    # The v17 file compiles to the active production checksum (publication 16).
    return json.dumps(graph_bundle.compile_bundle(json.loads(UTZIG_V17.read_text(encoding="utf-8"))))


def _publication() -> dict:
    document = json.loads(_compiled())
    return {"id": "pub-16", "version": 16, "persona_id": document["persona"]["id"],
            "checksum": document["checksum"], "compiler_version": document["compiler_version"],
            "document_json": document}


def _persona(bundle: dict) -> dict:
    return next(node for node in bundle["nodes"] if node["node_type"] == "persona")


def _utzig_acceptance_ops(publication: dict) -> list[dict]:
    base = graph_editor.bundle_from_publication(publication)
    persona = _persona(base)
    ops: list[dict] = [{"op": "update_node", "node_id": persona["id"], "patch": {
        "data.conversation_policy.qualification.question_modes": {key: "disabled" for key in OFF}}}]
    for node in base["nodes"]:
        for section in ("completion", "booking"):
            declared = ((node.get("data") or {}).get(section) or {}).get("required_fields")
            if isinstance(declared, list) and "objective" in declared:
                ops.append({"op": "update_node", "node_id": node["id"], "patch": {
                    f"data.{section}.required_fields": [key for key in declared if key != "objective"]}})
    field = {"key": "endereco_cliente", "required": False, "priority": 0.5, "scope": "persona",
             "depends_on": [], "question_node_id": ADDRESS, "owner_node_id": persona["id"],
             "accepted_statuses": ["known"], "overwrite_policy": "explicit_correction",
             "validation": {"mode": "schema"}, "value_schema": {"type": "string", "minLength": 2},
             "carry_over": True}
    existing = ((persona.get("data") or {}).get("qualification") or {}).get("fields") or []
    return ops + [
        {"op": "add_node", "node": {"id": ADDRESS, "node_type": "faq", "title": "endereço", "data": {
            "role": "qualification_question", "question": "Qual é o seu endereço? Pode ser só o bairro e a cidade."}}},
        {"op": "add_edge", "edge": {"source": "@persona", "target": ADDRESS, "relation_type": "contains"}},
        {"op": "update_node", "node_id": persona["id"], "patch": {"data.qualification.fields": existing + [field]}},
    ]


def test_active_publication_rebuilds_to_the_same_runtime_checksum():
    check = graph_editor.verify_round_trip(_publication())
    assert check["editable"] is True
    assert check["runtime_checksum"] == check["active_checksum"]
    assert not any(check["changes"]["node_changes"].values())


def test_editor_view_uses_compiled_anchors_and_persona_policy():
    view = graph_editor.editor_view(_publication())
    assert view["editable"] is True and view["compiler_upgrade"] is None
    assert len(view["contracts"]) == 11  # branch anchors, not every service with fields
    assert view["persona_node_id"] == "persona:utzig-garage"
    first = view["contracts"][0]
    assert first["path"][0]["node_id"] == "persona:utzig-garage"
    assert all("?" in field["text"] for field in first["fields"])  # every field shows its question
    assert view["persona_policy"]["business_model"] == "appointment"


def test_utzig_acceptance_plan_keeps_only_four_questions_on():
    publication = _publication()
    before = json.dumps(publication, sort_keys=True)
    result = graph_editor.plan(publication, _utzig_acceptance_ops(publication))
    assert json.dumps(publication, sort_keys=True) == before  # dry run, base untouched
    assert result["validation_errors"] == [] and result["publication_allowed"] is True
    assert result["nodes_added"] == 1
    active = {field["key"] for contract in result["contracts"] for field in contract["fields"]
              if field["question_mode"] != "disabled"}
    assert active == {"servico", "modelo_veiculo", "nome_cliente", "endereco_cliente"}
    for contract in result["contracts"]:
        address = next(field for field in contract["fields"] if field["key"] == "endereco_cliente")
        assert address["text"].startswith("Qual é o seu endereço?") and address["required"] is False


def test_disabled_questions_leave_explicit_required_lists():
    publication = _publication()
    persona = _persona(graph_editor.bundle_from_publication(publication))
    edited = graph_editor.apply_operations(graph_editor.bundle_from_publication(publication), [
        {"op": "update_node", "node_id": persona["id"],
         "patch": {"data.conversation_policy.qualification.question_modes": {"condicao": "disabled"}}}])
    lists = [((node.get("data") or {}).get(section) or {}).get("required_fields")
             for node in edited["nodes"] for section in ("completion", "booking")]
    declared = [items for items in lists if isinstance(items, list)]
    assert declared and all("condicao" not in items for items in declared)
    assert any("objective" in items for items in declared)  # undeclared keys are not dropped silently


@pytest.mark.parametrize("operation, error", [
    ({"op": "remove_node", "node_id": "product:ppf"}, "operation_not_supported"),
    ({"op": "update_node", "node_id": "product:ppf", "patch": {"data.public_site.cta": {}}}, "not_editable"),
    ({"op": "update_node", "node_id": "product:ppf",
      "patch": {"data.conversation_policy.qualification.question_modes": {}}}, "only_on_persona"),
    ({"op": "update_node", "node_id": "product:ppf", "patch": {"data.question": "x?"}}, "only_on_question_nodes"),
    ({"op": "update_node", "node_id": "missing", "patch": {"data.question": "x?"}}, "node_not_found"),
    ({"op": "add_node", "node": {"id": "faq:utzig:new", "node_type": "faq", "data": {"question": "x?"}}},
     "only_qualification_questions"),
    ({"op": "add_edge", "edge": {"source": "product:ppf", "target": "faq:x", "relation_type": "contains"}},
     "only_persona_contains_new_question"),
])
def test_editor_refuses_everything_outside_phase_one(operation, error):
    with pytest.raises(graph_editor.GraphEditorError, match=error):
        graph_editor.apply_operations(graph_editor.bundle_from_publication(_publication()), [operation])


class _Rpc:
    def __init__(self, calls):
        self.calls = calls

    def rpc(self, name, params):
        self.calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={"ok": True}))


def _publish_env(monkeypatch, *, fail_activation=False):
    from services import graph_bundle_publisher, supabase_client
    state = {"active": _publication(), "rpc": [], "events": []}
    monkeypatch.setattr(graph_editor, "active_publication", lambda slug: state["active"])
    monkeypatch.setattr(graph_editor, "_published", {})

    def stage(bundle, *, approved_draft_checksum, actor):
        return {"publication": {"id": "pub-17", "version": 17}}

    def activate(bundle, *, publication_id, approved_draft_checksum, approved_runtime_checksum, actor):
        if fail_activation:
            raise graph_bundle_publisher.GraphBundlePublishError("boom")
        state["active"] = {**state["active"], "id": publication_id, "checksum": approved_runtime_checksum}

    monkeypatch.setattr(graph_bundle_publisher, "stage_bundle", stage)
    monkeypatch.setattr(graph_bundle_publisher, "activate_staged_bundle", activate)
    monkeypatch.setattr(supabase_client, "get_client", lambda: _Rpc(state["rpc"]))
    monkeypatch.setattr(supabase_client, "insert_event", lambda event, source=None: state["events"].append(event))
    return state


def _reviewed():
    publication = _publication()
    ops = _utzig_acceptance_ops(publication)
    reviewed = graph_editor.plan(publication, ops)
    return ops, reviewed


def test_publish_only_on_the_active_base_with_the_reviewed_plan(monkeypatch):
    state = _publish_env(monkeypatch)
    ops, reviewed = _reviewed()
    common = dict(persona_slug="utzig-garage", operations=ops, actor="admin-1",
                  draft_checksum=reviewed["draft_checksum"], runtime_checksum=reviewed["runtime_checksum"])
    with pytest.raises(graph_editor.GraphEditorConflict, match="base_not_active"):
        graph_editor.publish(base_publication_id="pub-15", idempotency_key="k-stale-base", **common)
    with pytest.raises(graph_editor.GraphEditorConflict, match="plan_changed"):
        graph_editor.publish(base_publication_id="pub-16", idempotency_key="k-other-plan",
                             **{**common, "runtime_checksum": "sha256:other"})
    result = graph_editor.publish(base_publication_id="pub-16", idempotency_key="k-publish", **common)
    assert result == {"publication_id": "pub-17", "version": 17, "checksum": reviewed["runtime_checksum"],
                      "previous_publication_id": "pub-16"}
    assert [event["event_type"] for event in state["events"]] == ["graph_editor_published"]
    assert state["events"][0]["payload"]["operations"] == ops
    # A double click replays the same answer instead of publishing again.
    assert graph_editor.publish(base_publication_id="pub-16", idempotency_key="k-publish", **common) == result


def test_failed_activation_reactivates_the_previous_publication(monkeypatch):
    from services.graph_bundle_publisher import GraphBundlePublishError
    state = _publish_env(monkeypatch, fail_activation=True)
    ops, reviewed = _reviewed()
    with pytest.raises(GraphBundlePublishError):
        graph_editor.publish(persona_slug="utzig-garage", base_publication_id="pub-16", operations=ops,
                             draft_checksum=reviewed["draft_checksum"], runtime_checksum=reviewed["runtime_checksum"],
                             actor="admin-1", idempotency_key="k-fail")
    assert state["rpc"] == [("activate_graph_publication_v3", {"p_publication_id": "pub-16"})]
    assert state["events"] == []


def test_revert_only_to_the_previous_publication(monkeypatch):
    state = _publish_env(monkeypatch)
    monkeypatch.setattr(graph_editor, "previous_publication", lambda slug, active: {"id": "pub-15", "version": 15})
    with pytest.raises(graph_editor.GraphEditorConflict, match="revert_target_not_previous"):
        graph_editor.revert(persona_slug="utzig-garage", to_publication_id="pub-3", actor="admin-1")
    result = graph_editor.revert(persona_slug="utzig-garage", to_publication_id="pub-15", actor="admin-1")
    assert result["publication_id"] == "pub-15" and result["reverted_from_publication_id"] == "pub-16"
    assert state["rpc"] == [("activate_graph_publication_v3", {"p_publication_id": "pub-15"})]
    assert state["events"][-1]["event_type"] == "graph_editor_reverted"


def _request(role: str, *, can_edit: bool):
    access = [{"persona_id": "p-utzig", "persona_slug": "utzig-garage", "can_view": True,
               "can_edit": can_edit, "can_manage": False}]
    return SimpleNamespace(state=SimpleNamespace(
        user={"id": f"{role}-1", "role": role, "account_type": "internal"}, persona_access=access))


def test_routes_require_edit_to_plan_and_admin_to_publish(monkeypatch):
    from routes import graph_bundles
    body = graph_bundles.EditorPublishBody(persona_slug="utzig-garage", base_publication_id="pub-16",
                                           operations=[{"op": "noop"}], draft_checksum="sha256:aaaaaaaa",
                                           runtime_checksum="sha256:bbbbbbbb", idempotency_key="key-12345")
    with pytest.raises(HTTPException) as viewer:
        graph_bundles.graph_editor_plan(body, _request("operator", can_edit=False))
    assert viewer.value.status_code == 403
    with pytest.raises(HTTPException) as operator:
        graph_bundles.graph_editor_publish(body, _request("operator", can_edit=True))
    assert operator.value.status_code == 403
    with pytest.raises(HTTPException) as foreign:
        graph_bundles.graph_editor_plan(body.model_copy(update={"persona_slug": "tock-fatal"}),
                                        _request("operator", can_edit=True))
    assert foreign.value.status_code == 403
