"""Validated semantic changes and required-field normalization for graph editing."""
from __future__ import annotations
import copy
import re
import unicodedata
from typing import Any
from services import graph_bundle, graph_compiler_v3
from services.graph_editor_model import (
    GraphEditorError, EDITOR_SOURCE, QUESTION_STAGES, _EDITABLE_KNOWLEDGE_TYPES,
    _persona_node, _stage, journey_view,
)

from services.graph_editor_operations import (
    _Draft, _update, _valid_text, _is_question_node, _TEXT_KEYS, _declared_field_keys,
    MAX_TEXT_CHARS, MAX_QUESTION_CHARS,
    apply_operations, normalize_required_lists,
)
from services.graph_editor_questions import _set_question, _add_question, _move_question

def _set_text(draft: _Draft, change: dict[str, Any]) -> list[dict[str, Any]]:
    key, value = change.get("key"), change.get("value")
    if key == "confirmation":
        if not _valid_text(value, MAX_TEXT_CHARS):
            raise GraphEditorError("text_invalid:confirmation")
        node = next((n for n in draft.bundle["nodes"] if n.get("node_type") == "rule" and
            ((n.get("data") or {}).get("capabilities") or {}).get("journey_stage") == key), None)
        if node:
            return [_update(node["id"], {"summary": value.strip()})]
        node_id = "rule:journey:confirmation"
        return [{"op": "add_node", "node": {"id": node_id, "node_type": "rule",
            "slug": "journey-confirmation", "title": "Resumo e confirmação", "summary": value.strip(),
            "status": "approved", "tags": [],
            "data": {"capabilities": {"global_context": True, "journey_stage": key}}}},
            {"op": "add_edge", "edge": {"source": _persona_node(draft.bundle)["id"],
                "target": node_id, "relation_type": "contains"}}]
    if key not in _TEXT_KEYS:
        raise GraphEditorError(f"text_key_invalid:{key}")
    if not _valid_text(value, MAX_TEXT_CHARS):
        raise GraphEditorError(f"text_invalid:{key}")
    return [_update(_persona_node(draft.bundle)["id"], {_TEXT_KEYS[key]: value.strip()})]


def _set_knowledge(draft: _Draft, change: dict[str, Any]) -> list[dict[str, Any]]:
    node_id, text = str(change.get("node_id") or ""), change.get("text")
    node = next((n for n in draft.bundle["nodes"] if n["id"] == node_id), None)
    if not node or node.get("node_type") not in _EDITABLE_KNOWLEDGE_TYPES:
        raise GraphEditorError(f"knowledge_not_editable:{node_id}")
    if not _valid_text(text, MAX_TEXT_CHARS):
        raise GraphEditorError(f"knowledge_text_invalid:{node_id}")
    if node["node_type"] == "faq":
        if _is_question_node(node):
            return [_update(node_id, {"data.content.question" if isinstance((node.get("data") or {}).get("content"), dict) and (node["data"]["content"].get("question")) else "data.question": text.strip()})]
        question, separator, answer = text.strip().partition("\n")
        if not separator or not answer.strip() or not _valid_text(question, MAX_QUESTION_CHARS):
            raise GraphEditorError(f"knowledge_faq_format_invalid:{node_id}")
        # A FAQ question remains a FAQ; no owner, policy or claim is rewritten.
        content = (node.get("data") or {}).get("content") or {}
        question_path = "data.content.question" if isinstance(content, dict) and content.get("question") else "data.question"
        answer_path = "data.content.answer" if isinstance(content, dict) and content.get("answer") else ("data.content.resposta" if isinstance(content, dict) and content.get("resposta") else "data.answer")
        return [_update(node_id, {question_path: question.strip(), answer_path: answer.strip()})]
    return [_update(node_id, {"summary": text.strip()})]


_EXPANSIONS = {
    "set_question": _set_question,
    "add_question": _add_question,
    "move_question": _move_question,
    "set_text": _set_text,
    "set_knowledge": _set_knowledge,
}
_QUESTION_ATTRIBUTES = ("active", "essential", "tracking", "text")


def _split(changes: list[Any]) -> list[dict[str, Any]]:
    result = []
    for change in changes:
        if not isinstance(change, dict) or change.get("type") not in _EXPANSIONS:
            kind = change.get("type") if isinstance(change, dict) else type(change).__name__
            raise GraphEditorError(f"change_not_supported:{kind}")
        attributes = [name for name in _QUESTION_ATTRIBUTES if name in change]
        if change["type"] == "set_question" and len(attributes) > 1:
            base = {name: value for name, value in change.items() if name not in _QUESTION_ATTRIBUTES}
            result += [{**base, name: change[name]} for name in attributes]
        else:
            result.append(change)
    return result


def expand_changes(
    bundle: dict[str, Any], changes: list[dict[str, Any]], *, document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand semantic changes into graph operations, in order.

    ``document`` is the compiled ``bundle`` when the caller already has it.
    Applying the returned operations to ``bundle`` with ``apply_operations``
    reproduces the state each change was expanded against.
    """
    draft = _Draft(copy.deepcopy(bundle), document)
    operations: list[dict[str, Any]] = []
    for change in _split(changes):
        expanded = _EXPANSIONS[change["type"]](draft, change)
        draft.apply(expanded)
        operations += expanded
    return operations


# ── Readable errors ────────────────────────────────────────────────────────

_MESSAGES = {
    # Compiler (graph_compiler_v3) codes.
    "question_mode_field_not_declared": "A pergunta “{label}” não existe em nenhum caminho; não dá para ligar ou desligar.",
    "field_question_empty": "A pergunta “{label}” está sem texto. Escreva a pergunta antes de salvar.",
    "field_question_missing": "A pergunta “{label}” não tem texto de pergunta no grafo.",
    "field_validation_mode_missing": "A pergunta “{label}” precisa de um jeito de validar a resposta (opções, formato ou significado).",
    "ambiguous_field_declaration": "A pergunta “{label}” ficou com duas configurações diferentes no mesmo caminho. Faça a alteração em todos os caminhos.",
    "field_dependency_missing": "A pergunta “{label}” depende de outra pergunta que não existe neste caminho.",
    "field_dependency_cycle": "A pergunta “{label}” depende dela mesma numa cadeia de perguntas.",
    "inconsistent_field_owner": "A pergunta “{label}” ficou com donos diferentes entre os caminhos.",
    "question_mode_invalid": "A pergunta “{label}” recebeu um modo desconhecido.",
    "field_owner_unreachable": "A pergunta “{label}” pertence a um item fora deste caminho.",
    # Editor codes.
    "change_not_supported": "Tipo de alteração desconhecido ({label}).",
    "change_value_invalid": "A alteração da pergunta “{label}” tem um valor inválido.",
    "set_question_without_change": "Nada a alterar na pergunta “{label}”.",
    "question_not_found": "A pergunta “{label}” não existe neste grafo.",
    "question_node_missing": "A pergunta “{label}” não tem um texto de pergunta para editar.",
    "question_text_invalid": "O texto da pergunta não pode ficar vazio nem passar de 500 caracteres.",
    "essential_branch_unknown": "O caminho escolhido para a pergunta “{label}” não existe neste grafo.",
    "essential_branch_shared": "Na pergunta “{label}”, essencial vale para todos os caminhos juntos. Altere em todos.",
    "add_question_stage_invalid": "Escolha a etapa da nova pergunta: identificação, classificação ou serviço.",
    "add_question_label_invalid": "Dê um nome curto à nova pergunta (até 80 caracteres, com letras ou números).",
    "add_question_branches_required": "Escolha ao menos um caminho para a nova pergunta do serviço.",
    "add_question_branch_unknown": "Um dos caminhos escolhidos para a nova pergunta não existe neste grafo.",
    "move_question_not_in_stage": "A pergunta “{label}” não está nesta etapa.",
    "move_out_of_range": "A pergunta “{label}” já está no limite da etapa.",
    "move_not_honored": "A pergunta “{label}” não pode trocar de lugar: o nome vem sempre primeiro e algumas perguntas têm ordem fixa no grafo.",
    "move_service_order_fixed": "Nas perguntas do serviço a ordem é a de cada caminho; não dá para mover nesta etapa.",
    "text_key_invalid": "Escolha abertura, confirmação ou encerramento.",
    "knowledge_not_editable": "Este conhecimento não permite editar o texto.",
    "knowledge_text_invalid": "O texto não pode ficar vazio nem passar de 2000 caracteres.",
    "knowledge_faq_format_invalid": "Escreva a pergunta na primeira linha e a resposta nas demais linhas.",
    "idempotency_conflict": "A chave já foi usada com outra alteração. Recarregue o editor.",
    "text_invalid": "O texto não pode ficar vazio nem passar de 2000 caracteres.",
    "field_owner_change_refused": "A pergunta “{label}” não pode mudar de dono: as respostas já coletadas dependem dele.",
    "base_not_editable": "Esta versão do grafo não pode ser editada pela tela.",
    "base_not_active": "Outra pessoa salvou uma versão nova. Recarregue o editor e refaça a alteração.",
    "persona_not_found": "Persona não encontrada.",
    "active_publication_not_found": "Esta persona ainda não tem um grafo publicado.",
    "publication_failed": "A publicação falhou e a versão anterior continua ativa.",
}


def readable_errors(errors: list[str], labels: dict[str, str] | None = None) -> list[dict[str, str]]:
    """``[{code, message}]`` in plain Portuguese, one per distinct problem.

    Error strings are ``code:args`` (the compiler may prefix a branch id);
    ``labels`` maps declared field keys to the labels the screen shows.
    """
    labels = labels or {}
    result: list[dict[str, str]] = []
    for error in errors:
        parts = str(error).split(":")
        index = next((i for i, part in enumerate(parts) if part in _MESSAGES), None)
        if index is None:
            item = {"code": parts[0], "message": f"O grafo recusou a alteração ({parts[0]})."}
        else:
            rest = parts[index + 1:]
            key = next((part for part in rest if part in labels), rest[0] if rest else "")
            item = {"code": parts[index], "message": _MESSAGES[parts[index]].format(label=labels.get(key) or key)}
        if item not in result:
            result.append(item)
    return result


class GraphEditorRejected(GraphEditorError):
    """The changes, or the graph they produce, were refused (HTTP 422)."""

    def __init__(self, errors: list[str], *, labels: dict[str, str] | None = None):
        self.errors = readable_errors(errors, labels)
        super().__init__("; ".join(item["code"] for item in self.errors))


def _labels(bundle: dict[str, Any]) -> dict[str, str]:
    data = _persona_node(bundle).get("data") or {}
    published = (data.get("conversation_policy") or {}).get("field_labels") or (
        (data.get("appointment_policy") or {}).get("field_labels") or {})
    return {key: str(published.get(key) or key) for key in _declared_field_keys(bundle)}
