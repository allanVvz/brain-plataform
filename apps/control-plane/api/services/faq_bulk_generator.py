"""Generate real FAQ (question+answer) content for one branch of the
knowledge tree -- the piece `sofia_tools.tool_generate_faq_from_branch` has
always been a placeholder for (see its docstring: "O conteudo real ...
sera preenchido pelo worker da Janela 4" -- that worker was never built).

Two callers share this one engine:
1. `sofia_tools.tool_generate_faq_from_branch`, inline during a Sofia chat
   session -- the branch chain comes from the in-progress plan.
2. `POST /knowledge/graph/{node_id}/generate-faqs` (api/routes/knowledge.py)
   for an already-published node, outside any chat session -- the branch
   chain comes from the live graph (`knowledge_nodes`/`knowledge_edges`).

Both produce plain `{question, answer}` pairs grounded ONLY in the branch's
own title/content/tags -- the prompt explicitly forbids inventing facts not
present in the chain, mirroring the project's "não inventar produtos/preço"
rule already enforced elsewhere (docs/tock-fatal-modal-marketing-graph.md's
`regra-nao-inventar-produtos-tock`).

Writing quality comes from repository-owned generic graph skills. A
persona-specific skill is loaded only when the caller explicitly requests it,
so one customer's voice cannot leak into another customer's FAQs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from services.model_router import ModelRouter, ModelRouterError

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Only generic skills are safe defaults. Persona-specific skills can be passed
# explicitly after the caller has resolved the persona.
_DEFAULT_SKILLS = ("brain-faq-branch", "brain-sales-graph")


def _load_skill_content(skill_name: str) -> str:
    for root in (".agents", ".claude"):
        path = _REPO_ROOT / root / "skills" / skill_name / "SKILL.md"
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    return ""


def _skills_context(skill_names: tuple[str, ...]) -> str:
    blocks = []
    for name in skill_names:
        content = _load_skill_content(name)
        if content:
            blocks.append(f"### Skill: {name}\n{content[:4000]}")
    if not blocks:
        return ""
    return (
        "Contratos de autoria e qualidade aplicáveis a este lote. Preserve os "
        "fatos e o tom publicados pela persona; nunca copie identidade ou "
        "exemplos de outra persona:\n\n" + "\n\n".join(blocks)
    )


def _chain_to_text(chain: list[dict[str, Any]]) -> str:
    lines = []
    for node in chain:
        title = str(node.get("title") or node.get("slug") or "").strip()
        content = str(node.get("content") or node.get("summary") or "").strip()
        node_type = str(node.get("node_type") or node.get("content_type") or "").strip()
        source = str(
            node.get("source")
            or (node.get("metadata") or {}).get("source")
            or (node.get("data") or {}).get("source")
            or "pending_source"
        ).strip()
        status = str(node.get("status") or "pending_validation").strip()
        line = f"- [{node_type}] {title} (status={status}; source={source})"
        if content:
            line += f": {content[:500]}"
        lines.append(line)
    return "\n".join(lines)


def generate_faqs_for_chain(
    chain: list[dict[str, Any]],
    *,
    max_questions: int = 8,
    model: str = "gpt-4o-mini",
    skills: tuple[str, ...] = _DEFAULT_SKILLS,
) -> list[dict[str, Any]]:
    """Return up to `max_questions` `{question, answer}` pairs grounded in
    `chain` (branch ancestors, closest node first -- see the two adapters
    below for how each caller builds this list). Returns [] on any LLM
    failure or unparseable output -- callers keep the placeholder entry
    rather than silently publishing fabricated content."""
    if not chain:
        return []
    max_questions = max(1, min(20, int(max_questions or 8)))
    branch_text = _chain_to_text(chain)
    skills_text = _skills_context(skills)
    prompt = (
        f"Gere até {max_questions} pares de pergunta e resposta (FAQ) distintos que um "
        "cliente real perguntaria sobre este ramo do catálogo, no WhatsApp. "
        "Use SOMENTE os fatos abaixo -- nunca invente preço, prazo, estoque, "
        "frete, endereço, imagem, pagamento, troca, composição ou qualquer "
        "dado que não esteja explicitamente escrito. Se uma intenção não tem "
        "resposta factual no ramo, não gere essa FAQ. Perguntas curtas e "
        "naturais, como uma pessoa escreveria no WhatsApp. Respostas curtas, "
        "no tom publicado, sem termos internos como grupo de produtos, node, "
        "branch, publicado ou retrieval. Cubra intenções diferentes; não "
        "multiplique paráfrases da mesma resposta.\n\n"
        f"Ramo (do mais específico ao mais geral):\n{branch_text}\n\n"
        + (f"{skills_text}\n\n" if skills_text else "")
        + 'Responda SOMENTE um array JSON: [{"question": str, "answer": str, '
        '"aliases": [str], "intent": str}, ...]. '
        "Sem texto fora do array."
    )
    try:
        router = ModelRouter()
        raw = router.messages_create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            system=(
                "Você escreve FAQ para atendimento comercial no WhatsApp. "
                "Nunca inventa fato não fornecido. Responde só com JSON válido."
            ),
            max_tokens=4000,
        )
    except ModelRouterError:
        return []
    match = re.search(r"\[.*\]", raw if isinstance(raw, str) else "", re.S)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return []
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        intent = str(item.get("intent") or "").strip()
        aliases = [
            str(value).strip() for value in item.get("aliases") or []
            if str(value).strip()
        ]
        dedupe_key = (
            re.sub(r"\W+", " ", (intent or question).casefold()).strip(),
            re.sub(r"\W+", " ", answer.casefold()).strip(),
        )
        if question and answer and dedupe_key not in seen:
            seen.add(dedupe_key)
            pairs.append({
                "question": question,
                "answer": answer,
                "aliases": list(dict.fromkeys(aliases)),
                "intent": intent or "other",
            })
    return pairs[:max_questions]


def build_chain_from_live_graph(node_rows: list[dict], edge_rows: list[dict], node_id: str) -> list[dict[str, Any]]:
    """Adapter for the graph-sidebar entry point: walk `contains` edges
    upward from `node_id` (an existing, published `knowledge_nodes.id`) to
    the persona root, using the already-fetched full node/edge set for a
    persona (e.g. `supabase_client.list_all_knowledge_graph(persona_id=...)`)."""
    nodes_by_id = {str(row.get("id")): row for row in node_rows}
    parent_by_child: dict[str, str] = {}
    for edge in edge_rows:
        metadata = edge.get("metadata") or {}
        if str(edge.get("relation_type") or "") != "contains":
            continue
        if metadata.get("active", True) is False:
            continue
        parent_by_child[str(edge.get("target_node_id"))] = str(edge.get("source_node_id"))

    chain: list[dict[str, Any]] = []
    cursor = str(node_id)
    seen: set[str] = set()
    while cursor and cursor not in seen and len(chain) < 16:
        seen.add(cursor)
        row = nodes_by_id.get(cursor)
        if not row:
            break
        chain.append({
            "id": row.get("id"),
            "slug": row.get("slug"),
            "graph_node_id": (row.get("metadata") or {}).get("graph_json_node_id"),
            "node_type": row.get("node_type"),
            "title": row.get("title"),
            "content": row.get("summary"),
            "tags": row.get("tags") or [],
            "source": (row.get("metadata") or {}).get("source"),
            "status": row.get("status"),
            "metadata": row.get("metadata") or {},
        })
        cursor = parent_by_child.get(cursor) or ""
    return chain
