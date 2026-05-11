# -*- coding: utf-8 -*-
"""
WA Validator Service — generates test scripts from KB, tracks validation sessions,
and analyses conversation gaps to feed back into KB Intake.
"""

import asyncio
import httpx
import json
import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from services import supabase_client
from services.model_router import AVAILABLE_MODELS, get_router

_MODEL_DEFAULT = "gpt-4o-mini"
_WA_BOT_DIR = os.environ.get("WA_BOT_DIR", r"C:\Users\Alan\Documents\repositorios\wa-wscrap-bot")
_WA_PYTHON  = os.environ.get("WA_PYTHON", r"C:\Users\Alan\Documents\repositorios\wa-wscrap-bot\.venv\Scripts\python.exe")
_BRAIN_API_URL = os.environ.get("BRAIN_API_URL", "http://localhost:8000")

# In-memory session store  {session_id: session_dict}
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

# ── Bot registry ───────────────────────────────────────────────────────────────
_BOT_REGISTRY: list[dict] = []


def bots() -> list:
    """Return available bots: static registry + any active personas not yet listed."""
    result = list(_BOT_REGISTRY)
    registered = {b["persona_slug"] for b in _BOT_REGISTRY}
    try:
        for p in supabase_client.get_personas():
            slug = p.get("slug", "")
            if slug and slug not in registered:
                result.append({
                    "id": slug,
                    "bot_name": p.get("name", slug),
                    "label": p.get("name", slug),
                    "persona_slug": slug,
                    "description": p.get("description", ""),
                })
                registered.add(slug)
    except Exception:
        pass
    return result


def _chat(model: str, prompt: str, max_tokens: int = 1024) -> str:
    return get_router().chat(model, prompt, max_tokens)

_FLOWS = {
    "compra_simples": "Fluxo de compra simples: cliente pergunta sobre produto, recebe info, confirma compra.",
    "duvida_frete": "Fluxo de dúvida sobre frete/entrega: cliente pergunta prazo e valor de frete.",
    "saudacao_despedida": "Fluxo básico: saudação, pergunta simples, despedida.",
    "produto_especifico": "Fluxo de produto específico: cliente nomeia produto, bot responde com detalhes e CTA.",
    "reclamacao": "Fluxo de reclamação/insatisfação: cliente reclama, bot reconhece e escalona.",
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


def _build_kb_context(persona_id: str) -> str:
    entries = supabase_client.get_kb_entries(persona_id=persona_id, status="ATIVO")
    if not entries:
        return "(base de conhecimento vazia)"

    sections: dict[str, list[str]] = {}
    for e in entries:
        tipo = e.get("tipo", "geral")
        text = f"[{e.get('titulo', '')}] {e.get('conteudo', '')}"
        sections.setdefault(tipo, []).append(text)

    lines: list[str] = []
    priority = ["brand", "tom", "produto", "regra", "faq"]
    order = priority + [k for k in sections if k not in priority]
    for tipo in order:
        if tipo not in sections:
            continue
        lines.append(f"### {tipo.upper()}")
        for item in sections[tipo][:5]:
            lines.append(f"- {item[:300]}")

    return "\n".join(lines)


def _generate_script_with_openai(
    persona_name: str,
    kb_ctx: str,
    flow_id: str,
    model: str,
) -> dict:
    flow_desc = _FLOWS.get(flow_id, flow_id)
    prompt = f"""Você é um analista de QA para um bot de vendas via WhatsApp.
Crie um script de conversa de validação para testar se o bot conhece bem os produtos e processos do cliente.

=== CLIENTE ===
{persona_name}

=== BASE DE CONHECIMENTO ===
{kb_ctx}

=== FLUXO A TESTAR ===
{flow_desc}

Gere um script JSON com exatamente 5 a 8 mensagens que um cliente real enviaria.
Cada mensagem deve testar se o bot conhece informações da base de conhecimento.
Use linguagem informal e natural, como um cliente de verdade no WhatsApp.

Responda APENAS com JSON válido nesse formato:
{{
  "flow_description": "descrição do que está sendo testado",
  "expected_knowledge": ["item 1 que o bot deve saber", "item 2", ...],
  "steps": [
    {{"text": "mensagem do cliente", "wait": 15}},
    ...
  ]
}}

Não use markdown. JSON puro começando com {{."""

    raw = _chat(model, prompt)
    return _extract_json(raw)


def generate_script(
    persona_slug: str,
    flow_id: str,
    target_contact: str,
    model: str = _MODEL_DEFAULT,
) -> dict:
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise ValueError(f"Persona não encontrada: {persona_slug}")

    persona_id = persona["id"]
    persona_name = persona.get("name", persona_slug)
    kb_ctx = _build_kb_context(persona_id)

    script_data = _generate_script_with_openai(persona_name, kb_ctx, flow_id, model)

    session_id = str(uuid.uuid4())
    script = {
        "meta": {
            "persona": persona_slug,
            "persona_name": persona_name,
            "flow": flow_id,
            "session_id": session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
        },
        "target": target_contact,
        "flow_description": script_data.get("flow_description", ""),
        "expected_knowledge": script_data.get("expected_knowledge", []),
        "steps": script_data.get("steps", []),
    }

    with _sessions_lock:
        _sessions[session_id] = {
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
        }

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
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Sessão não encontrada: {session_id}")
    if session["status"] == "running":
        raise ValueError("Sessão já está em execução")

    script_path = os.path.join(_WA_BOT_DIR, f"_validator_script_{session_id[:8]}.json")
    output_path = os.path.join(_WA_BOT_DIR, f"_validator_output_{session_id[:8]}.json")

    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(session["script"], f, ensure_ascii=False, indent=2)

    def _run():
        import logging as _logging
        _log = _logging.getLogger("wa_validator_service")
        try:
            python_bin = _WA_PYTHON if os.path.exists(_WA_PYTHON) else "python"
            cmd = [python_bin, "wa_validator.py", "--script", script_path, "--output", output_path]
            _log.info("Iniciando subprocess: %s", " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                cwd=_WA_BOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with _sessions_lock:
                _sessions[session_id]["pid"] = proc.pid
                _sessions[session_id]["status"] = "running"
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            stdout_data, _ = proc.communicate()

            if stdout_data:
                _log.info("wa_validator stdout [%s]:\n%s", session_id[:8], stdout_data[-3000:])

            output = {}
            if os.path.exists(output_path):
                with open(output_path, encoding="utf-8") as f:
                    output = json.load(f)

            if not output and proc.returncode != 0:
                final_status = "error"
                error_msg = f"Processo encerrou com código {proc.returncode}.\nLog:\n{stdout_data[-2000:] if stdout_data else '(sem saída)'}"
            else:
                final_status = output.get("status", "done")
                error_msg = output.get("error", "")

            with _sessions_lock:
                _sessions[session_id]["output"] = output
                _sessions[session_id]["status"] = final_status
                _sessions[session_id]["error"] = error_msg
                _sessions[session_id]["log"] = stdout_data[-4000:] if stdout_data else ""
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

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
            with _sessions_lock:
                _sessions[session_id]["status"] = "error"
                _sessions[session_id]["error"] = str(e)
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    with _sessions_lock:
        _sessions[session_id]["status"] = "starting"
        _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    return get_session(session_id)


def get_session(session_id: str) -> dict:
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Sessão não encontrada: {session_id}")

    output_path = os.path.join(_WA_BOT_DIR, f"_validator_output_{session_id[:8]}.json")
    if session["status"] in ("running", "starting") and os.path.exists(output_path):
        try:
            with open(output_path, encoding="utf-8") as f:
                partial = json.load(f)
            with _sessions_lock:
                _sessions[session_id]["output"] = partial
        except Exception:
            pass

    with _sessions_lock:
        return dict(_sessions[session_id])


def list_sessions() -> list:
    with _sessions_lock:
        return [dict(s) for s in sorted(
            _sessions.values(),
            key=lambda x: x["created_at"],
            reverse=True,
        )]


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

    conv_text = "\n".join(
        f"{turn['role'].upper()}: {turn.get('text', '(sem resposta)')}"
        for turn in conversation
    )
    expected_str = "\n".join(f"- {e}" for e in expected)

    prompt = f"""Analise esta conversa de validação de um bot de vendas WhatsApp.

=== CONHECIMENTO ESPERADO ===
{expected_str}

=== CONVERSA REGISTRADA ===
{conv_text}

Identifique:
1. Quais conhecimentos o bot demonstrou corretamente
2. Quais conhecimentos estão faltando ou incorretos (gaps)
3. Recomendações para preencher os gaps na base de conhecimento

Responda APENAS com JSON:
{{
  "demonstrated": ["conhecimento 1 que o bot demonstrou", ...],
  "gaps": [
    {{"topic": "tópico ausente", "evidence": "o bot respondeu X quando deveria saber Y", "priority": "high/medium/low"}},
    ...
  ],
  "recommendations": ["recomendação 1 para a base de conhecimento", ...],
  "overall_score": 0-100,
  "summary": "resumo de 2 linhas"
}}"""

    raw = _chat(model, prompt)
    parsed = _extract_json(raw)

    # Merge parsed result over defaults so any missing key never reaches the frontend as undefined
    insights = {
        **_EMPTY_INSIGHTS,
        **{k: v for k, v in parsed.items() if v is not None},
        "session_id": session_id,
        "persona_slug": persona_slug,
    }

    with _sessions_lock:
        _sessions[session_id]["insights"] = insights
        _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

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


async def run_session_direct(session_id: str) -> dict:
    """
    Execute a validation session by calling the platform's own /process endpoint
    for each script step — no WhatsApp connection required.
    Each bot reply comes from the real AI pipeline (context_builder → classifier
    → decision_engine → SDR/CLOSER agent).
    """
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session:
        raise ValueError(f"Sessão não encontrada: {session_id}")
    if session["status"] == "running":
        raise ValueError("Sessão já está em execução")

    script = session.get("script", {})
    persona_slug = session.get("persona_slug", "global")
    steps = script.get("steps", [])
    # Use a stable, readable lead_id for test messages in Supabase
    test_lead_id = f"validator_{session_id[:8]}"

    with _sessions_lock:
        _sessions[session_id]["status"] = "running"
        _sessions[session_id]["output"] = {"conversation": [], "status": "running"}
        _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    conversation: list[dict] = []

    async def _do_run() -> None:
        import logging as _logging
        _log = _logging.getLogger("wa_validator_service.direct")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                for i, step in enumerate(steps):
                    text = step.get("text", "")
                    wait_s = min(step.get("wait", 10), 3)

                    ts_now = datetime.now(timezone.utc).isoformat()
                    conversation.append({
                        "role": "validator",
                        "text": text,
                        "ts": ts_now,
                    })
                    # Save validator's message to Supabase so conversation is visible
                    try:
                        supabase_client.insert_message({
                            "message_id": f"val_{session_id[:8]}_{i}",
                            "sender_type": "user",
                            "canal": "whatsapp",
                            "texto": text,
                            "direction": "Inbounding",
                            "Lead_Stage": "teste",
                            "nome": f"Validador [{persona_slug}]",
                            "created_at": ts_now,
                        })
                    except Exception as e:
                        _log.debug("Could not save validator message: %s", e)

                    with _sessions_lock:
                        _sessions[session_id]["output"] = {
                            "conversation": list(conversation), "status": "running"
                        }

                    try:
                        resp = await client.post(
                            f"{_BRAIN_API_URL}/process",
                            json={
                                "lead_id": test_lead_id,
                                "nome": f"Validador [{persona_slug}]",
                                "stage": "novo",
                                "canal": "whatsapp",
                                "mensagem": text,
                                "persona_slug": persona_slug,
                            },
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        reply: str = data.get("reply") or ""
                        turn: dict = {
                            "role": "bot",
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "agent": data.get("agent_used", ""),
                            "latency_ms": data.get("latency_ms"),
                        }
                        if reply:
                            turn["text"] = reply
                        else:
                            turn["text"] = "(sem resposta — agente não gerou reply)"
                            turn["timeout"] = True
                    except Exception as exc:
                        _log.error("Step %d /process call failed: %s", i, exc)
                        turn = {
                            "role": "bot",
                            "text": f"(erro: {exc})",
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "timeout": True,
                        }

                    conversation.append(turn)
                    with _sessions_lock:
                        _sessions[session_id]["output"] = {
                            "conversation": list(conversation), "status": "running"
                        }

                    if i < len(steps) - 1:
                        await asyncio.sleep(wait_s)

            final_output = {"conversation": conversation, "status": "done"}
            with _sessions_lock:
                _sessions[session_id]["status"] = "done"
                _sessions[session_id]["output"] = final_output
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            supabase_client.insert_event({
                "event_type": "wa_validator_direct_done",
                "payload": {
                    "session_id": session_id,
                    "persona_slug": persona_slug,
                    "n_turns": len(conversation),
                },
            })

        except Exception as exc:
            with _sessions_lock:
                _sessions[session_id]["status"] = "error"
                _sessions[session_id]["error"] = str(exc)
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    asyncio.create_task(_do_run())
    return get_session(session_id)


def flows() -> list:
    return [{"id": k, "label": v.split(":")[0]} for k, v in _FLOWS.items()]
