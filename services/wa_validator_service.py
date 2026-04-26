# -*- coding: utf-8 -*-
"""
WA Validator Service — generates test scripts from KB, tracks validation sessions,
and analyses conversation gaps to feed back into KB Intake.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import anthropic

from services import supabase_client

_MODEL_DEFAULT = "claude-haiku-4-5-20251001"
_WA_BOT_DIR = os.environ.get("WA_BOT_DIR", r"C:\Users\Alan\Documents\repositorios\wa-wscrap-bot")

# In-memory session store  {session_id: session_dict}
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

AVAILABLE_MODELS = {
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5 — Rápido",
    "claude-sonnet-4-6": "Claude Sonnet 4.6 — Balanceado",
    "claude-opus-4-7": "Claude Opus 4.7 — Mais capaz",
}

_FLOWS = {
    "compra_simples": "Fluxo de compra simples: cliente pergunta sobre produto, recebe info, confirma compra.",
    "duvida_frete": "Fluxo de dúvida sobre frete/entrega: cliente pergunta prazo e valor de frete.",
    "saudacao_despedida": "Fluxo básico: saudação, pergunta simples, despedida.",
    "produto_especifico": "Fluxo de produto específico: cliente nomeia produto, bot responde com detalhes e CTA.",
    "reclamacao": "Fluxo de reclamação/insatisfação: cliente reclama, bot reconhece e escalona.",
}


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


def _generate_script_with_claude(
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

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


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

    script_data = _generate_script_with_claude(persona_name, kb_ctx, flow_id, model)

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
        try:
            proc = subprocess.Popen(
                ["python", "wa_validator.py", "--script", script_path, "--output", output_path],
                cwd=_WA_BOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with _sessions_lock:
                _sessions[session_id]["pid"] = proc.pid
                _sessions[session_id]["status"] = "running"
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            proc.wait()

            output = {}
            if os.path.exists(output_path):
                with open(output_path, encoding="utf-8") as f:
                    output = json.load(f)

            with _sessions_lock:
                _sessions[session_id]["output"] = output
                _sessions[session_id]["status"] = output.get("status", "done")
                _sessions[session_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            supabase_client.insert_event({
                "event_type": "wa_validator_session_done",
                "payload": {
                    "session_id": session_id,
                    "status": output.get("status"),
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

    if not conversation:
        return {"gaps": [], "summary": "Sem conversa para analisar.", "session_id": session_id}

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

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    insights = json.loads(raw)
    insights["session_id"] = session_id
    insights["persona_slug"] = persona_slug

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


def flows() -> list:
    return [{"id": k, "label": v.split(":")[0]} for k, v in _FLOWS.items()]
