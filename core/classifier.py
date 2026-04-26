import os
import json
import anthropic
from schemas.context import Context
from pathlib import Path

_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_PROMPT = (Path(__file__).parent.parent / "prompts" / "classifier.md").read_text(encoding="utf-8")

_SCHEMA = {
    "intent": "string",
    "interest_level": "baixo | medio | alto",
    "urgency": "baixa | media | alta",
    "fit": "ruim | neutro | bom",
    "objections": "array of strings",
    "summary": "string",
    "route_hint": "SDR | CLOSER | FOLLOW_UP | SUPPORT | PRODUCT_SPEC",
}


def classify(ctx: Context) -> dict:
    history_text = "\n".join(
        f"[{m.get('sender_type','?')}] {m.get('texto','')}"
        for m in ctx.historico[-10:]
    )

    classifier_input = (
        f"INFORMAÇÕES DO LEAD:\n"
        f"Nome: {ctx.lead.nome or 'não informado'}\n"
        f"Produto de interesse: {ctx.lead.interesse_produto or 'não informado'}\n"
        f"Stage atual: {ctx.lead.stage}\n"
        f"Canal: {ctx.lead.canal}\n"
        f"Cidade: {ctx.lead.cidade or 'não informada'}\n"
        f"CEP: {ctx.lead.cep or 'não informado'}\n\n"
        f"MENSAGEM DO LEAD:\n{ctx.mensagem}\n\n"
        f"HISTÓRICO:\n{history_text or 'sem histórico'}"
    )

    prompt = _PROMPT.replace("{{classifier_input}}", classifier_input)

    message = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {
            "intent": "duvida_geral",
            "interest_level": "medio",
            "urgency": "baixa",
            "fit": "neutro",
            "objections": [],
            "summary": "Classificação falhou — usando defaults",
            "route_hint": "SDR",
        }
