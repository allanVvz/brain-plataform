# -*- coding: utf-8 -*-
"""
Marketing — text generation for marketing copy, ads, emails, social, etc.

Distinct from /generate (which is for Figma campaign cards):
- This route is text-only and persona-aware.
- Backed by ModelRouter (OpenAI cascade + Anthropic fallback).
- System prompts are distilled from the curated marketing skills:
  copywriting, marketing-psychology, customer-research, content-strategy,
  cold-email, email-sequence, ad-creative, lead-magnets, social-content.

Output is plain text/markdown so the dashboard can render and (optionally)
persist as a knowledge_items row of content_type=copy.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import supabase_client
from services.model_router import ModelRouter, ModelRouterError, AVAILABLE_MODELS

logger = logging.getLogger("marketing")

router = APIRouter(prefix="/marketing", tags=["marketing"])


# ── Mode catalog ──────────────────────────────────────────────────────────
# Each mode maps to a system-prompt template. The template is distilled from
# the corresponding marketing skill (see ~/.claude/skills-staging) and adapted
# for the AI Brain context (persona-aware, structured output).
#
# Adding a new mode is a single dict entry — no other code changes required.

class ModeSpec(BaseModel):
    key: str
    label: str
    description: str
    inputs: list[dict]  # [{name, label, placeholder, type:"text"|"textarea"|"select", required?}]
    system_prompt: str
    user_prompt_template: str


def _persona_block(persona_id: Optional[str]) -> str:
    """Build a persona context block to prepend to the system prompt.

    Pulls brand/tone/product/briefing nodes from the knowledge graph so the
    output matches the persona's voice and catalog. Best-effort — empty
    block when graph is unavailable or persona is None.
    """
    if not persona_id:
        return ""
    try:
        # Brand + tone + briefing summaries set voice/positioning context.
        canonical = supabase_client.list_knowledge_nodes_by_type(
            ["brand", "tone", "briefing", "rule"], persona_id=persona_id, limit=20,
        ) or []
        # Top products give the catalog that copy can reference.
        products = supabase_client.list_knowledge_nodes_by_type(
            ["product"], persona_id=persona_id, limit=12,
        ) or []
    except Exception as exc:
        logger.warning("persona_block fetch failed: %s", exc)
        return ""

    if not canonical and not products:
        return ""

    parts: list[str] = []
    if canonical:
        parts.append("## Contexto da marca / tom / regras (não inventar — só usar):")
        for n in canonical:
            title = (n.get("title") or n.get("slug") or "").strip()
            summary = (n.get("summary") or "").strip()[:300]
            ntype = n.get("node_type")
            if title:
                parts.append(f"- **[{ntype}] {title}**" + (f": {summary}" if summary else ""))
    if products:
        parts.append("\n## Produtos/ofertas catalogadas:")
        for n in products:
            title = (n.get("title") or n.get("slug") or "").strip()
            meta = n.get("metadata") or {}
            facts: list[str] = []
            price = meta.get("price") or {}
            if price.get("display"):
                facts.append(price["display"])
            if meta.get("colors_count") is not None:
                facts.append(f"{meta['colors_count']} cores")
            url = meta.get("catalog_url") or meta.get("url")
            extra = f" — {', '.join(facts)}" if facts else ""
            extra += f" — {url}" if url else ""
            parts.append(f"- {title}{extra}")
    return "\n".join(parts) + "\n"


# Skill-distilled system prompts. Each is concise (~150 words) and assumes
# the persona block is appended above it at call-time.
_BASE_VOICE = (
    "Você é um copywriter senior que escreve em português brasileiro coloquial "
    "e direto. Nunca invente fatos sobre produto, preço ou política — use só o "
    "que estiver no contexto da persona. Quando faltar dado, pergunte ao "
    "operador em vez de chutar."
)

_MODES: dict[str, ModeSpec] = {
    "copywriting": ModeSpec(
        key="copywriting",
        label="Copy de Produto",
        description="Texto de venda/oferta para um produto específico, baseado em ângulos psicológicos e preço estruturado.",
        inputs=[
            {"name": "product",   "label": "Produto",   "type": "text",     "placeholder": "Ex.: Higienização de Cadeiras Prime",  "required": True},
            {"name": "audience",  "label": "Público",   "type": "text",     "placeholder": "Ex.: donas de casa em Novo Hamburgo"},
            {"name": "angle",     "label": "Ângulo",    "type": "select",   "options": ["benefício", "dor", "prova social", "urgência", "preço/valor"]},
            {"name": "format",    "label": "Formato",   "type": "select",   "options": ["headline + parágrafo", "post Instagram", "anúncio Meta Ads", "WhatsApp"]},
            {"name": "extra",     "label": "Notas",     "type": "textarea", "placeholder": "Ex.: enfatizar regional, tom seguro"},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Sua tarefa é escrever copy de venda baseado em ângulo psicológico claro. "
            "Estruture: (1) headline curta com tensão; (2) corpo com 1 benefício + 1 prova "
            "concreta; (3) CTA específico (não 'saiba mais'). Use o preço estruturado quando "
            "houver. Saída em markdown."
        ),
        user_prompt_template=(
            "Produto: {product}\n"
            "Público: {audience}\n"
            "Ângulo: {angle}\n"
            "Formato: {format}\n"
            "Notas adicionais: {extra}\n\n"
            "Gere a copy."
        ),
    ),

    "cold_email": ModeSpec(
        key="cold_email",
        label="E-mail Frio (cold email)",
        description="Sequência inicial de outreach personalizada. Curto, com gancho relevante e CTA único.",
        inputs=[
            {"name": "target",     "label": "Lead/empresa", "type": "text",     "placeholder": "Cargo ou nome do contato + empresa", "required": True},
            {"name": "hook",       "label": "Gancho",        "type": "textarea", "placeholder": "Algo específico observado (post, vaga, evento)"},
            {"name": "offer",      "label": "Oferta",        "type": "text",     "placeholder": "Ex.: Demo de 15min mostrando X"},
            {"name": "tone",       "label": "Tom",           "type": "select",   "options": ["formal", "informal", "consultivo"]},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Escreva e-mail frio que segue: (1) linha de assunto com curiosidade ou benefício "
            "específico (≤8 palavras); (2) primeira frase referenciando o gancho; (3) 2-3 frases "
            "conectando o gancho à oferta; (4) CTA único e fácil (nunca múltiplas perguntas); "
            "(5) PS opcional com prova social. Total ≤ 120 palavras. Saída como bloco "
            "markdown com Subject: e Body:."
        ),
        user_prompt_template=(
            "Lead: {target}\n"
            "Gancho observado: {hook}\n"
            "Oferta: {offer}\n"
            "Tom: {tone}\n\n"
            "Escreva o e-mail frio."
        ),
    ),

    "email_sequence": ModeSpec(
        key="email_sequence",
        label="Sequência de E-mail",
        description="Série de 3-5 e-mails para nurture/onboarding/recovery, com progressão lógica.",
        inputs=[
            {"name": "goal",     "label": "Objetivo",  "type": "select",   "options": ["nurture", "onboarding", "carrinho abandonado", "winback", "lead magnet follow-up"], "required": True},
            {"name": "audience", "label": "Público",   "type": "text",     "placeholder": "Ex.: leads que baixaram o lead magnet"},
            {"name": "count",    "label": "Quantos e-mails", "type": "select", "options": ["3", "5", "7"]},
            {"name": "extra",    "label": "Notas",     "type": "textarea"},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Construa uma sequência numerada onde cada e-mail tem um único objetivo "
            "psicológico (educar → engajar → desejo → urgência → CTA). Para cada e-mail: "
            "subject, preview text, body curto (≤80 palavras), CTA. Mostre o intervalo "
            "sugerido entre cada (ex.: D+0, D+2, D+4). Markdown."
        ),
        user_prompt_template=(
            "Objetivo: {goal}\n"
            "Público: {audience}\n"
            "Quantidade: {count} e-mails\n"
            "Notas: {extra}\n\n"
            "Construa a sequência."
        ),
    ),

    "ad_creative": ModeSpec(
        key="ad_creative",
        label="Anúncio (Meta/Google Ads)",
        description="Variantes de criativo para teste A/B com múltiplos ângulos e formatos.",
        inputs=[
            {"name": "product",  "label": "Produto",   "type": "text", "required": True},
            {"name": "platform", "label": "Plataforma","type": "select", "options": ["Meta Feed", "Meta Stories", "Google Search", "Google Display", "TikTok"]},
            {"name": "variants", "label": "Variantes", "type": "select", "options": ["3", "5", "8"]},
            {"name": "extra",    "label": "Notas",     "type": "textarea"},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Gere variantes de criativo, cada uma com ângulo distinto (benefício, dor, "
            "comparação, prova social, urgência). Para cada variante: headline, descrição "
            "(respeitando limite da plataforma), CTA. Anote qual ângulo psicológico cada "
            "variante explora. Saída como tabela markdown."
        ),
        user_prompt_template=(
            "Produto: {product}\n"
            "Plataforma: {platform}\n"
            "Variantes: {variants}\n"
            "Notas: {extra}\n\n"
            "Gere as variantes."
        ),
    ),

    "lead_magnet": ModeSpec(
        key="lead_magnet",
        label="Lead Magnet",
        description="Idéia + outline para um lead magnet (e-book, checklist, calculadora) que captura e qualifica.",
        inputs=[
            {"name": "audience", "label": "Público-alvo", "type": "text", "required": True},
            {"name": "pain",     "label": "Dor principal", "type": "textarea", "required": True},
            {"name": "format",   "label": "Formato",      "type": "select", "options": ["checklist", "e-book", "template", "calculadora", "mini-curso"]},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Proponha um lead magnet que: (1) tenha título com ganho específico no nome; "
            "(2) outline em 5-8 seções; (3) exemplo de hook na intro; (4) call to action de "
            "upgrade no final que conecta ao produto. Markdown."
        ),
        user_prompt_template=(
            "Público: {audience}\n"
            "Dor: {pain}\n"
            "Formato: {format}\n\n"
            "Proponha o lead magnet completo."
        ),
    ),

    "social_content": ModeSpec(
        key="social_content",
        label="Posts de Social",
        description="Bateria de posts para feed/Stories alinhados ao tom da marca.",
        inputs=[
            {"name": "platform", "label": "Plataforma", "type": "select", "options": ["Instagram Feed", "Instagram Stories", "LinkedIn", "TikTok caption"]},
            {"name": "theme",    "label": "Tema",       "type": "text", "required": True},
            {"name": "count",    "label": "Quantidade", "type": "select", "options": ["3", "5", "10"]},
            {"name": "extra",    "label": "Notas",      "type": "textarea"},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Gere posts numerados, cada um com objetivo claro (ensinar, vender, engajar, "
            "provar). Use frases curtas, evite jargão, respeite o tom da marca. Para cada post: "
            "tipo (educacional/promo/prova social), texto completo, hashtags se aplicável, CTA. "
            "Markdown."
        ),
        user_prompt_template=(
            "Plataforma: {platform}\n"
            "Tema: {theme}\n"
            "Quantidade: {count}\n"
            "Notas: {extra}\n\n"
            "Gere os posts."
        ),
    ),

    "content_strategy": ModeSpec(
        key="content_strategy",
        label="Estratégia de Conteúdo",
        description="Plano editorial ou pilar de conteúdo orientado a um objetivo de marketing.",
        inputs=[
            {"name": "goal",     "label": "Objetivo",   "type": "select", "options": ["aumentar tráfego", "gerar leads", "nutrir base", "posicionar autoridade", "lançar produto"], "required": True},
            {"name": "audience", "label": "Público",    "type": "text"},
            {"name": "horizon",  "label": "Horizonte",  "type": "select", "options": ["1 mês", "1 trimestre", "6 meses"]},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Construa o plano com: (1) tese/posicionamento; (2) 3 pilares de conteúdo com "
            "exemplos de tópicos; (3) calendário sugerido (ritmo + formatos); (4) métricas "
            "de sucesso por pilar; (5) próximos passos acionáveis. Markdown."
        ),
        user_prompt_template=(
            "Objetivo: {goal}\n"
            "Público: {audience}\n"
            "Horizonte: {horizon}\n\n"
            "Construa o plano."
        ),
    ),

    "marketing_psychology": ModeSpec(
        key="marketing_psychology",
        label="Análise Psicológica",
        description="Aplica gatilhos cognitivos a uma situação de venda, oferta ou objeção.",
        inputs=[
            {"name": "situation", "label": "Situação", "type": "textarea", "required": True, "placeholder": "Cenário, oferta ou objeção a tratar"},
            {"name": "goal",      "label": "Objetivo", "type": "text",     "placeholder": "O que você quer que aconteça depois"},
        ],
        system_prompt=(
            f"{_BASE_VOICE}\n\n"
            "Identifique 3-5 gatilhos psicológicos relevantes (ex.: prova social, "
            "escassez, ancoragem, reciprocidade, autoridade) e mostre como aplicar cada um "
            "para a situação. Para cada: explicação curta + exemplo de frase pronta. Markdown."
        ),
        user_prompt_template=(
            "Situação: {situation}\n"
            "Objetivo: {goal}\n\n"
            "Mostre os gatilhos aplicáveis."
        ),
    ),
}


# ── Schemas ───────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    mode: str = Field(..., description="Key from /marketing/modes")
    inputs: dict = Field(default_factory=dict)
    persona_id: Optional[str] = None
    model: Optional[str] = Field(None, description="OpenAI/Anthropic model id; default gpt-4o-mini")
    max_tokens: int = Field(1500, ge=100, le=4000)


class GenerateResponse(BaseModel):
    content: str
    model_used: Optional[str] = None
    mode: str
    persona_id: Optional[str] = None


class ModeListResponse(BaseModel):
    modes: list[dict]
    available_models: dict[str, str]


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("/modes", response_model=ModeListResponse)
def list_modes():
    """List all creation modes with their input schema. Used by the dashboard
    to render the form dynamically."""
    modes_payload = [
        {
            "key": m.key,
            "label": m.label,
            "description": m.description,
            "inputs": m.inputs,
        }
        for m in _MODES.values()
    ]
    return ModeListResponse(modes=modes_payload, available_models=AVAILABLE_MODELS)


@router.post("/generate", response_model=GenerateResponse)
def generate(body: GenerateRequest):
    spec = _MODES.get(body.mode)
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown mode '{body.mode}'. See /marketing/modes")

    # Build user prompt by templating; missing keys become "(não informado)" so
    # the model still has structure even with partial input.
    safe_inputs = {k: (v if v not in (None, "") else "(não informado)") for k, v in body.inputs.items()}
    try:
        user_prompt = spec.user_prompt_template.format_map(_DefaultDict(safe_inputs))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid inputs: {exc}")

    # Compose system prompt: persona context (if any) + skill prompt.
    persona_block = _persona_block(body.persona_id)
    system_prompt = (persona_block + "\n" if persona_block else "") + spec.system_prompt

    router_ = ModelRouter()
    requested_model = body.model or "gpt-4o-mini"
    try:
        content = router_.messages_create(
            model=requested_model,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            max_tokens=body.max_tokens,
        )
    except ModelRouterError as exc:
        logger.error("marketing.generate exhausted providers: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    return GenerateResponse(
        content=content,
        model_used=requested_model,  # exact router-selected model is logged but not exposed
        mode=body.mode,
        persona_id=body.persona_id,
    )


class _DefaultDict(dict):
    """Format-map helper: missing keys become '(não informado)' instead of KeyError."""
    def __missing__(self, key: str) -> str:
        return "(não informado)"
