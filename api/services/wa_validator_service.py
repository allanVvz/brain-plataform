# -*- coding: utf-8 -*-
"""
WA Validator Service — generates test scripts from KB, tracks validation sessions,
and analyses conversation gaps to feed back into KB Intake.
"""

import asyncio
import httpx
import json
import os
import random
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from services import (
    conversation_runtime,
    graph_agent_runtime_v3,
    graph_json_v2_store,
    n8n_client,
    supabase_client,
)

# Flows that collect the customer's name as one of their scripted steps --
# the only ones "known_name" initial state can meaningfully apply to (a
# flow with no name-collection step has nothing to pre-seed or omit).
_NAME_COLLECTING_FLOWS = {"sdr_qualificacao_carro", "sdr_troca_servico"}

_MODEL_DEFAULT = "none"
AVAILABLE_MODELS = {
    "none": "Determinístico — sem modelo",
}
_ROOT_DIR = Path(__file__).resolve().parents[2]
_WA_EXECUTOR = _ROOT_DIR / "dashboard" / "scripts" / "wa-validator.mjs"
_WA_NODE = os.environ.get("WA_VALIDATOR_NODE", "node")
_WA_RUNTIME = _ROOT_DIR / ".runtime" / "wa-validator"
_WA_PROFILE = Path(
    os.environ.get(
        "WA_VALIDATOR_PROFILE",
        str(_ROOT_DIR / ".runtime" / "wa-validator-profile"),
    )
)
_WA_ARTIFACTS = _ROOT_DIR / "test-artifacts" / "wa-validator"
_WA_RUNNER_URL = (os.environ.get("WA_VALIDATOR_RUNNER_URL") or "").rstrip("/")
_BRAIN_API_URL = os.environ.get("BRAIN_API_URL", "http://localhost:8080")

# WA Validator sessions live in Supabase, not a plain in-process dict.
# Confirmed live 2026-08-08: production runs GUNICORN_WORKERS=2, so a
# "generate script" request and the following "run" request had roughly a
# coin-flip chance of landing on different worker processes -- the second
# worker's in-memory dict never had the session the first one created,
# producing "Sessão não encontrada" for a session that genuinely existed,
# just in the other process's memory.


def _session_get(session_id: str) -> Optional[dict]:
    return supabase_client.get_wa_validator_session(session_id)


def _session_create(
    session_id: str, data: dict, *, persona_slug: Optional[str] = None, flow_id: Optional[str] = None
) -> None:
    supabase_client.upsert_wa_validator_session(session_id, data, persona_slug=persona_slug, flow_id=flow_id)


def _session_update(session_id: str, **fields) -> dict:
    """Read-modify-write merge patch.

    Best-effort, not transactional -- acceptable for this ephemeral
    test-tooling data, where each session_id has at most one active writer
    in practice (a single validator run driving its own session).
    """
    current = supabase_client.get_wa_validator_session(session_id) or {}
    current.update(fields)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    supabase_client.upsert_wa_validator_session(session_id, current)
    return current


def _session_list() -> list[dict]:
    return supabase_client.list_wa_validator_sessions()

# ── Bot registry ───────────────────────────────────────────────────────────────
_BOT_REGISTRY: list[dict] = []

_KNOWN_CONVERSATION_MODES = {"deterministic", "n8n_agents", "orquestrador"}


def _resolve_conversation_mode(persona_id: str | None, routing: dict) -> str:
    """The routing switch that actually governs live dispatch.

    Confirmed live 2026-08-08: this previously read only the legacy
    persona.process_mode column, so the validator tested a different engine
    (n8n_agents) than the one actually handling real WhatsApp traffic
    (deterministic, per the active binding's decision_owner) -- an Aurora
    validation session failed every step because it POSTed to an n8n
    webhook nobody maintains, while real customers were being served by the
    deterministic graph_agent_runtime_v3 pipeline the whole time. Mirrors
    routes.personas._mask_routing's resolution exactly, so the validator and
    the settings UI never disagree about which engine is live.
    """
    process_mode = routing.get("process_mode") or "internal"
    fallback = "n8n_agents" if process_mode == "n8n" else "deterministic"
    if not persona_id:
        return fallback
    active_binding = next(
        (
            row
            for row in supabase_client.get_workflow_bindings(persona_id)
            if row.get("active")
        ),
        None,
    )
    decision_owner = ((active_binding or {}).get("metadata") or {}).get("decision_owner")
    return decision_owner if decision_owner in _KNOWN_CONVERSATION_MODES else fallback


def bots() -> list:
    """Return available bots: static registry + any active personas not yet listed."""
    result = list(_BOT_REGISTRY)
    registered = {b["persona_slug"] for b in _BOT_REGISTRY}
    try:
        for p in supabase_client.get_personas():
            slug = p.get("slug", "")
            if slug and slug not in registered:
                agent_name = p.get("name", slug)
                agent_slug = "agent"
                try:
                    current = graph_json_v2_store.load_current(slug)
                    graph = current[1] if current else None
                    agent_node = next(
                        (
                            node
                            for node in (graph.nodes if graph else [])
                            if (node.data or {}).get("metadata", {}).get(
                                "agent_slug"
                            )
                        ),
                        None,
                    )
                    if agent_node:
                        agent_name = agent_node.label
                        agent_slug = str(
                            (agent_node.data or {}).get("metadata", {}).get(
                                "agent_slug"
                            )
                            or agent_node.slug
                        )
                except Exception:
                    pass
                result.append({
                    "id": slug,
                    "bot_name": agent_name,
                    "agent_slug": agent_slug,
                    "whatsapp_phone": (
                        (agent_node.data or {}).get("metadata", {}).get(
                            "whatsapp_phone"
                        )
                        if agent_node
                        else None
                    ),
                    "label": f"{agent_name} — {p.get('name', slug)}",
                    "persona_slug": slug,
                    "description": p.get("description", ""),
                })
                registered.add(slug)
    except Exception:
        pass
    return result


_FLOWS = {
    "compra_simples": "Fluxo de compra simples: cliente pergunta sobre produto, recebe info, confirma compra.",
    "duvida_frete": "Fluxo de dúvida sobre frete/entrega: cliente pergunta prazo e valor de frete.",
    "saudacao_despedida": "Fluxo básico: saudação, pergunta simples, despedida.",
    "produto_especifico": "Fluxo de produto específico: cliente nomeia produto, bot responde com detalhes e CTA.",
    "reclamacao": "Fluxo de reclamação/insatisfação: cliente reclama, bot reconhece e escalona.",
    "atendente_humano": "Pedido explícito de atendente com handoff.",
    "produto_inexistente": "Produto inexistente após uma pergunta de esclarecimento.",
    "sem_evidencia": "Pergunta comercial sem evidência aprovada no grafo.",
    "produto_ambiguo": "Nome de produto ambíguo que exige esclarecimento.",
    "mensagem_duplicada": "Retry idempotente da mesma mensagem Meta.",
    "estagio_monotonic": "Mensagem curta não pode rebaixar o estágio.",
    "classifier_failure": "Falha do classificador determinístico gera handoff.",
    "invalid_decision_schema": "Saída fora do contrato gera handoff.",
    "delivery_callback": "Callbacks sent/delivered/read/failed são reconciliados.",
    "sdr_qualificacao_carro": (
        "SDR agêntico de agendamento (Aurora): qualifica nome, veículo, ano, "
        "objetivo e trilha presencial/remoto, nunca confirma preço ou "
        "horário, e encerra com handoff para a equipe humana."
    ),
    "sdr_troca_servico": (
        "SDR agêntico de agendamento (Aurora): cliente pede um serviço, muda "
        "de ideia no meio da qualificação e pede um serviço diferente -- "
        "valida que nome, veículo e ano já informados não são perguntados "
        "de novo depois da troca de branch."
    ),
    "sdr_reclamacao_recorrente": (
        "Cliente recorrente (Aurora): fase 1 é um agendamento completo "
        "(nome, veículo, ano, objetivo, presencial/remoto, condição) que "
        "resolve até o handoff; as mensagens dessa fase são então "
        "retroagidas algumas horas. Fase 2, horas depois, é uma reclamação "
        "sem repetir o nome -- valida que o nome/veículo não são "
        "perguntados de novo, que a pergunta da reclamação referencia o "
        "serviço já conhecido, e que a resposta não soa como continuação "
        "direta da fase 1."
    ),
}

# A fixed name (previously always "Allan") made every validator run
# indistinguishable and never exercised the fact-extraction path for any
# other name. One is picked per generate_script() call so consecutive runs
# actually vary, covering both genders instead of skewing the sample.
_CLIENT_NAMES = [
    "Allan", "Bruno", "Carlos", "Diego", "Eduardo", "Fabio", "Gustavo",
    "Marcos", "Rafael", "Thiago",
    "Ana", "Beatriz", "Camila", "Fernanda", "Gabriela", "Helena", "Isabela",
    "Juliana", "Larissa", "Patricia",
]

# Real Aurora service branches (confirmed live against the published graph
# 2026-08-08) -- picking one at random per run, instead of always
# "higienização interna", spreads coverage across the branches most likely
# to expose per-branch field/owner mismatches like the one fixed today.
_CAR_SERVICES = [
    "higienização interna", "polimento", "vitrificação", "pintura",
    "chapeação", "lavagem técnica detalhada", "polimento de vidros", "PPF",
]

# Which business_model(s) (persona_node.data.business_model, same field
# services.conversation_runtime._business_model reads) a flow's scripted
# messages actually make sense for. Confirmed live 2026-08-08: running
# "compra_simples" (asks price/quantity of a "produto") against Aurora
# (business_model="appointment", no product nodes at all) produced a
# looping, self-contradicting conversation -- not a pipeline bug, a
# nonsensical test. Flows absent here (or mapped to an empty set) are
# treated as valid for any business model.
_FLOW_BUSINESS_MODELS: dict[str, set[str]] = {
    "compra_simples": {"sales"},
    "duvida_frete": {"sales"},
    "produto_especifico": {"sales"},
    "produto_inexistente": {"sales"},
    "produto_ambiguo": {"sales"},
    "mensagem_duplicada": {"sales"},
    "estagio_monotonic": {"sales"},
    "sdr_qualificacao_carro": {"appointment"},
    "sdr_troca_servico": {"appointment"},
    "sdr_reclamacao_recorrente": {"appointment"},
}


def _extract_json(text: str) -> dict:
    """Parse JSON from Claude response regardless of markdown fences or surrounding text."""
    text = text.strip()
    # Find the outermost { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    # Fallback: try to parse as-is (handles plain JSON with no fences)
    return json.loads(text)


def _published_graph(persona_slug: str):
    current = graph_json_v2_store.load_current(persona_slug)
    if not current:
        raise ValueError(
            f"Nenhum Graph JSON v2 publicado para {persona_slug}"
        )
    version, graph = current
    event = graph_json_v2_store.latest_event(persona_slug) or {}
    checksum = (
        (event.get("payload") or {}).get("checksum")
        or graph_json_v2_store.checksum_graph(graph)
    )
    if graph.status != "published" or not graph.validation.is_valid:
        raise ValueError("Graph JSON v2 publicado não está válido")
    return version, checksum, graph


def _build_graph_context(persona_slug: str) -> tuple[str, int, str, object]:
    version, checksum, graph = _published_graph(persona_slug)
    lines: list[str] = []
    for node in graph.nodes:
        data = node.data or {}
        if data.get("active", True) is False:
            continue
        if str(data.get("status") or "").lower() not in {
            "approved",
            "validated",
            "active",
            "ativo",
        }:
            continue
        lines.append(
            f"[{node.id}] {node.node_type}/{node.slug}: "
            f"{node.label} {str(data.get('markdown') or '')[:300]}"
        )
    return "\n".join(lines), version, str(checksum), graph


def _deterministic_script(
    flow_id: str,
    *,
    product: object | None,
    graph_version: int,
    graph_checksum: str,
    omit_client_name: bool = False,
) -> dict:
    product_id = getattr(product, "id", None)
    product_data = getattr(product, "data", {}) or {}
    product_metadata = product_data.get("metadata") or {}
    product_name = (
        product_metadata.get("display_name")
        or getattr(product, "label", None)
        or "o primeiro produto ativo"
    )
    price = product_data.get("price") or product_metadata.get("price") or {}
    unit_price = (
        float(price.get("amount"))
        if isinstance(price, dict) and price.get("amount") is not None
        else None
    )
    common_expected = [f"graph:{graph_version}:{graph_checksum}"]
    if product_id:
        common_expected.insert(0, f"evidence:{product_id}")
    client_name = random.choice(_CLIENT_NAMES)
    service_a, service_b = random.sample(_CAR_SERVICES, 2)
    if flow_id == "sdr_reclamacao_recorrente":
        # Two-phase scenario: phase 1 is a normal booking that resolves to
        # completion (name + vehicle + service all known); a backdate step
        # then shifts those messages a few hours into the past before
        # phase 2 -- a complaint that never repeats the name -- runs. See
        # run_session_direct's handling of the "backdate_hours" step kind.
        return {
            "flow_description": _FLOWS.get(flow_id, flow_id),
            "expected_knowledge": common_expected,
            "steps": [
                {"text": f"Quero saber sobre {service_a} do meu carro", "wait": 10},
                {"text": client_name, "wait": 10},
                {"text": "Onix", "wait": 10},
                {"text": "2020", "wait": 10},
                {"text": "Quero manter o carro e cuidar bem dele", "wait": 10},
                {"text": "Consigo levar até vocês", "wait": 10},
                {"text": "Os bancos estão meio manchados", "wait": 10},
                {"backdate_hours": 5},
                {"text": "Estou com um problema com o serviço que fiz aí", "wait": 10},
            ],
            "expected_dialogue": {
                "product_name": product_name,
                "unit_price": unit_price,
                "final_quantity": None,
                "final_total": None,
                "forbidden_terms": ["tock", "tock fatal"],
                "known_service": service_a,
                "known_name": client_name,
            },
        }
    scenarios = {
        "compra_simples": [
            "Oi",
            f"Quanto custa {product_name}?",
            "quero 2",
            "mude para 3",
            "qual o total?",
            client_name,
            "Rua QA, 100, Canoas",
            "Sim",
        ],
        "saudacao_despedida": ["Oi", "Quais categorias estão disponíveis?", "Obrigado"],
        "produto_especifico": [f"Vocês têm {product_name}?", "quanto custa?", "quero 2"],
        "duvida_frete": ["Oi", "Como funciona a entrega?"],
        "reclamacao": ["Estou com um problema e quero fazer uma reclamação"],
        "atendente_humano": ["Quero falar com um atendente humano"],
        "produto_inexistente": ["Vocês têm o produto QA inexistente?", "É esse mesmo"],
        "sem_evidencia": ["Qual é uma condição comercial que não está documentada?"],
        "produto_ambiguo": ["Quero aquele produto", "Não sei o nome completo"],
        "mensagem_duplicada": [f"Quanto custa {product_name}?", f"Quanto custa {product_name}?"],
        "estagio_monotonic": [f"Quero 2 de {product_name}", "Oi"],
        "classifier_failure": ["[QA_CLASSIFIER_FAILURE]"],
        "invalid_decision_schema": ["[QA_INVALID_DECISION_SCHEMA]"],
        "delivery_callback": [f"Quero 1 de {product_name}"],
        "sdr_qualificacao_carro": [
            f"Quero saber sobre {service_a} do meu carro",
            *([] if omit_client_name else [client_name]),
            "Onix",
            "2020",
            "Quero manter o carro e cuidar bem dele",
            "Consigo levar até vocês",
            "Os bancos estão meio manchados",
        ],
        "sdr_troca_servico": [
            f"Quero saber sobre {service_a} do meu carro",
            *([] if omit_client_name else [client_name]),
            "Civic",
            "2021",
            f"Na verdade, prefiro fazer {service_b} em vez de {service_a}",
            "Quero manter o carro e cuidar bem dele",
            "Consigo levar até vocês",
            "Prata",
        ],
    }
    messages = scenarios.get(flow_id)
    if not messages:
        raise ValueError(f"Fluxo determinístico desconhecido: {flow_id}")
    expected_dialogue = {
        "product_name": product_name,
        "unit_price": unit_price,
        "final_quantity": 3 if flow_id == "compra_simples" else None,
        "final_total": (
            round(unit_price * 3, 2)
            if unit_price is not None and flow_id == "compra_simples"
            else None
        ),
        "forbidden_terms": ["tock", "tock fatal"],
    }
    if flow_id in _NAME_COLLECTING_FLOWS:
        expected_dialogue["known_name"] = client_name
        expected_dialogue["known_service"] = service_a
        expected_dialogue["client_name_omitted"] = omit_client_name
    return {
        "flow_description": _FLOWS.get(flow_id, flow_id),
        "expected_knowledge": common_expected,
        "steps": [{"text": text, "wait": 10} for text in messages],
        "expected_dialogue": expected_dialogue,
    }


def _resolve_initial_state(requested: str | None, flow_id: str) -> str:
    """Normalize the requested initial state to "cold" or "known_name".

    "random" and anything not applicable to this flow (no name-collection
    step) resolve to "cold" -- there is nothing to pre-seed or omit for a
    flow that never asks for the name in the first place.
    """
    if flow_id not in _NAME_COLLECTING_FLOWS:
        return "cold"
    if requested == "random":
        return random.choice(["cold", "known_name"])
    if requested == "known_name":
        return "known_name"
    return "cold"


def generate_script(
    persona_slug: str,
    flow_id: str,
    target_contact: str,
    model: str = _MODEL_DEFAULT,
    initial_state: str | None = None,
) -> dict:
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise ValueError(f"Persona não encontrada: {persona_slug}")

    persona_id = persona["id"]
    persona_name = persona.get("name", persona_slug)
    if not str(target_contact or "").strip():
        raise ValueError("Contato WhatsApp inválido")
    kb_ctx, graph_version, graph_checksum, graph = _build_graph_context(
        persona_slug
    )
    business_model = conversation_runtime._business_model(graph)
    flow_models = _FLOW_BUSINESS_MODELS.get(flow_id)
    if flow_models and business_model not in flow_models:
        raise ValueError(
            f"Fluxo '{flow_id}' não é válido para uma persona "
            f"'{business_model}' (requer {sorted(flow_models)})"
        )
    resolved_initial_state = _resolve_initial_state(initial_state, flow_id)
    agent_node = next(
        (
            node
            for node in graph.nodes
            if (node.data or {}).get("metadata", {}).get("agent_slug")
        ),
        None,
    )
    agent_metadata = (agent_node.data or {}).get("metadata", {}) if agent_node else {}
    agent_slug = str(agent_metadata.get("agent_slug") or "agent")
    target_phone = str(agent_metadata.get("whatsapp_phone") or "").strip()
    primary_product = next(
        (
            node
            for node in graph.nodes
            if node.node_type == "product"
            and (node.data or {}).get("metadata", {}).get("qa_primary") is True
        ),
        None,
    )
    script_data = _deterministic_script(
        flow_id,
        product=primary_product,
        graph_version=graph_version,
        graph_checksum=graph_checksum,
        omit_client_name=(resolved_initial_state == "known_name"),
    )
    routing = supabase_client.get_persona_routing(persona_slug) or {}
    conversation_mode = _resolve_conversation_mode(persona_id, routing)

    session_id = str(uuid.uuid4())
    script = {
        "meta": {
            "persona": persona_slug,
            "persona_name": persona_name,
            "flow": flow_id,
            "session_id": session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": "none",
            "classifier": "deterministic_v1",
            "conversation_mode": conversation_mode,
            "pipeline_contract": "conversation_v1",
            "agent_slug": agent_slug,
            "graph_version": graph_version,
            "graph_checksum": graph_checksum,
            "initial_state": resolved_initial_state,
        },
        "target": target_contact,
        "target_phone": target_phone or None,
        "flow_description": script_data.get("flow_description", ""),
        "expected_knowledge": script_data.get("expected_knowledge", []),
        "expected_dialogue": script_data.get("expected_dialogue", {}),
        "steps": script_data.get("steps", []),
    }

    _session_create(session_id, {
        "id": session_id,
        "persona_slug": persona_slug,
        "flow_id": flow_id,
        "status": "ready",
        "script": script,
        "output": None,
        "insights": None,
        "pid": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, persona_slug=persona_slug, flow_id=flow_id)

    supabase_client.insert_event({
        "event_type": "wa_validator_script_generated",
        "payload": {
            "session_id": session_id,
            "persona_slug": persona_slug,
            "flow_id": flow_id,
            "n_steps": len(script["steps"]),
        },
    })

    return {"session_id": session_id, "script": script}


def run_session(session_id: str) -> dict:
    session = _session_get(session_id)
    if not session:
        raise ValueError(f"Sessão não encontrada: {session_id}")
    if session["status"] == "running":
        raise ValueError("Sessão já está em execução")
    if _WA_RUNNER_URL:
        token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
        response = httpx.post(
            f"{_WA_RUNNER_URL}/run",
            json={"session_id": session_id, "script": session["script"]},
            headers={"X-Webhook-Token": token},
            timeout=15,
        )
        response.raise_for_status()
        _session_update(session_id, status="starting", runner=_WA_RUNNER_URL)
        return get_session(session_id)

    runtime_dir = _WA_RUNTIME / session_id
    runtime_dir.mkdir(parents=True, exist_ok=True)
    script_path = runtime_dir / "script.json"
    output_path = runtime_dir / "output.json"
    artifact_dir = _WA_ARTIFACTS / session_id
    script_path.write_text(
        json.dumps(session["script"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def _run():
        import logging as _logging
        _log = _logging.getLogger("wa_validator_service")
        try:
            cmd = [
                _WA_NODE,
                str(_WA_EXECUTOR),
                "--script",
                str(script_path),
                "--output",
                str(output_path),
                "--profile",
                str(_WA_PROFILE),
                "--artifacts",
                str(artifact_dir),
            ]
            _log.info("Iniciando subprocess: %s", " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                cwd=_ROOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _session_update(session_id, pid=proc.pid, status="running")

            stdout_data, _ = proc.communicate()

            if stdout_data:
                _log.info("wa_validator stdout [%s]:\n%s", session_id[:8], stdout_data[-3000:])

            output = {}
            if output_path.exists():
                output = json.loads(output_path.read_text(encoding="utf-8"))

            if not output and proc.returncode != 0:
                final_status = "error"
                error_msg = f"Processo encerrou com código {proc.returncode}.\nLog:\n{stdout_data[-2000:] if stdout_data else '(sem saída)'}"
            else:
                final_status = output.get("status", "done")
                error_msg = output.get("error", "")

            _session_update(
                session_id, output=output, status=final_status, error=error_msg,
                log=stdout_data[-4000:] if stdout_data else "",
                output_path=str(output_path), artifact_dir=str(artifact_dir),
            )

            supabase_client.insert_event({
                "event_type": "wa_validator_session_done",
                "payload": {
                    "session_id": session_id,
                    "status": final_status,
                    "returncode": proc.returncode,
                    "n_turns": len(output.get("conversation", [])),
                },
            })

        except Exception as e:
            _session_update(session_id, status="error", error=str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    _session_update(session_id, status="starting")

    return get_session(session_id)


def get_session(session_id: str) -> dict:
    session = _session_get(session_id)
    if not session:
        raise ValueError(f"Sessão não encontrada: {session_id}")
    if _WA_RUNNER_URL and session.get("runner"):
        try:
            token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
            response = httpx.get(
                f"{_WA_RUNNER_URL}/sessions/{session_id}",
                headers={"X-Webhook-Token": token},
                timeout=5,
            )
            response.raise_for_status()
            output = response.json()
            session = _session_update(session_id, output=output, status=output.get("status", "running"))
        except Exception as exc:
            session = _session_update(session_id, runner_error=str(exc))

    output_path = _WA_RUNTIME / session_id / "output.json"
    if session["status"] in ("running", "starting") and output_path.exists():
        try:
            partial = json.loads(output_path.read_text(encoding="utf-8"))
            session = _session_update(session_id, output=partial)
        except Exception:
            pass

    return session


def list_sessions() -> list:
    return sorted(_session_list(), key=lambda x: x["created_at"], reverse=True)


def analyze_gaps(session_id: str, model: str = _MODEL_DEFAULT) -> dict:
    session = get_session(session_id)
    output = session.get("output") or {}
    conversation = output.get("conversation", [])
    script = session.get("script", {})
    expected = script.get("expected_knowledge", [])
    persona_slug = session.get("persona_slug", "")

    _EMPTY_INSIGHTS = {
        "demonstrated": [], "gaps": [], "recommendations": [],
        "overall_score": 0, "summary": "",
    }

    if not conversation:
        return {**_EMPTY_INSIGHTS, "summary": "Sem conversa para analisar.", "session_id": session_id}

    bot_turns = [turn for turn in conversation if turn.get("role") == "bot"]
    failures = [
        turn
        for turn in bot_turns
        if turn.get("timeout")
        or turn.get("error")
        or str(turn.get("text") or "").startswith("(erro:")
    ]
    evidence_used = {
        str(node_id)
        for turn in bot_turns
        for node_id in (turn.get("evidence_node_ids") or [])
    }
    demonstrated: list[str] = []
    gaps: list[dict] = []
    for item in expected:
        if item.startswith("evidence:"):
            node_id = item.split(":", 1)[1]
            if node_id in evidence_used:
                demonstrated.append(item)
            else:
                gaps.append({
                    "topic": item,
                    "evidence": "Node não apareceu na evidência registrada.",
                    "priority": "high",
                })
        elif item.startswith("graph:"):
            expected_lineage = item.split(":", 1)[1]
            successful_turns = [turn for turn in bot_turns if turn not in failures]
            actual_lineages = {
                f"{turn.get('graph_version')}:{turn.get('graph_checksum')}"
                for turn in successful_turns
                if turn.get("graph_version")
            }
            if actual_lineages == {expected_lineage}:
                demonstrated.append(item)
            else:
                gaps.append({
                    "topic": item,
                    "evidence": (
                        "Nenhuma resposta bem-sucedida confirmou a versão do grafo."
                        if not actual_lineages
                        else f"Runtime reportou {sorted(actual_lineages)}, esperado {expected_lineage}."
                    ),
                    "priority": "high",
                })
    if failures:
        gaps.append({
            "topic": "transport_or_reply",
            "evidence": f"{len(failures)} turno(s) sem resposta válida.",
            "priority": "high",
        })
    response_ratio = (len(bot_turns) - len(failures)) / max(
        1,
        len([turn for turn in conversation if turn.get("role") == "validator"]),
    )
    evidence_ratio = len(demonstrated) / max(1, len(expected))
    score = round(max(0, min(100, (response_ratio * 50) + (evidence_ratio * 50))))
    insights = {
        **_EMPTY_INSIGHTS,
        "demonstrated": demonstrated,
        "gaps": gaps,
        "recommendations": [
            "Corrigir somente a origem Markdown/Graph indicada pela evidência."
        ] if gaps else [],
        "overall_score": score,
        "summary": (
            "Validação determinística concluída sem uso de modelo. "
            f"{len(failures)} falha(s) de resposta e {len(gaps)} gap(s)."
        ),
        "session_id": session_id,
        "persona_slug": persona_slug,
        "analyzer": "deterministic_v1",
    }

    _session_update(session_id, insights=insights)

    supabase_client.insert_event({
        "event_type": "wa_validator_gaps_analyzed",
        "payload": {
            "session_id": session_id,
            "persona_slug": persona_slug,
            "n_gaps": len(insights.get("gaps", [])),
            "score": insights.get("overall_score"),
        },
    })

    return insights


async def _wait_for_reply_delivered(
    lead_ref: int, messages_before: int, *, max_wait_s: float, poll_interval_s: float = 1.0,
) -> None:
    """Wait for the pipeline to actually persist a reply before the next scripted step.

    Confirmed live 2026-08-08: scripted steps advanced on a fixed sleep
    (capped at 3s) regardless of how long the real pipeline took, so on a
    slower turn (branch retrieval + agentic model + possible repair round)
    the next script message could go out before the previous one's reply
    had landed. Several inbound messages for the same lead in flight at
    once then raced graph_agent_runtime_v3's optimistic ledger lock
    (commit_graph_turn_v3's expected_revision check) -- every turn that
    lost that race silently produced no reply at all, while the customer
    message itself was still persisted, leaving several client turns in a
    row with no bot reply between them. Polling for an actual new message
    to land (up to max_wait_s) makes the validator behave like a real
    customer -- one message, wait for the reply, then the next -- instead
    of outrunning the pipeline. Generic: applies to every persona/flow the
    validator runs, not just Aurora.
    """
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        messages = supabase_client.get_messages(str(lead_ref), limit=200) or []
        if len(messages) > messages_before:
            return
        await asyncio.sleep(poll_interval_s)


def _seed_known_name(*, persona: dict, lead_ref: int, client_name: str) -> None:
    """Pre-seed nome_cliente as already-known before any script step runs.

    Tests the exact bug class fixed 2026-08-09 (a resolved field being
    re-asked/lost): a script generated with initial_state="known_name"
    never sends the customer's name at all, so if the agent asks for it
    anyway, that is a real regression, not scripted repetition. Reuses
    commit_graph_turn_v3 -- the same RPC every real turn commits through --
    instead of writing to conversation_ledgers/conversation_facts directly,
    so the seeded lead's state is indistinguishable from one that reached
    the same fact organically. Only meaningful for graph_agent_runtime_v3
    personas (Aurora et al.); quietly no-ops for any other runtime, where
    "known_name" behaves the same as "cold" for now.
    """
    if not client_name:
        return
    persona_id = str(persona.get("id") or "")
    if not persona_id:
        return
    publication = supabase_client.get_active_graph_publication(persona_id)
    if not publication:
        return
    document = publication.get("document_json") or {}
    owner_node_id = next(
        (
            field.get("owner_node_id")
            for contract in (document.get("branch_contracts") or {}).values()
            for field in contract.get("fields") or []
            if field.get("key") == "nome_cliente" and field.get("owner_node_id")
        ),
        None,
    )
    if not owner_node_id:
        return
    supabase_client.commit_graph_turn_v3(
        p_canonical_inbound_id=f"validator-seed:{lead_ref}",
        p_persona_id=persona_id, p_lead_ref=lead_ref,
        p_publication_id=publication["id"], p_graph_checksum=publication["checksum"],
        p_active_branch_node_id=None, p_asked_question_node_ids=[],
        p_expected_revision=0,
        p_facts=[{
            "field_key": "nome_cliente", "owner_node_id": owner_node_id,
            "status": "known", "value": client_name,
            "source_message_id": f"validator-seed:{lead_ref}",
            "evidence_span": "", "confidence": 1.0,
        }],
        p_retrieval_trace={}, p_model_proposal={}, p_proof_result={}, p_repair_result={},
        p_final_decision={},
    )


async def run_session_direct(session_id: str) -> dict:
    """Execute through the selected mode using the conversation_v1 contract."""
    session = _session_get(session_id)
    if not session:
        raise ValueError(f"Sessão não encontrada: {session_id}")
    if session["status"] == "running":
        raise ValueError("Sessão já está em execução")

    script = session.get("script", {})
    persona_slug = session.get("persona_slug", "")
    persona = supabase_client.get_persona(persona_slug) or {}
    routing = supabase_client.get_persona_routing(persona_slug) or {}
    conversation_mode = _resolve_conversation_mode(persona.get("id"), routing)
    bindings = supabase_client.get_workflow_bindings(persona.get("id"))
    binding = next(
        (
            row
            for row in bindings
            if row.get("active", True)
            and (row.get("metadata") or {}).get("decision_owner")
            in {"n8n_hybrid", "n8n_agents"}
        ),
        None,
    )
    binding_metadata = (binding or {}).get("metadata") or {}
    workflow_url = str(
        binding_metadata.get("conversation_webhook_url")
        or binding_metadata.get("webhook_url")
        or os.environ.get("N8N_CONVERSATION_TEST_URL")
        or ""
    ).strip()
    if conversation_mode == "n8n_agents" and not workflow_url:
        raise ValueError("Workflow n8n_agents ativo não configurado")
    flow_id = session.get("flow_id", "")
    graph_version = script.get("meta", {}).get("graph_version")
    # Flow name + graph version it was generated against (not just the
    # persona slug) so two validation leads for the same persona are
    # distinguishable at a glance, and a stale run against an old graph
    # version is obvious from the name alone.
    lead_label = f"{flow_id} v{graph_version}" if graph_version is not None else flow_id
    lead = supabase_client.ensure_lead_for_persona(
        lead_id=f"validator_{session_id[:8]}",
        persona_slug_or_id=persona_slug,
        nome=lead_label,
        stage="novo",
        canal="whatsapp",
    ) or {}
    lead_ref = lead.get("id")
    if not lead_ref:
        raise ValueError("Não foi possível criar o lead de validação")
    supabase_client.update_lead(
        lead_ref,
        {
            "metadata": {
                **dict(lead.get("metadata") or {}),
                "validation": {
                    "is_validation": True,
                    "source": "webscraping",
                    "run_id": session_id,
                    "session_id": session_id,
                },
            }
        },
    )
    channel_binding_id = (supabase_client.get_lead_by_ref(lead_ref) or {}).get(
        "channel_binding_id"
    )
    if not channel_binding_id:
        raise ValueError(
            f"Lead de validação para {persona_slug} não recebeu channel_binding_id "
            "automático; configure um workflow_binding ativo para a persona."
        )
    initial_state = script.get("meta", {}).get("initial_state", "cold")
    if initial_state == "known_name":
        _seed_known_name(
            persona=persona, lead_ref=int(lead_ref),
            client_name=str(script.get("expected_dialogue", {}).get("known_name") or ""),
        )
    steps = script.get("steps", [])

    _session_update(session_id, status="running", output={"conversation": [], "status": "running"})

    conversation: list[dict] = []

    async def _do_run() -> None:
        import logging as _logging
        _log = _logging.getLogger("wa_validator_service.direct")
        try:
            token = (os.environ.get("AI_BRAIN_WEBHOOK_TOKEN") or "").strip()
            for i, step in enumerate(steps):
                if "backdate_hours" in step:
                    hours = float(step["backdate_hours"])
                    shifted = supabase_client.backdate_lead_messages(int(lead_ref), hours)
                    conversation.append({
                        "role": "system",
                        "text": f"[backdated {shifted} message(s) by {hours}h]",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "message_id": f"validator:{session_id}:{i}:backdate",
                    })
                    _session_update(session_id, output={"conversation": list(conversation), "status": "running"})
                    continue
                text = step.get("text", "")
                configured_wait = float(step.get("wait", 10) or 10)
                ts_now = datetime.now(timezone.utc).isoformat()
                message_id = f"validator:{session_id}:{i}"
                correlation_id = f"validator:{session_id}:{i}"
                messages_before = len(supabase_client.get_messages(str(lead_ref), limit=200) or [])
                conversation.append({
                    "role": "validator",
                    "text": text,
                    "ts": ts_now,
                    "message_id": message_id,
                })
                # commit() claims the inbound message through the same
                # durable lead_buffer row the real inbound webhooks create
                # (claim_conversation_commit requires it to already exist),
                # so the validator must go through the same atomic
                # enqueue used in production rather than a bare message
                # insert.
                envelope = supabase_client.enqueue_whatsapp_envelope(
                    buffer={
                        "persona_id": persona.get("id"),
                        "lead_ref": lead_ref,
                        "channel_binding_id": channel_binding_id,
                        "whatsapp_phone_number_id": None,
                        "external_message_id": message_id,
                        "direction": "inbound",
                        "payload": {"text": text, "sender": "wa-validator"},
                        "status": "buffered",
                        "batch_key": f"{persona.get('id')}:{lead_ref}",
                        "idempotency_key": f"inbound:wa-validator:{message_id}",
                        "correlation_id": correlation_id,
                    },
                    message={
                        "lead_id": lead_ref,
                        "role": "user",
                        "content": text,
                        "direction": "inbound",
                        "status": "buffered",
                        "channel": "whatsapp",
                        "sender_id": "wa-validator",
                        "external_message_id": message_id,
                        "channel_binding_id": channel_binding_id,
                        "correlation_id": correlation_id,
                        "metadata": {"provider": "wa-validator"},
                        "created_at": ts_now,
                    },
                )
                buffer_uuid = str(envelope.get("buffer_id") or "")
                _session_update(session_id, output={"conversation": list(conversation), "status": "running"})
                try:
                    # Confirmed live 2026-08-08: hardcoding "conversation_v1"
                    # here got every Aurora n8n_agents step rejected by the
                    # workflow's own "pipeline contract mismatch" guard --
                    # the deployed workflow expects whatever the binding
                    # itself declares, exactly like real dispatch
                    # (workers.whatsapp_dispatch_worker) already resolves it.
                    pipeline_contract = (
                        binding_metadata.get("pipeline_contract") or "conversation_v3"
                        if conversation_mode == "n8n_agents"
                        else "conversation_v1"
                    )
                    event = {
                            "persona_slug": persona_slug,
                            "lead_ref": lead_ref,
                            "buffer_id": buffer_uuid,
                            "external_message_id": message_id,
                            "correlation_id": correlation_id,
                            "phone_number_id": None,
                            "channel_binding_id": channel_binding_id,
                            "message": text,
                            "pipeline_contract": pipeline_contract,
                            "decision_owner": conversation_mode,
                        }
                    if conversation_mode == "n8n_agents":
                        # Reuse the exact same client the real dispatch
                        # worker uses (workers.whatsapp_dispatch_worker)
                        # instead of a hand-rolled httpx call -- the
                        # previous inline version built headers = {} even
                        # when a token was configured, so it silently
                        # never sent X-Webhook-Token at all.
                        status, body = await asyncio.to_thread(
                            n8n_client.send_to_webhook,
                            workflow_url,
                            event,
                            secret=token or None,
                            timeout=45.0,
                            # send_to_webhook truncates its return value to
                            # this many chars -- workers.whatsapp_dispatch_
                            # worker only wants a short log preview, but this
                            # caller parses the WHOLE body as JSON. Confirmed
                            # live 2026-08-08: reusing the worker's 65_536
                            # preview limit here truncated real Aurora
                            # replies mid-string, turning a working turn into
                            # a bogus JSONDecodeError. Large enough that no
                            # realistic conversation turn is ever cut off.
                            response_limit=5_000_000,
                        )
                        if status >= 400:
                            raise RuntimeError(
                                f"n8n webhook returned HTTP {status}: {body[:500]}"
                            )
                        if not body.strip():
                            raise RuntimeError(
                                f"n8n webhook returned HTTP {status} with an "
                                "empty body -- the workflow likely isn't "
                                "reaching its Respond to Webhook node"
                            )
                        data = json.loads(body)
                    else:
                        data = conversation_runtime.execute_pipeline(
                            persona_slug=persona_slug,
                            lead_ref=int(lead_ref),
                            message=text,
                            message_id=message_id,
                            correlation_id=correlation_id,
                            phone_number_id=None,
                            channel_binding_id=channel_binding_id,
                            inbound_buffer_id=event["buffer_id"],
                        )
                    reply: str = data.get("reply_text") or ""
                    turn: dict = {
                        "role": "bot",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "agent": script.get("meta", {}).get("agent_slug"),
                        "route": data.get("route"),
                        "intent": data.get("intent"),
                        "handoff": data.get("handoff"),
                        "message_id": data.get("message_id"),
                        "classifier": data.get("classifier"),
                        "conversation_mode": conversation_mode,
                        "pipeline_contract": data.get("pipeline_contract")
                        or "conversation_v1",
                        "evidence_node_ids": data.get("evidence_node_ids")
                        or [],
                        "graph_version": data.get("graph_version")
                        or script.get("meta", {}).get("graph_version"),
                        "graph_checksum": data.get("graph_checksum")
                        or script.get("meta", {}).get("graph_checksum"),
                    }
                    if reply:
                        turn["text"] = reply
                    else:
                        turn["text"] = "(sem resposta — agente não gerou reply)"
                        turn["timeout"] = True
                except Exception as exc:
                    tb = traceback.format_exc()
                    _log.error(
                        "Step %d %s pipeline failed:\n%s", i, conversation_mode, tb
                    )
                    turn = {
                        "role": "bot",
                        "text": f"(erro: {exc})",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "error": True,
                        "error_detail": tb,
                    }

                conversation.append(turn)
                _session_update(session_id, output={"conversation": list(conversation), "status": "running"})

                if i < len(steps) - 1:
                    await _wait_for_reply_delivered(
                        int(lead_ref), messages_before, max_wait_s=max(configured_wait, 20.0),
                    )

            final_output = {"conversation": conversation, "status": "done"}
            _session_update(session_id, status="done", output=final_output)

            supabase_client.insert_event({
                "event_type": "wa_validator_direct_done",
                "payload": {
                    "session_id": session_id,
                    "persona_slug": persona_slug,
                    "n_turns": len(conversation),
                    "graph_version": script.get("meta", {}).get("graph_version"),
                    "graph_checksum": script.get("meta", {}).get("graph_checksum"),
                    "conversation_mode": conversation_mode,
                    "classifier": "deterministic_v1",
                    "pipeline_contract": (
                        binding_metadata.get("pipeline_contract") or "conversation_v3"
                        if conversation_mode == "n8n_agents"
                        else "conversation_v1"
                    ),
                },
            })

        except Exception as exc:
            _session_update(session_id, status="error", error=str(exc))

    task = asyncio.create_task(_do_run())
    # CLI and container QA runs have no long-lived ASGI loop after the command
    # returns. Opt in to awaiting the deterministic scenario there, while the
    # API route retains its non-blocking behaviour by default.
    if os.environ.get("WA_VALIDATOR_DIRECT_WAIT", "").strip().lower() in {"1", "true", "yes"}:
        await task
    return get_session(session_id)


def _persona_business_model(persona_slug: str) -> str | None:
    """The persona's declared business_model, or None if it can't be resolved.

    Reuses conversation_runtime._business_model -- the same field the
    runtime itself gates appointment vs. sales behavior on -- rather than
    re-deriving it here. None (not a default) lets callers fail open when
    the graph isn't loadable, since this is a UX filter, not a security
    boundary.
    """
    try:
        _version, _checksum, graph = _published_graph(persona_slug)
        return conversation_runtime._business_model(graph)
    except Exception:
        return None


def flows(persona_slug: str | None = None) -> list:
    business_model = _persona_business_model(persona_slug) if persona_slug else None
    return [
        {"id": k, "label": v.split(":")[0]}
        for k, v in _FLOWS.items()
        if business_model is None
        or not _FLOW_BUSINESS_MODELS.get(k)
        or business_model in _FLOW_BUSINESS_MODELS[k]
    ]
