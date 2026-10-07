from __future__ import annotations

import copy
import json
import re
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

FIXTURES = Path(__file__).resolve().parent / "fixtures"
UTZIG_V17 = REPO_ROOT / "data/graph_bundles/utzig-garage/utzig-concise-closing-v17.json"
PERSONA = "persona:utzig-garage"
MODES = "data.conversation_policy.qualification.question_modes"
FIELDS = "data.qualification.fields"
OFF = ["condicao", "estrada_de_chao", "evaluation_route", "foco_brilho_riscos",
       "procedimento_anterior", "revestimento_bancos", "vazamento_oleo"]
ADDRESS_TEXT = "Qual é o seu endereço? Pode ser só o bairro e a cidade."
ADD_ADDRESS = {"type": "add_question", "stage": "identification", "label": "endereço",
               "text": ADDRESS_TEXT, "essential": False}
ACCEPTANCE = [{"type": "set_question", "key": key, "active": False} for key in OFF] + [ADD_ADDRESS]


@lru_cache(maxsize=1)
def _compiled() -> str:
    # The v17 file compiles to the active production checksum (publication 16).
    return json.dumps(graph_bundle.compile_bundle(json.loads(UTZIG_V17.read_text(encoding="utf-8"))))


def _publication() -> dict:
    document = json.loads(_compiled())
    return {"id": "pub-16", "version": 16, "persona_id": document["persona"]["id"],
            "checksum": document["checksum"], "compiler_version": document["compiler_version"],
            "document_json": document}


def _base() -> dict:
    return graph_editor.bundle_from_publication(_publication())


def _declarations_for_bundle(bundle):
    return {n["id"]: (n.get("data", {}).get("fields"), n.get("data", {}).get("qualification")) for n in bundle["nodes"] if n["id"] != "rule:journey:confirmation"}


def _legacy_journey(journey):
    journey = copy.deepcopy(journey)
    for stage in journey["stages"]:
        if stage["key"] == "confirmation":
            stage.pop("texts", None)
        for question in stage.get("questions", []):
            for settings in question.get("per_branch", {}).values():
                settings.pop("editable", None)
        for rule in stage.get("rules", []):
            rule.pop("editable", None)
    return journey


def _redact(value):
    # Same redaction as the fixtures: money values never reach the repository.
    return json.loads(re.sub(r"R\$ ?[\d.,]*\d", "R$ (removido)", json.dumps(value, ensure_ascii=False)))


def _expand(changes: list[dict], bundle: dict | None = None) -> tuple[list[dict], dict, dict]:
    """(operations, edited bundle, journey of the recompiled bundle)."""
    bundle = bundle or _base()
    operations = graph_editor.expand_changes(bundle, changes)
    edited = graph_editor.apply_operations(bundle, operations)
    return operations, edited, graph_editor.journey_view(graph_bundle.compile_bundle(edited))["journey"]


def _stage(journey: dict, key: str) -> dict:
    return next(stage for stage in journey["stages"] if stage["key"] == key)


def _keys(journey: dict, stage: str) -> list[str]:
    return [question["key"] for question in _stage(journey, stage)["questions"]]


def _question(journey: dict, key: str) -> dict:
    return next(question for stage in journey["stages"] for question in stage.get("questions") or []
                if question["key"] == key)


def _declarations(bundle: dict, key: str) -> dict[str, dict]:
    return {node["id"]: field for node in bundle["nodes"]
            for field in ((node.get("data") or {}).get("qualification") or {}).get("fields") or []
            if field.get("key") == key}


def _persona(bundle: dict) -> dict:
    return next(node for node in bundle["nodes"] if node["node_type"] == "persona")


def _refused(changes: list[dict], code: str, bundle: dict | None = None) -> None:
    with pytest.raises(graph_editor.GraphEditorError, match=f"^{code}"):
        graph_editor.expand_changes(bundle or _base(), changes)


# ── Read side: journey and knowledge ───────────────────────────────────────

def test_active_publication_rebuilds_to_the_same_runtime_checksum():
    check = graph_editor.verify_round_trip(_publication())
    assert check["editable"] is True
    assert check["runtime_checksum"] == check["active_checksum"]
    assert not any(check["changes"]["node_changes"].values())


def test_journey_reproduces_the_frozen_utzig_fixture():
    view = graph_editor.journey_view(_publication()["document_json"])
    fixture = json.loads((FIXTURES / "editor-journey-utzig.json").read_text(encoding="utf-8"))
    assert _legacy_journey(_redact(view["journey"])) == fixture["journey"]
    # Knowledge: same nodes and indexes; node text is redacted in the fixture.
    without_text = lambda nodes: [{key: value for key, value in node.items() if key not in {"text", "editable"}} for node in nodes]  # noqa: E731
    assert without_text(view["knowledge"]["nodes"]) == without_text(fixture["knowledge"]["nodes"])
    for index in ("by_branch", "by_question", "by_stage"):
        assert view["knowledge"][index] == fixture["knowledge"][index]


def test_editor_view_serves_the_journey_instead_of_the_bundle():
    view = graph_editor.editor_view(_publication())
    assert set(view) == {"publication", "editable", "blocked_reasons", "compiler_upgrade",
                         "persona_node_id", "journey", "knowledge"}
    assert view["editable"] is True and view["blocked_reasons"] == [] and view["compiler_upgrade"] is None
    assert view["persona_node_id"] == PERSONA
    assert view["journey"]["model"] == "agendamento" and view["journey"]["branch_count"] == 11
    assert _stage(view["journey"], "classification")["selector"]["field_key"] == "servico"


def test_tock_journey_selects_the_path_by_purchase_profile():
    # Trimmed copy of the exported production publication (see "_source").
    fixture = json.loads((FIXTURES / "editor-document-tock.json").read_text(encoding="utf-8"))
    journey = graph_editor.journey_view(fixture["document"])["journey"]
    assert _legacy_journey(journey) == fixture["journey"]
    assert journey["model"] == "venda" and journey["branch_count"] == 2
    selector = _stage(journey, "classification")["selector"]
    assert selector["field_key"] == "purchase_profile"
    assert [option["branch_node_id"] for option in selector["options"]] == ["audience:tock-reseller", "audience:tock-retail"]
    assert _keys(journey, "identification")[0] == "nome_cliente"
    assert len(_stage(journey, "service")["branches"]) == 2


# ── Changes → operations ───────────────────────────────────────────────────

def test_set_question_active_writes_only_the_persona_question_modes():
    operations, edited, journey = _expand([{"type": "set_question", "key": "condicao", "active": False}])
    assert operations == [{"op": "update_node", "node_id": PERSONA, "patch": {MODES: {"condicao": "disabled"}}}]
    assert _question(journey, "condicao")["active"] is False
    # Turning one back on keeps the other keys of the map.
    operations, _, journey = _expand([
        {"type": "set_question", "key": "vazamento_oleo", "active": False},
        {"type": "set_question", "key": "condicao", "active": True},
    ], bundle=edited)
    assert operations[-1]["patch"] == {MODES: {"vazamento_oleo": "disabled"}}
    assert _question(journey, "condicao")["active"] is True
    assert _question(journey, "vazamento_oleo")["active"] is False


def test_set_question_active_also_reads_the_appointment_question_modes():
    bundle = _base()
    _persona(bundle)["data"]["appointment_policy"]["question_modes"] = {"condicao": "disabled"}
    # Already off through the appointment map: nothing to write.
    assert graph_editor.expand_changes(bundle, [{"type": "set_question", "key": "condicao", "active": False}]) == []
    operations, _, journey = _expand([{"type": "set_question", "key": "condicao", "active": True}], bundle=bundle)
    assert operations == [{"op": "update_node", "node_id": PERSONA,
                           "patch": {"data.appointment_policy.question_modes": {}}}]
    assert _question(journey, "condicao")["active"] is True


def test_essential_on_every_path_changes_every_declaration_and_keeps_owners():
    base = _base()
    owners = {node_id: field["owner_node_id"] for node_id, field in _declarations(base, "condicao").items()}
    _, edited, journey = _expand([{"type": "set_question", "key": "condicao", "essential": False}], bundle=base)
    after = _declarations(edited, "condicao")
    assert {node_id: field["owner_node_id"] for node_id, field in after.items()} == owners
    assert len(after) == 10 and all(field["required"] is False for field in after.values())
    per_branch = _question(journey, "condicao")["per_branch"]
    assert len(per_branch) == 7 and all(value["essential"] is False for value in per_branch.values())


def test_essential_on_one_path_changes_only_that_declaration():
    operations, edited, journey = _expand([
        {"type": "set_question", "key": "condicao", "essential": False, "branch_node_id": "product:ppf"}])
    assert [operation["node_id"] for operation in operations] == ["product:ppf"]
    assert _declarations(edited, "condicao")["product:ppf"]["owner_node_id"] == "product:ppf"
    per_branch = _question(journey, "condicao")["per_branch"]
    assert per_branch.pop("product:ppf")["essential"] is False
    assert all(value["essential"] is True for value in per_branch.values())


def test_essential_folds_an_explicit_question_mode_into_the_declarations():
    bundle = _base()
    _persona(bundle)["data"]["conversation_policy"]["qualification"]["question_modes"] = {"condicao": "optional"}
    operations, edited, journey = _expand([
        {"type": "set_question", "key": "condicao", "essential": True, "branch_node_id": "product:ppf"}], bundle=bundle)
    assert operations[0] == {"op": "update_node", "node_id": PERSONA, "patch": {MODES: {}}}
    assert _declarations(edited, "condicao")["product:ppf"]["required"] is True
    per_branch = _question(journey, "condicao")["per_branch"]
    assert per_branch.pop("product:ppf")["essential"] is True
    assert all(value["essential"] is False for value in per_branch.values())  # "optional" kept elsewhere


def test_essential_on_one_path_refuses_a_question_every_path_shares():
    _, edited, _ = _expand([ADD_ADDRESS])
    _refused([{"type": "set_question", "key": "endereco", "essential": True, "branch_node_id": "product:ppf"}],
             "essential_branch_shared", bundle=edited)
    _refused([{"type": "set_question", "key": "condicao", "essential": True, "branch_node_id": "product:nope"}],
             "essential_branch_unknown")


def test_tracking_moves_a_common_question_to_classification():
    _, edited, journey = _expand([{"type": "set_question", "key": "modelo_veiculo", "tracking": True}])
    assert all(field["tracking"] is True for field in _declarations(edited, "modelo_veiculo").values())
    assert "modelo_veiculo" in _keys(journey, "classification")
    assert "modelo_veiculo" not in _keys(journey, "identification")
    _, back, journey = _expand([{"type": "set_question", "key": "modelo_veiculo", "tracking": False}], bundle=edited)
    assert all(field["tracking"] is False for field in _declarations(back, "modelo_veiculo").values())
    assert _keys(journey, "identification") == ["nome_cliente", "modelo_veiculo"]


def test_set_question_text_edits_the_question_node():
    text = "Como está o carro nessa área hoje?"
    operations, _, journey = _expand([{"type": "set_question", "key": "condicao", "text": text}])
    assert operations == [{"op": "update_node", "node_id": "faq:qualification:condicao",
                           "patch": {"data.question": text}}]
    assert _question(journey, "condicao")["text"] == text
    # Several attributes in one change expand one after the other.
    operations, _, journey = _expand([{"type": "set_question", "key": "condicao", "active": False, "text": text}])
    assert [operation["node_id"] for operation in operations] == [PERSONA, "faq:qualification:condicao"]
    assert _question(journey, "condicao")["active"] is False
    _refused([{"type": "set_question", "key": "condicao", "text": "  "}], "question_text_invalid")
    _refused([{"type": "set_question", "key": "condicao", "active": "no"}], "change_value_invalid")
    _refused([{"type": "set_question", "key": "nada", "text": "Oi?"}], "question_not_found")
    _refused([{"type": "set_question", "key": "condicao"}], "set_question_without_change")


def test_add_question_for_identification_declares_on_the_persona():
    operations, edited, journey = _expand([ADD_ADDRESS])
    assert operations[0]["op"] == "add_node" and operations[0]["node"]["id"] == "faq:qualification:endereco"
    assert operations[1]["edge"] == {"source": PERSONA, "target": "faq:qualification:endereco",
                                     "relation_type": "contains"}
    field = _declarations(edited, "endereco")[PERSONA]
    assert field == {
        "key": "endereco", "required": False, "priority": 0.7, "scope": "persona", "owner_node_id": PERSONA,
        "question_node_id": "faq:qualification:endereco", "depends_on": [], "accepted_statuses": ["known"],
        "overwrite_policy": "explicit_correction", "validation": {"mode": "schema"},
        "value_schema": {"type": "string", "minLength": 1}, "tracking": False,
    }
    assert _keys(journey, "identification") == ["nome_cliente", "modelo_veiculo", "endereco"]
    question = _question(journey, "endereco")
    assert (question["label"], question["text"], question["essential"], question["knowledge_count"]) == (
        "endereço", ADDRESS_TEXT, False, 1)
    assert question["owner_node_ids"] == [PERSONA]


def test_add_question_for_classification_is_tracked():
    _, edited, journey = _expand([{"type": "add_question", "stage": "classification", "label": "Campanha",
                                   "text": "Por onde você conheceu a Utzig?", "essential": False}])
    assert _declarations(edited, "campanha")[PERSONA]["tracking"] is True
    assert _keys(journey, "classification") == ["campanha"]


def test_add_question_for_service_declares_on_each_chosen_path():
    change = {"type": "add_question", "stage": "service", "label": "Cor do veículo", "text": "Qual é a cor do carro?",
              "essential": True, "branch_node_ids": ["product:ppf", "product:vitrification"]}
    _, edited, journey = _expand([change])
    declarations = _declarations(edited, "cor_do_veiculo")
    assert {node_id: (field["scope"], field["owner_node_id"]) for node_id, field in declarations.items()} == {
        "product:ppf": ("branch", "product:ppf"), "product:vitrification": ("branch", "product:vitrification")}
    question = _question(journey, "cor_do_veiculo")
    assert sorted(question["branches"]) == ["product:ppf", "product:vitrification"]
    assert question["per_branch"] == {"product:ppf": {"essential": True, "editable": True}, "product:vitrification": {"essential": True, "editable": True}}
    _refused([{**change, "branch_node_ids": []}], "add_question_branches_required")
    _refused([{**change, "branch_node_ids": ["product:nope"]}], "add_question_branch_unknown")


def test_add_question_key_is_a_unique_ascii_slug():
    operations, _, _ = _expand([
        {"type": "add_question", "stage": "identification", "label": "Nome cliente", "text": "Nome?", "essential": False},
        {"type": "add_question", "stage": "identification", "label": "objective", "text": "Objetivo?", "essential": False},
    ])
    added = [operation["node"]["id"] for operation in operations if operation["op"] == "add_node"]
    # nome_cliente is a declared field; faq:qualification:objective already exists.
    assert added == ["faq:qualification:nome_cliente_2", "faq:qualification:objective_2"]
    _refused([{**ADD_ADDRESS, "label": "???"}], "add_question_label_invalid")
    _refused([{**ADD_ADDRESS, "stage": "handoff"}], "add_question_stage_invalid")


def test_move_question_swaps_with_its_neighbour_through_priority():
    _, edited, journey = _expand([ADD_ADDRESS, {"type": "move_question", "stage": "identification",
                                                "key": "endereco", "direction": -1}])
    assert _keys(journey, "identification") == ["nome_cliente", "endereco", "modelo_veiculo"]
    # Coherent priority on every declaration of the stage.
    assert {field["priority"] for field in _declarations(edited, "modelo_veiculo").values()} == {0.7}
    assert {field["priority"] for field in _declarations(edited, "endereco").values()} == {0.8}


def test_move_question_is_refused_when_the_compiler_would_not_honor_it():
    _, edited, _ = _expand([ADD_ADDRESS])
    move = {"type": "move_question", "stage": "identification"}
    # The name always comes first in the journey.
    _refused([{**move, "key": "modelo_veiculo", "direction": -1}], "move_not_honored", bundle=edited)
    _refused([{**move, "key": "endereco", "direction": 1}], "move_out_of_range", bundle=edited)
    _refused([{**move, "key": "condicao", "direction": -1}], "move_question_not_in_stage", bundle=edited)
    _refused([{**move, "stage": "service", "key": "condicao", "direction": -1}], "move_service_order_fixed")


def test_set_text_edits_opening_and_closing_on_the_persona():
    operations, edited, journey = _expand([
        {"type": "set_text", "key": "opening", "value": "Apresente-se como assistente da Utzig."},
        {"type": "set_text", "key": "closing", "value": "Diga que o Wilian continua o atendimento."},
    ])
    assert [operation["node_id"] for operation in operations] == [PERSONA, PERSONA]
    policy = _persona(edited)["data"]["conversation_policy"]
    assert policy["opening"]["first_turn"] == "Apresente-se como assistente da Utzig."
    assert _stage(journey, "handoff")["texts"][0]["value"] == "Diga que o Wilian continua o atendimento."
    _refused([{"type": "set_text", "key": "summary", "value": "x"}], "text_key_invalid")
    _refused([{"type": "set_text", "key": "opening", "value": ""}], "text_invalid")


def test_unknown_change_types_are_refused_with_a_readable_error():
    _refused([{"type": "remove_question", "key": "condicao"}], "change_not_supported")
    with pytest.raises(graph_editor.GraphEditorRejected) as refused:
        graph_editor.plan_changes(_publication(), [{"type": "remove_question", "key": "condicao"}])
    assert refused.value.errors == [{"code": "change_not_supported",
                                     "message": "Tipo de alteração desconhecido (remove_question)."}]


def test_fields_need_a_validation_mode_and_keep_their_owner():
    base = _base()
    ppf = next(node for node in base["nodes"] if node["id"] == "product:ppf")
    fields = copy.deepcopy(ppf["data"]["qualification"]["fields"])
    no_mode = [{**field, "validation": {}, "value_schema": {}} if field["key"] == "condicao" else field for field in fields]
    with pytest.raises(graph_editor.GraphEditorError, match="field_validation_mode_missing"):
        graph_editor.apply_operations(base, [{"op": "update_node", "node_id": "product:ppf", "patch": {FIELDS: no_mode}}])
    moved = [{**field, "owner_node_id": PERSONA} if field["key"] == "condicao" else field for field in fields]
    with pytest.raises(graph_editor.GraphEditorError, match="field_owner_change_refused"):
        graph_editor.apply_operations(base, [{"op": "update_node", "node_id": "product:ppf", "patch": {FIELDS: moved}}])


@pytest.mark.parametrize("operation, error", [
    ({"op": "remove_node", "node_id": "product:ppf"}, "operation_not_supported"),
    ({"op": "update_node", "node_id": "product:ppf", "patch": {"data.public_site.cta": {}}}, "not_editable"),
    ({"op": "update_node", "node_id": "product:ppf", "patch": {MODES: {}}}, "only_on_persona"),
    ({"op": "update_node", "node_id": "product:ppf",
      "patch": {"data.conversation_policy.opening.first_turn": "Oi"}}, "only_on_persona"),
    ({"op": "update_node", "node_id": "product:ppf", "patch": {"data.question": "x?"}}, "only_on_question_nodes"),
    ({"op": "update_node", "node_id": "missing", "patch": {"data.question": "x?"}}, "node_not_found"),
    ({"op": "add_node", "node": {"id": "faq:utzig:new", "node_type": "faq", "data": {"question": "x?"}}},
     "only_qualification_questions"),
    ({"op": "add_edge", "edge": {"source": "product:ppf", "target": "faq:x", "relation_type": "contains"}},
     "only_persona_contains_new_question"),
])
def test_operations_outside_the_editor_vocabulary_are_refused(operation, error):
    with pytest.raises(graph_editor.GraphEditorError, match=error):
        graph_editor.apply_operations(_base(), [operation])


def test_required_lists_only_name_declared_questions_that_are_on():
    edited = graph_editor.apply_operations(_base(), [
        {"op": "update_node", "node_id": PERSONA, "patch": {MODES: {"condicao": "disabled"}}}])
    lists = [((node.get("data") or {}).get(section) or {}).get("required_fields")
             for node in edited["nodes"] for section in ("completion", "booking")]
    declared = [items for items in lists if isinstance(items, list)]
    assert declared and all("condicao" not in items for items in declared)
    # "objective" has a question node but no declared field: it can never be
    # collected, so it leaves the lists the model reads.
    assert all("objective" not in items for items in declared)
    assert any("servico" in items for items in declared)


def test_compiler_errors_become_plain_portuguese_messages():
    labels = {"condicao": "condição atual", "endereco": "endereço"}
    errors = graph_editor.readable_errors([
        "question_mode_field_not_declared:vehicle_color",
        "field_question_empty:product:ppf:endereco:faq:qualification:endereco",
        "field_question_empty:product:vitrification:endereco:faq:qualification:endereco",  # same problem, other path
        "field_validation_mode_missing:product:ppf:condicao",
        "ambiguous_field_declaration:product:ppf:condicao",
        "product:ppf:field_dependency_missing:condicao:servico",
        "product:ppf:field_dependency_cycle:condicao",
        "bundle_node_status_conflict:faq:x",
    ], labels)
    assert [item["code"] for item in errors] == [
        "question_mode_field_not_declared", "field_question_empty", "field_validation_mode_missing",
        "ambiguous_field_declaration", "field_dependency_missing", "field_dependency_cycle", "bundle_node_status_conflict"]
    assert errors[1]["message"] == "A pergunta “endereço” está sem texto. Escreva a pergunta antes de salvar."
    assert "“condição atual”" in errors[4]["message"]
    assert errors[-1]["message"] == "O grafo recusou a alteração (bundle_node_status_conflict)."


def test_utzig_acceptance_keeps_only_service_vehicle_name_and_address_active():
    publication = _publication()
    before = json.dumps(publication, sort_keys=True)
    result = graph_editor.plan_changes(publication, ACCEPTANCE)
    assert json.dumps(publication, sort_keys=True) == before  # dry run, base untouched
    assert result["validation_errors"] == [] and result["publication_allowed"] is True
    assert result["nodes_added"] == 1 and len(result["branches_affected"]) == 11
    journey = result["journey"]
    active = {question["key"] for stage in journey["stages"] for question in stage.get("questions") or []
              if question["active"]}
    active |= {stage["selector"]["field_key"] for stage in journey["stages"]
               if stage.get("selector") and stage["selector"]["question"]["active"]}
    assert active == {"servico", "modelo_veiculo", "nome_cliente", "endereco"}
    assert _keys(journey, "identification") == ["nome_cliente", "modelo_veiculo", "endereco"]
    lists = [((node.get("data") or {}).get(section) or {}).get("required_fields")
             for node in result["bundle"]["nodes"] for section in ("completion", "booking")]
    assert {key for items in lists if isinstance(items, list) for key in items} <= {"servico", "modelo_veiculo"}


# ── Save, revert and routes ────────────────────────────────────────────────

class _RpcFailure(Exception):
    code = "40001"
    def __init__(self, message):
        self.message = message


class _Rpc:
    """Shared persisted-state double, independent of Python editor instances."""
    def __init__(self, state, *, fail_activation=False):
        self.state, self.fail_activation = state, fail_activation

    def rpc(self, name, params):
        self.state["rpc"].append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.execute(name, params)))

    def execute(self, name, p):
        with self.state["db_lock"]:
            key = (p["p_persona_id"], p.get("p_idempotency_key"))
            receipt = self.state["receipts"].get(key)
            fingerprint = tuple(p.get(field) for field in
                                ("p_actor", "p_operation", "p_base_publication_id", "p_request_hash"))
            if name in {"graph_editor_receipt_v1", "commit_graph_editor_v1"} and receipt:
                if receipt[0] != fingerprint:
                    raise _RpcFailure("graph_editor_idempotency_conflict")
                return copy.deepcopy(receipt[1])
            if name == "graph_editor_receipt_v1":
                return None
            if name == "commit_graph_editor_v1":
                if p["p_base_publication_id"] != self.state["active"]["id"]:
                    raise _RpcFailure("graph_editor_base_not_active")
                if self.fail_activation:
                    raise RuntimeError("FAQ projection gate refused activation")
                base = self.state["active"]["id"]
                self.state["active"] = {**self.state["active"], "id": p["p_publication_id"],
                                        "checksum": p["p_runtime_checksum"]}
                self.state["activated"].append(p["p_runtime_checksum"])
                result = {"version": 17, "publication_id": p["p_publication_id"],
                          ("previous_publication_id" if p["p_operation"] == "save"
                           else "reverted_from_publication_id"): base}
                self.state["receipts"][key] = (fingerprint, copy.deepcopy(result))
                self.state["events"].append({"event_type": "graph_editor_committed", "payload": {
                    **p.get("p_audit", {}), "actor": p["p_actor"], "result": result}})
                if self.state.get("lose_reply"):
                    self.state["lose_reply"] = False
                    raise TimeoutError("committed response lost")
                return result
            raise AssertionError(f"unexpected RPC {name}")


def _save_env(monkeypatch, *, fail_activation=False):
    import threading
    from services import graph_bundle_publisher, supabase_client
    state = {"active": _publication(), "rpc": [], "events": [], "staged": [], "activated": [],
             "receipts": {}, "db_lock": threading.Lock()}
    monkeypatch.setattr(graph_editor, "active_publication", lambda slug: state["active"])
    monkeypatch.setattr(supabase_client, "get_persona", lambda slug: {"id": _publication()["persona_id"]})

    def stage(bundle, *, approved_draft_checksum, actor):
        state["staged"].append(approved_draft_checksum)
        return {"publication": {"id": "pub-17", "version": 17}}

    monkeypatch.setattr(graph_bundle_publisher, "stage_bundle", stage)
    monkeypatch.setattr(supabase_client, "get_client", lambda: _Rpc(state, fail_activation=fail_activation))
    return state


def _save(**overrides):
    return graph_editor.save(**{"persona_slug": "utzig-garage", "base_publication_id": "pub-16",
                                "changes": ACCEPTANCE, "actor": "admin-1", "idempotency_key": "k-save", **overrides})


def test_save_publishes_on_the_active_base_with_server_checksums(monkeypatch):
    state = _save_env(monkeypatch)
    reviewed = graph_editor.plan_changes(_publication(), ACCEPTANCE)
    result = _save()
    assert result == {"version": 17, "publication_id": "pub-17", "previous_publication_id": "pub-16"}
    assert state["staged"] == [reviewed["draft_checksum"]]
    assert state["activated"] == [reviewed["runtime_checksum"]]
    assert [event["event_type"] for event in state["events"]] == ["graph_editor_committed"]
    payload = state["events"][0]["payload"]
    assert payload["actor"] == "admin-1" and payload["changes"] == ACCEPTANCE
    # A double click replays the same answer instead of publishing again.
    assert _save() == result
    assert len(state["staged"]) == 1


def test_save_refuses_a_base_that_is_no_longer_active(monkeypatch):
    state = _save_env(monkeypatch)
    with pytest.raises(graph_editor.GraphEditorConflict, match="base_not_active"):
        _save(base_publication_id="pub-15")
    assert state["staged"] == []


def test_failed_activation_never_compensates_over_another_writers_publication(monkeypatch):
    state = _save_env(monkeypatch, fail_activation=True)
    with pytest.raises(graph_editor.GraphEditorOutcomeUnknown):
        _save(idempotency_key="k-fail")
    assert state["active"]["id"] == "pub-16"
    assert not any(name == "activate_graph_publication_v3" for name, _ in state["rpc"])
    assert state["events"] == [] and state["receipts"] == {}


@pytest.mark.parametrize("overrides", [
    {"actor": "other-admin"}, {"base_publication_id": "pub-15"},
    {"changes": [{"type": "set_question", "key": "condicao", "active": False}]},
])
def test_durable_key_cannot_be_reused_for_another_actor_base_or_body(monkeypatch, overrides):
    state = _save_env(monkeypatch)
    _save()
    with pytest.raises(graph_editor.GraphEditorConflict, match="idempotency_conflict"):
        _save(**overrides)
    assert len(state["staged"]) == 1


def test_receipt_replays_after_restart_and_after_a_later_publication(monkeypatch):
    state = _save_env(monkeypatch)
    original = _save()
    state["active"] = {**state["active"], "id": "pub-20"}
    # A new service process has no cache to hydrate; only the DB receipt matters.
    monkeypatch.setattr(graph_editor, "active_publication", lambda slug: pytest.fail("replay read active"))
    assert _save() == original
    assert len(state["staged"]) == 1


def test_lost_committed_reply_is_reconciled_by_same_request_key(monkeypatch):
    state = _save_env(monkeypatch)
    state["lose_reply"] = True
    with pytest.raises(graph_editor.GraphEditorOutcomeUnknown):
        _save()
    assert state["active"]["id"] == "pub-17"
    assert _save()["publication_id"] == "pub-17"
    assert len(state["activated"]) == 1


def test_distinct_keys_racing_from_same_base_have_only_one_cas_winner(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from services import graph_bundle_publisher
    state = _save_env(monkeypatch)
    original_stage = graph_bundle_publisher.stage_bundle
    barrier = threading.Barrier(2)
    def stage(*args, **kwargs):
        result = original_stage(*args, **kwargs)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(graph_bundle_publisher, "stage_bundle", stage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(_save, idempotency_key=key) for key in ("writer-a", "writer-b")]
        outcomes = []
        for call in calls:
            try: outcomes.append(call.result(timeout=20))
            except graph_editor.GraphEditorConflict: outcomes.append("conflict")
    assert outcomes.count("conflict") == 1
    assert len(state["receipts"]) == len(state["activated"]) == 1


def test_same_key_racing_from_same_base_replays_one_result(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from services import graph_bundle_publisher
    state = _save_env(monkeypatch)
    original_stage = graph_bundle_publisher.stage_bundle
    barrier = threading.Barrier(2)
    def stage(*args, **kwargs):
        result = original_stage(*args, **kwargs)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(graph_bundle_publisher, "stage_bundle", stage)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(_save) for _ in range(2)]
        results = [call.result(timeout=20) for call in calls]
    assert results[0] == results[1]
    assert len(state["receipts"]) == len(state["activated"]) == 1


def test_revert_only_to_the_previous_publication(monkeypatch):
    state = _save_env(monkeypatch)
    monkeypatch.setattr(graph_editor, "previous_publication", lambda slug, active: {"id": "pub-15", "version": 15, "checksum": "sha256:previous"})
    with pytest.raises(graph_editor.GraphEditorConflict, match="revert_target_not_previous"):
        graph_editor.revert(persona_slug="utzig-garage", to_publication_id="pub-3", actor="admin-1", base_publication_id="pub-16", idempotency_key="revert-1")
    result = graph_editor.revert(persona_slug="utzig-garage", to_publication_id="pub-15", actor="admin-1", base_publication_id="pub-16", idempotency_key="revert-1")
    assert result["publication_id"] == "pub-15" and result["reverted_from_publication_id"] == "pub-16"
    assert state["rpc"][-1][0] == "commit_graph_editor_v1"
    assert state["rpc"][-1][1]["p_base_publication_id"] == "pub-16"
    assert state["events"][-1]["event_type"] == "graph_editor_committed"


def _request(role: str, *, can_edit: bool):
    access = [{"persona_id": "p-utzig", "persona_slug": "utzig-garage", "can_view": True,
               "can_edit": can_edit, "can_manage": False}]
    return SimpleNamespace(state=SimpleNamespace(
        user={"id": f"{role}-1", "role": role, "account_type": "internal"}, persona_access=access))


def _body(**overrides):
    from routes import graph_bundles
    return graph_bundles.EditorSaveBody(**{"persona_slug": "utzig-garage", "base_publication_id": "pub-16",
                                           "changes": ACCEPTANCE, "idempotency_key": "key-12345", **overrides})


def _route_error(call) -> HTTPException:
    with pytest.raises(HTTPException) as raised:
        call()
    return raised.value


def test_save_route_answers_409_and_422_with_readable_errors(monkeypatch):
    from routes import graph_bundles
    _save_env(monkeypatch)
    admin = _request("admin", can_edit=True)
    stale = _route_error(lambda: graph_bundles.graph_editor_save(_body(base_publication_id="pub-15"), admin))
    assert stale.status_code == 409 and stale.detail["errors"][0]["code"] == "base_not_active"
    unknown = _route_error(lambda: graph_bundles.graph_editor_save(
        _body(changes=[{"type": "rename_persona"}], idempotency_key="key-unknown"), admin))
    assert unknown.status_code == 422
    assert unknown.detail == {"errors": [{"code": "change_not_supported",
                                          "message": "Tipo de alteração desconhecido (rename_persona)."}]}
    # A graph the compiler refuses comes back with the compiler code, in Portuguese.
    monkeypatch.setattr(graph_editor, "expand_changes", lambda bundle, changes, document=None: [
        {"op": "update_node", "node_id": PERSONA, "patch": {MODES: {"vehicle_color": "disabled"}}}])
    refused = _route_error(lambda: graph_bundles.graph_editor_save(_body(idempotency_key="key-compiler"), admin))
    assert refused.status_code == 422
    assert refused.detail["errors"] == [{"code": "question_mode_field_not_declared",
                                         "message": "A pergunta “vehicle_color” não existe em nenhum caminho; "
                                                    "não dá para ligar ou desligar."}]


def test_save_route_succeeds_for_an_admin(monkeypatch):
    from routes import graph_bundles
    state = _save_env(monkeypatch)
    result = graph_bundles.graph_editor_save(_body(), _request("admin", can_edit=True))
    assert result == {"version": 17, "publication_id": "pub-17", "previous_publication_id": "pub-16"}
    assert state["events"][0]["payload"]["actor"] == "admin-1"


def test_routes_require_admin_to_save_and_scope_every_persona(monkeypatch):
    from routes import graph_bundles
    state = _save_env(monkeypatch)
    operator = _request("operator", can_edit=True)
    assert _route_error(lambda: graph_bundles.graph_editor_save(_body(), operator)).status_code == 403
    assert _route_error(lambda: graph_bundles.graph_editor_save(
        _body(persona_slug="tock-fatal"), operator)).status_code == 403
    assert _route_error(lambda: graph_bundles.graph_editor_get(
        operator, persona_slug="tock-fatal")).status_code == 403
    assert _route_error(lambda: graph_bundles.graph_editor_revert(graph_bundles.EditorRevertBody(
        persona_slug="utzig-garage", to_publication_id="pub-15", base_publication_id="pub-16", idempotency_key="revert-1"), operator)).status_code == 403
    assert state["staged"] == []
    assert not any(route.path in {"/graph-bundles/editor/plan", "/graph-bundles/editor/publish"}
                   for route in graph_bundles.router.routes)


def test_get_route_returns_the_frozen_view_shape(monkeypatch):
    from routes import graph_bundles
    _save_env(monkeypatch)
    monkeypatch.setattr(graph_editor, "previous_publication", lambda slug, active: {"id": "pub-15", "version": 15, "checksum": "sha256:previous"})
    view = graph_bundles.graph_editor_get(_request("operator", can_edit=False), persona_slug="utzig-garage")
    assert list(view) == ["publication", "previous_publication", "editable", "blocked_reasons",
                          "compiler_upgrade", "persona_node_id", "journey", "knowledge"]
    assert view["previous_publication"]["id"] == "pub-15" and view["publication"]["id"] == "pub-16"


def test_confirmation_rule_is_in_runtime_context_before_and_after_branch_choice():
    _, edited, journey = _expand([{"type": "set_text", "key": "confirmation", "value": "Peça bairro e cidade uma vez, sem insistir; confirme o resumo."}])
    stage = _stage(journey, "confirmation")
    rule_id = stage["rule_node_id"]
    assert rule_id == "rule:journey:confirmation"
    compiled = graph_bundle.compile_bundle(edited)
    for contract in [compiled["common_contract"], *compiled["branch_contracts"].values()]:
        assert rule_id in contract["turn_context_node_ids"]
        assert rule_id in contract["turn_context_chunk_node_ids"]
    assert _declarations_for_bundle(edited) == _declarations_for_bundle(_base())


def test_knowledge_edit_keeps_node_identity_fields_and_claims():
    base = _base()
    faq = next(n for n in base["nodes"] if n["node_type"] == "faq" and (n.get("data") or {}).get("answer"))
    text = faq["data"]["question"] + "\nResposta editada pelo administrador."
    _, edited, _ = _expand([{"type": "set_knowledge", "node_id": faq["id"], "text": text}], base)
    changed = next(n for n in edited["nodes"] if n["id"] == faq["id"])
    assert changed["data"]["answer"] == "Resposta editada pelo administrador."
    assert changed["projection_node_id"] == faq["projection_node_id"]
    assert changed["data"].get("claims") == faq["data"].get("claims")
    assert edited["edges"] == base["edges"]
    _refused([{"type": "set_knowledge", "node_id": faq["id"], "text": "Sem resposta"}], "knowledge_faq_format_invalid", base)
    _refused([{"type": "set_knowledge", "node_id": PERSONA, "text": "Tentar mudar persona"}], "knowledge_not_editable", base)


def test_active_publication_decodes_stored_text_without_losing_numeric_spelling(monkeypatch):
    from services import supabase_client
    publication = _publication()
    document = publication["document_json"]
    document["nodes"][0]["data"]["numeric_fixture"] = 1.0
    monkeypatch.setattr(supabase_client, "get_persona", lambda slug: {"id": publication["persona_id"]})
    class Client:
        def rpc(self, name, params):
            assert name == "read_graph_editor_publication_v1"
            assert params == {"p_persona_id": publication["persona_id"]}
            return SimpleNamespace(execute=lambda: SimpleNamespace(data={
                "publication": {k:v for k,v in publication.items() if k != "document_json"},
                "document_text": json.dumps(document),
            }))
    monkeypatch.setattr(supabase_client, "get_client", lambda: Client())
    value = graph_editor.active_publication("utzig-garage")
    assert type(value["document_json"]["nodes"][0]["data"]["numeric_fixture"]) is float


def test_compiler_upgrade_requires_valid_baseline_and_unchanged_content():
    publication = _publication()
    def older(value):
        if isinstance(value, dict):
            return {k: ("graph-compiler-v3.6.6" if k == "compiler_version" else older(v)) for k,v in value.items()}
        if isinstance(value, list): return [older(v) for v in value]
        return value
    document = older(publication["document_json"])
    document.pop("checksum")
    document["checksum"] = graph_editor.graph_compiler_v3.canonical_checksum(document)
    publication = {**publication, "compiler_version": "graph-compiler-v3.6.6", "checksum": document["checksum"], "document_json": document}
    checked = graph_editor.verify_round_trip(publication)
    assert checked["editable"] is True and checked["same_checksum"] is False
    assert checked["compiler_upgrade"] == {"from": "graph-compiler-v3.6.6", "to": "graph-compiler-v3.6.7"}
    bad = copy.deepcopy(publication)
    bad["document_json"]["nodes"][0]["title"] += " corrupted"
    assert graph_editor.verify_round_trip(bad)["editable"] is False
    current = _publication()
    document = current["document_json"]
    document["unknown_top_level_extension"] = True
    document.pop("checksum")
    document["checksum"] = graph_editor.graph_compiler_v3.canonical_checksum(document)
    current["checksum"] = document["checksum"]
    checked = graph_editor.verify_round_trip(current)
    assert checked["editable"] is False
    assert "base_recompile_checksum_mismatch" in checked["validation_errors"]


@pytest.mark.parametrize("getter,args", [("get_knowledge_node_for_source", ("graph_bundle", "source-id")), ("get_knowledge_node_by_slug", ("some-slug",))])
def test_staging_nodes_never_escape_lookup_fallback(monkeypatch, getter, args):
    from repositories import control_plane as repository
    class Query:
        def __getattr__(self, name):
            return lambda *args, **kwargs: self
    monkeypatch.setattr(repository, "_KG_TABLES_MISSING", False)
    monkeypatch.setattr(repository, "get_client", lambda: Query())
    monkeypatch.setattr(repository, "_q", lambda query: [{"id": "placeholder", "metadata": {"editor_staging": True}}])
    assert getattr(repository, getter)(*args) is None


def test_raw_publication_conflict_reaches_http409(monkeypatch):
    from repositories import control_plane as repository
    class Conflict(Exception):
        code = "40001"
    class Query:
        def execute(self):
            raise Conflict("raw_published_graph_write_requires_editor")
    with pytest.raises(HTTPException) as failure:
        repository._q(Query())
    assert failure.value.status_code == 409
    assert failure.value.detail["errors"][0]["code"] == "published_graph_requires_editor"
    assert "raw_published" not in failure.value.detail["errors"][0]["message"]
