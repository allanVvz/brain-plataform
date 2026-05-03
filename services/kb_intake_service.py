"""
KB Intake Service — conversational classifier for knowledge ingestion.
Writes to vault → git commit → sync Supabase.
"""
import os
import base64
import json
import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from services import supabase_client
from services import knowledge_rag_intake
from services.catalog_crawler import crawl_catalog_url
from services.vault_sync import run_sync, VAULT_PATH
from services.model_router import AVAILABLE_MODELS as ROUTER_MODELS
from services.model_router import ModelRouter, ModelRouterError

AVAILABLE_MODELS = {
    **ROUTER_MODELS,
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5 - fallback",
}

_VAULT_CLIENT_FOLDERS = {
    "tock-fatal":        "TOCK_FATAL",
    "vz-lupas":          "VZ_LUPAS",
    "baita-conveniencia":"BAITA_CONVENIENCIA",
    "global":            "00_GLOBAL",
}

_CONTENT_TYPE_FOLDERS = {
    "brand":         "01_BRAND",
    "briefing":      "02_BRIEFING",
    "product":       "03_PRODUCTS",
    "campaign":      "04_CAMPAIGNS",
    "copy":          "05_COPY",
    "faq":           "06_FAQ",
    "tone":          "07_TONE",
    "audience":      "08_AUDIENCE",
    "competitor":    "09_COMPETITORS",
    "rule":          "10_RULES",
    "prompt":        "11_PROMPTS",
    "maker_material":"12_MAKER",
    "asset":         "assets",
    "other":         "00_OTHER",
}

_CONTENT_ALIASES = {
    "faq": "faq", "pergunta": "faq", "perguntas": "faq", "kb": "faq",
    "produto": "product", "product": "product",
    "copy": "copy",
    "campanha": "campaign", "campaign": "campaign",
    "briefing": "briefing",
    "tom": "tone", "tone": "tone",
    "moodboard": "maker_material", "maker": "maker_material",
    "regra": "rule", "rule": "rule",
}

_PERSONA_ALIASES = {
    "tock fatal": "tock-fatal",
    "tock-fatal": "tock-fatal",
    "tock_fatal": "tock-fatal",
    "vz lupas": "vz-lupas",
    "vz-lupas": "vz-lupas",
    "baita conveniencia": "baita-conveniencia",
    "baita conveniência": "baita-conveniencia",
    "baita-conveniencia": "baita-conveniencia",
}

_ASSET_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".mp4", ".pdf", ".ai", ".psd"}

_sessions: dict[str, dict] = {}
_SESSION_DIR = Path(os.environ.get("KB_INTAKE_SESSION_DIR", ".runtime/kb-intake-sessions"))

AGENT_PROFILES = {
    "sofia": {
        "name": "Sofia",
        "role": "agente de inteligencia marketing comercial",
        "greeting": (
            "Olá! Eu sou a **Sofia**. Aprendi bastante sobre marketing para te ajudar "
            "a construir conhecimento para tua marca."
        ),
    },
    "zaya": {
        "name": "Zaya",
        "role": "agente de marketing visual",
        "greeting": (
            "Olá! Eu sou a **Zaya**. Posso te ajudar a transformar conhecimento "
            "visual em direção criativa para tua marca."
        ),
    },
}


def get_agent_profile(agent_key: str | None = None) -> dict:
    return AGENT_PROFILES.get((agent_key or "sofia").strip().lower(), AGENT_PROFILES["sofia"])


_SYSTEM_PROMPT = """Você é uma agente especializada em classificar materiais para a base de conhecimento da plataforma AI Brain.

Sua identidade de conversa vem do estado da sessão. Por padrão, a agente é Sofia, agente de inteligência marketing comercial. Em fluxos futuros, a identidade pode mudar organicamente para Zaya, agente de marketing visual. Nunca se apresente como "Criar"; Criar é o nome da ferramenta/tela, não da agente.

Sua função: conduzir uma conversa objetiva para coletar as informações necessárias de classificação. Seja direto e eficiente. Não utilize mensagens padrão de agradecimento ou explicações sobre o processo técnico de salvamento.

=== CLIENTES DISPONÍVEIS ===
- tock-fatal → Tock Fatal (marca de moda urbana)
- vz-lupas → VZ Lupas (óculos e saúde visual)
- baita-conveniencia → Baita Conveniência (bar e conveniência)
- global → Global (aplicável a todos os clientes)

=== TIPOS DE CONTEÚDO TEXTUAL ===
brand, briefing, product, campaign, copy, faq, tone, audience, competitor, rule, prompt, maker_material, other

=== PARA ASSETS VISUAIS ===
Tipo de asset: background, logo, product, model, banner, story, post, video, icon, other
Função do asset: maker_material, brand_reference, campaign_hero, copy_support, product_showcase, other

=== FLUXO DE CLASSIFICAÇÃO ===
1. Identifique o cliente (obrigatório)
2. Identifique se é asset visual ou conteúdo textual
3. Se asset: pergunte tipo e função
4. Se texto: identifique o tipo de conteúdo
5. Confirme o título (sugira um se não houver)
6. Quando completo, apresente apenas o resumo técnico e aguarde a confirmação de salvamento. NÃO informe que "está realizando o salvamento" ou "agradeço a paciência".

Você consegue extrair múltiplas informações de uma única mensagem. Por exemplo, se o usuário diz "background do Tock Fatal", você já sabe cliente=tock-fatal, content_type=asset, asset_type=background.

Responda SEMPRE em português. Seja conciso.
NÃO use rótulos como "Classe atual:" ou "Estado:". Inclua apenas o bloco de estado puro no final da mensagem: <classification>{
  "complete": false,
  "persona_slug": null,
  "content_type": null,
  "asset_type": null,
  "asset_function": null,
  "title": null
}
</classification>
Quando TODAS as informações estiverem coletadas E confirmadas pelo usuário, marque "complete": true.
"""

_SYSTEM_PROMPT += """

=== FLUXO CAPTURAR / MARKETING GRAPH ===
Quando a sessão trouxer um contexto inicial confirmado pelo operador, leia esse contexto como briefing operacional. Antes de acionar qualquer salvamento, proponha:
1. fontes usadas;
2. entries a criar ou atualizar por nível do grafo: brand, campaign, audience, product, variant/color, copy, faq, rule e tone;
3. links semânticos esperados entre entries;
4. riscos de invenção e perguntas pendentes.

Para pedidos de copy/marketing, gere propostas hierarquizadas por grafo, não uma lista solta de textos. Exemplo de encadeamento:
brand -> campaign -> audience -> product -> color/variant -> copy -> faq/rule.

Nunca invente preço, cor, disponibilidade, URL, política comercial ou promessa. Use apenas contexto inicial, uploads, mensagens do usuário e conhecimento confirmado. Quando faltar dado, marque como pendente e pergunte ao operador.

=== CRAWLER / SITE COMO EVIDENCIA BRUTA ===
Quando o usuario pedir para ler, coletar ou usar um site, trate o crawler como captura bruta, nao como verdade perfeita.
O crawler pode falhar por HTML inconsistente, JavaScript, imagem, dados duplicados ou dados ausentes.

Se houver resultado do crawler no estado da sessao:
- cite a confianca e os avisos tecnicos;
- use candidatos extraidos como rascunho/evidencia, nao como conhecimento ativo;
- quando preco, cor, kit, disponibilidade ou atributo estiver ausente, pergunte de forma objetiva ou marque como pendente;
- nao diga "li todos os produtos" se o crawler trouxe confianca baixa/media ou candidatos incompletos;
- proponha uma arvore de conhecimento com status por entry: confirmado, inferido, pendente_validacao.

Ao final da coleta, gere varios conhecimentos, um para cada bloco selecionado pelo operador. Exemplo minimo quando os blocos forem briefing, publico, product, entity, copy e faq:
1. briefing: fonte, escopo, riscos do crawler e regras de validacao;
2. publico: revendedoras e clientes finais, com dores/objetivos/criterios de preco;
3. product: uma entry por produto candidato, usando o titulo do produto quando disponivel;
4. entity: cores, tamanhos, kits, materiais e precos como entidades/tags quando confirmados;
5. copy: copys separadas por publico/canal quando houver informacao suficiente;
6. faq: perguntas e respostas recuperaveis sobre preco, cores, kits, varejo e atacado.

Antes de salvar, apresente a lista concreta de entries e links semanticos que serao criados. Nao finalize com um resumo generico.

=== SAIDA ESTRUTURADA OBRIGATORIA PARA GERACAO ===
Quando o operador pedir "gerar conhecimento", "pode gerar", "criar a arvore" ou equivalente, OU se houver resultados de crawler e blocos selecionados no contexto inicial, OU se a sessao for iniciada com URL e blocos:
- nao responda com resumo generico;
- PRIORIZE gerar o plano imediatamente se houver evidências capturadas;
- gere uma proposta completa em Markdown para leitura humana;
- inclua obrigatoriamente um bloco JSON entre <knowledge_plan> e </knowledge_plan>.
- nao substitua <knowledge_plan> por bloco ```json; o teste E2E exige as tags literais.

O JSON deve seguir este formato:
{
  "source": "URL ou origem",
  "persona_slug": "tock-fatal",
  "validation_policy": "human_validation_required",
  "entries": [
    {
      "content_type": "briefing|audience|product|entity|copy|faq|campaign|brand|rule|tone",
      "title": "titulo concreto",
      "slug": "slug-canonico",
      "status": "confirmado|inferido|pendente_validacao",
      "content": "conteudo do conhecimento",
      "tags": ["tag"],
      "metadata": {}
    }
  ],
  "links": [
    {"source": "slug", "relation_type": "part_of_campaign|about_product|answers_question|supports_copy|same_topic_as", "target": "slug"}
  ],
  "missing_questions": []
}

Regras para esse bloco:
- precisa conter uma entry para cada bloco selecionado no inicio;
- sempre crie uma estrutura de conhecimento em arvore com multiplos galhos: brand/campaign como raiz quando existirem, audience/product/entity como galhos intermediarios, e copy/faq/rule/asset como folhas conectadas;
- evite listas planas: cada entry deve ter ao menos um link semantico quando houver outro node relacionado no plano;
- distribua os links entre galhos diferentes para facilitar camadas, galhos e arvores no grafo inserido;
- se os blocos incluirem product, gere uma entry por produto conhecido ou candidato;
- se o operador pediu uma quantidade minima, essa quantidade e obrigatoria;
- se o operador pediu 3 produtos e o crawler encontrou so 2, crie o terceiro como produto candidato com status pendente_validacao;
- nao encerre um plano que pediu 3 produtos com apenas 2 products;
- se os blocos incluirem audience, gere publicos concretos, nao "publico geral";
- se os blocos incluirem copy, gere copies concretas e use a ferramenta mental de geracao de copy;
- se os blocos incluirem faq, gere perguntas e respostas recuperaveis;
- se o operador pediu FAQ sobre preco, cores e kits, gere no minimo 2 FAQs: uma para preco/kits e outra para cores;
- links devem conectar brand/campaign/audience/product/entity/copy/faq quando existirem;
- para uma arvore comercial completa, gere no minimo 8 links semanticos;
- campos desconhecidos devem ficar como pendente_validacao, nao bloquear a arvore inteira.

=== BLOCOS SELECIONADOS NA CAPTURA ===
O contexto inicial pode trazer "Blocos de conhecimento solicitados". Trate esses blocos como a intencao inicial do operador, nao como um grafo fixo.

Para cada bloco selecionado, identifique lacunas minimas antes de propor entries:
- brand: nome, posicionamento, promessa, provas e restricoes;
- briefing: objetivo, fonte, escopo, publico e formato de saida;
- campaign: nome, periodo, oferta, publico e produtos relacionados;
- audience: segmento, dores, desejos, objecoes e linguagem;
- product: nome, categoria, beneficios, atributos, preco, cores e disponibilidade;
- entity: cores, materiais, categorias, variantes e relacoes;
- copy: canal, publico, oferta, tom, CTA e prova;
- faq: pergunta real, resposta confirmada, fonte e produto/campanha ligados;
- rule: politica, condicao, excecao e fonte;
- tone: voz, palavras preferidas, palavras proibidas e exemplos;
- asset: tipo visual, uso, fonte, proporcao e restricoes.

Se durante a conversa o operador pedir outro bloco ou mudar o objetivo, atualize a proposta e pergunte as lacunas desse novo bloco. Nao exija que o operador escreva IDs de grafo como "brand:tock-fatal"; voce deve transformar respostas naturais em entries e links semanticos propostos.

=== QUANDO FALTAR INFORMACAO ===
Se voce nao souber uma informacao necessaria, nao preencha com suposicao e nao finalize a classificacao.
Responda perguntando ao operador somente o que falta, em no maximo 3 perguntas curtas.

Pergunte especialmente quando faltar:
- persona/cliente;
- tipo de conteudo;
- titulo canonico;
- fonte/URL/arquivo que comprova o conhecimento;
- produto, campanha ou publico-alvo a que a copy/FAQ/regra se conecta;
- preco, cores, disponibilidade, politica comercial ou prazo;
- confirmacao humana para salvar.

Formato recomendado quando houver lacunas:
1. "Para continuar preciso confirmar:"
2. Lista numerada curta de perguntas.
3. Opcionalmente, diga quais partes ja estao claras.
4. Mantenha "complete": false no bloco <classification>.

So marque "complete": true quando todos os campos minimos estiverem claros E o operador tiver confirmado explicitamente que pode salvar.

=== SUGESTOES PROATIVAS ===
Apos a geracao inicial de cards, ofereca proativamente ideias de melhorias ou como aumentar o conhecimento, como:
- "Podemos refinar a descricao de algum produto?"
- "Quer adicionar FAQs sobre politica de troca ou frete?"
- "Que tal criar copys especificas para campanhas de lancamento?"
- "Podemos buscar mais informacoes sobre concorrentes ou publicos-alvo?"

=== CONHECIMENTO DE NEGÓCIO: TOCK FATAL ===
- Tock Fatal (Loja Física): Kit Modal 10 peças sai por R$ 45,90 cada. Regra de flexibilidade "3 peças": o cliente pode levar apenas 3 unidades e manter o valor unitário promocional do kit de 10.
- Tock Fatal (Atacado/Revenda): Exige obrigatoriamente o kit de 10 peças para garantir o preço de revenda.
- Trocas: Aceitas em até 30 dias para peças sem sinal de uso.

=== VISUALIZAÇÃO E ENTREGÁVEIS ===
- Responda em Markdown visualmente rico (use tabelas para preços, negrito para ênfase e listas claras). 
- Suas mensagens serão exibidas em um componente com toggle "View/Code". Capriche na organização do Markdown para que a versão "View" seja elegante e profissional.
- Ao gerar cards de conhecimento (<knowledge_plan>), certifique-se de que cada entrada (regras, faqs, produtos, briefings, públicos) seja uma entry ATÔMICA e DETALHADA.
- Se o operador solicitar um volume alto (ex: 20+ cards), crie uma entry individual para cada FAQ, cada Regra e cada Produto. Não agrupe tudo em um único card de "FAQ Geral" se puder criar 10 cards de FAQ específicos.
"""


def _extract_cls(text: str) -> Optional[dict]:
    match = re.search(r"<classification>(.*?)</classification>", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except Exception:
        return None


def _strip_cls(text: str) -> str:
    return re.sub(r"\s*<classification>.*?</classification>", "", text, flags=re.DOTALL).strip()


def _extract_plan_entries(text: str) -> list[dict]:
    """Extrai entradas do knowledge_plan para renderizacao de cards no chat."""
    match = re.search(r"<knowledge_plan>\s*(.*?)\s*</knowledge_plan>", text, re.DOTALL)
    if not match:
        return []
    try:
        plan = json.loads(match.group(1).strip())
        return plan.get("entries", [])
    except Exception:
        return []

def _extract_plan(text: str) -> dict:
    """Extrai o plano completo (entries + links) do texto."""
    match = re.search(r"<knowledge_plan>\s*(.*?)\s*</knowledge_plan>", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1).strip())
    except Exception:
        return {}


def _session_path(session_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    return _SESSION_DIR / f"{safe}.json"


def _serialize_session(session: dict) -> dict:
    data = json.loads(json.dumps(session, default=str))
    raw = session.get("classification", {}).get("file_bytes")
    if isinstance(raw, (bytes, bytearray)):
        data.setdefault("classification", {})["file_bytes_b64"] = base64.b64encode(raw).decode("ascii")
        data["classification"]["file_bytes"] = None
    return data


def _save_session(session: dict) -> None:
    try:
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)
        _session_path(session["id"]).write_text(
            json.dumps(_serialize_session(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_session(session_id: str) -> Optional[dict]:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
        b64 = session.get("classification", {}).pop("file_bytes_b64", None)
        if b64:
            session["classification"]["file_bytes"] = base64.b64decode(b64)
        _sessions[session_id] = session
        return session
    except Exception:
        return None


def _get_session(session_id: str) -> Optional[dict]:
    return _sessions.get(session_id) or _load_session(session_id)


def create_session(model: str = "gpt-4o-mini", initial_context: str = "", agent_key: str = "sofia") -> dict:
    sid = str(uuid.uuid4())
    agent = get_agent_profile(agent_key)
    session = {
        "id": sid,
        "model": model,
        "agent_key": agent_key if agent_key in AGENT_PROFILES else "sofia",
        "agent_name": agent["name"],
        "agent_role": agent["role"],
        "agent_greeting": agent["greeting"],
        "stage": "chatting",
        "messages": [],
        "context": (initial_context or "").strip(),
        "crawler_captures": [],
        "classification": {
            "persona_slug": None,
            "content_type": None,
            "asset_type": None,
            "asset_function": None,
            "title": None,
            "file_ext": None,
            "file_bytes": None,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _sessions[sid] = session
    _save_session(session)
    return session


def get_session(session_id: str) -> Optional[dict]:
    return _get_session(session_id)


def attach_crawler_capture(session_id: str, capture: dict) -> bool:
    session = _get_session(session_id)
    if not session:
        return False
    captures = session.setdefault("crawler_captures", [])
    captures.append(capture)
    session["crawler_captures"] = captures[-5:]
    _save_session(session)
    return True


def _source_url_from_context(context: str) -> str | None:
    match = re.search(r"fonte principal:\s*(https?://\S+)", context or "", re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"https?://\S+", context or "")
    return match.group(0).strip() if match else None


def _should_crawl(user_content: str, session: dict) -> bool:
    content = user_content.lower()
    if re.search(r"\b(leia|ler|colete|coletar|site|fonte|link|catalogo|cat[aá]logo)\b", content, re.I):
        return True
    
    # Auto-trigger: URL no contexto + Primeira mensagem da sessao + Sem capturas ainda
    has_url = bool(_source_url_from_context(session.get("context") or ""))
    has_captures = bool(session.get("crawler_captures"))
    is_first_msg = len(session.get("messages", [])) <= 1
    return has_url and not has_captures and is_first_msg


def _crawler_context(captures: list[dict]) -> str:
    if not captures:
        return ""
    latest = captures[-1]
    products = latest.get("product_candidates") or []
    product_lines = []
    for i, product in enumerate(products[:12], 1):
        title = product.get("title") or "sem titulo"
        prices = product.get("prices") or ([product.get("price")] if product.get("price") else [])
        colors = product.get("colors") or []
        product_lines.append(
            f"{i}. {title} | precos={prices or 'pendente'} | cores={colors or 'pendente'} | fonte={product.get('source')}"
        )
    warnings = "\n".join(f"- {w}" for w in latest.get("warnings") or [])
    return "\n".join(
        [
            "Resultado mais recente do crawler heuristico:",
            f"- URL: {latest.get('url')}",
            f"- status_http: {latest.get('status_code')}",
            f"- confianca: {latest.get('confidence')} ({latest.get('confidence_label')})",
            "- politica: captura bruta; validacao humana obrigatoria antes de salvar como conhecimento ativo.",
            "",
            "Candidatos de produtos extraidos:",
            "\n".join(product_lines) if product_lines else "- nenhum candidato confiavel",
            "",
            "Avisos:",
            warnings or "- sem avisos tecnicos",
            "",
            "Preview de texto bruto:",
            (latest.get("raw_text_preview") or "")[:2500],
        ]
    )


def chat(session_id: str, user_message: str, file_info: Optional[dict] = None) -> dict:
    session = _get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    cls = session["classification"]

    if file_info:
        ext = file_info.get("ext", "")
        cls["file_ext"] = ext
        if file_info.get("bytes"):
            cls["file_bytes"] = file_info["bytes"]
        file_desc = f"[Arquivo: {file_info['filename']} — {len(file_info.get('bytes', b''))} bytes]"
        user_content = f"{file_desc}\n{user_message}".strip() if user_message else file_desc
    else:
        user_content = user_message

    session["messages"].append({"role": "user", "content": user_content})

    crawler_result = None
    if _should_crawl(user_content, session):
        source_url = _source_url_from_context(session.get("context") or "")
        if source_url:
            try:
                crawler_result = crawl_catalog_url(source_url)
            except Exception as exc:
                crawler_result = {
                    "url": source_url,
                    "confidence": 0.05,
                    "confidence_label": "baixa",
                    "warnings": [f"Crawler indisponivel: {exc}"],
                    "stages": [
                        {"key": "fetch", "label": "captura bruta da URL", "status": "error"},
                        {"key": "validate", "label": "validacao humana obrigatoria", "status": "required"},
                    ],
                }
            attach_crawler_capture(session_id, crawler_result)

    state_ctx = f"""
Estado atual:
- Agente: {session.get('agent_name') or 'Sofia'} ({session.get('agent_role') or 'agente de inteligencia marketing comercial'})
- Regra de apresentacao: se precisar se apresentar, diga que voce e {session.get('agent_name') or 'Sofia'}; nunca diga que voce e Criar.
- Cliente: {cls['persona_slug'] or '—'}
- Tipo de conteúdo: {cls['content_type'] or '—'}
- Tipo de asset: {cls['asset_type'] or '—'}
- Função do asset: {cls['asset_function'] or '—'}
- Título: {cls['title'] or '—'}
- Arquivo binário recebido: {'Sim (' + cls['file_ext'] + ')' if cls.get('file_bytes') else 'Não'}
"""

    if session.get("context"):
        state_ctx += "\nContexto inicial confirmado pelo operador:\n" + session["context"][:6000] + "\n"
    if session.get("crawler_captures"):
        state_ctx += "\n" + _crawler_context(session["crawler_captures"]) + "\n"

    try:
        router = ModelRouter()
        raw = router.messages_create(
            model=session["model"],
            messages=session["messages"],
            system=_SYSTEM_PROMPT + "\n\n" + state_ctx,
            max_tokens=4000,
        )
    except ModelRouterError as exc:
        session["messages"].pop()  # roll back the user message on failure
        _save_session(session)
        return {"error": f"LLM indisponível: {exc}"}
    except Exception as exc:
        session["messages"].pop()
        _save_session(session)
        return {"error": f"Erro inesperado no LLM: {exc}"}

    cls_data = _extract_cls(raw)
    visible = _strip_cls(raw)
    plan_entries = _extract_plan_entries(raw)

    if cls_data:
        for key in ("persona_slug", "content_type", "asset_type", "asset_function", "title"):
            if cls_data.get(key):
                cls[key] = cls_data[key]
        if cls_data.get("complete"):
            session["stage"] = "ready_to_save"

    session["messages"].append({"role": "assistant", "content": raw})
    _apply_save_inference(session)
    _save_session(session)

    return {
        "message": visible,
        "stage": session["stage"],
        "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
        "crawler": crawler_result,
        "proposed_entries": plan_entries,
    }


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w\s\-]", "_", name).strip().replace(" ", "_")


def _fold(text: str) -> str:
    import unicodedata
    normalized = unicodedata.normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _infer_from_transcript(session: dict) -> dict:
    transcript = "\n".join(str(m.get("content") or "") for m in session.get("messages", []))
    visible = _strip_cls(transcript)
    folded = _fold(visible)
    inferred: dict = {}

    def label_key(label: str) -> str | None:
        normalized = _fold(label).strip().replace("?", "")
        if normalized == "cliente":
            return "persona_slug"
        if normalized in {"tipo", "tipo de conteudo", "tipo de contedo"}:
            return "content_type"
        if normalized in {"titulo", "ttulo"}:
            return "title"
        if normalized in {"descricao", "descrio"}:
            return "description"
        if normalized == "link":
            return "link"
        return None
    for line in visible.splitlines():
        clean = line.strip().lstrip("-").strip()
        if ":" not in clean:
            continue
        label, value = clean.split(":", 1)
        key = label_key(label)
        if key and value.strip():
            inferred[key] = value.strip().strip("-").strip()
        # Otimizacao: ignora linhas muito longas ou se ja encontrou os metadados principais
        if len(line) > 200 or len(inferred) >= 5:
            break

    if inferred.get("persona_slug"):
        key = _fold(inferred["persona_slug"]).strip()
        inferred["persona_slug"] = _PERSONA_ALIASES.get(key, key.replace(" ", "-"))
    else:
        for alias, slug in _PERSONA_ALIASES.items():
            if alias in folded:
                inferred["persona_slug"] = slug
                break

    if inferred.get("content_type"):
        key = _fold(inferred["content_type"]).strip()
        inferred["content_type"] = _CONTENT_ALIASES.get(key, key)
    else:
        for alias, ctype in _CONTENT_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", folded):
                inferred["content_type"] = ctype
                break

    return inferred


def _apply_save_inference(session: dict) -> None:
    cls = session["classification"]
    inferred = _infer_from_transcript(session)
    
    # 1. Inferir campos básicos do texto do chat
    for key in ("persona_slug", "content_type", "title"):
        if inferred.get(key) and (not cls.get(key) or cls.get(key) == "other"):
            cls[key] = inferred[key]
            
    # 2. Fallback: Se o título ainda estiver faltando, buscar no plano de conhecimento
    if not cls.get("title"):
        for msg in reversed(session.get("messages", [])):
            if msg.get("role") == "assistant":
                entries = _extract_plan_entries(msg.get("content") or "")
                if entries:
                    # Pega o título da primeira entrada ou do briefing
                    briefing = next((e for e in entries if e.get("content_type") == "briefing"), entries[0])
                    cls["title"] = briefing.get("title")
                    break

    # 3. Último recurso: Inferir da URL ou Persona para não travar o salvamento
    if not cls.get("title"):
        url = _source_url_from_context(session.get("context") or "")
        if url:
            cls["title"] = f"Extração: {url.split('//')[-1]}"
        elif cls.get("persona_slug"):
            cls["title"] = f"Conhecimento: {cls['persona_slug']}"

    if inferred.get("description"):
        cls["description"] = inferred["description"]
    if inferred.get("link"):
        cls["link"] = inferred["link"]


def _build_content(session: dict, content_text: str) -> str:
    if content_text and content_text.strip():
        return content_text.strip()
    cls = session["classification"]
    inferred = _infer_from_transcript(session)
    description = cls.get("description") or inferred.get("description") or ""
    link = cls.get("link") or inferred.get("link") or ""

    if cls.get("content_type") == "faq":
        lines = [f"Pergunta: {cls.get('title') or 'FAQ'}"]
        lines.append(f"Resposta: {description}" if description else "Resposta: ")
        if link:
            lines.extend(["", f"Link: {link}"])
        return "\n".join(lines)

    lines: list[str] = []
    if description:
        lines.extend(["## Descrição", "", description, ""])
    if link:
        lines.extend(["## Link", "", link, ""])
    return "\n".join(lines).strip()


def _write_entry_file(persona_slug: str, entry: dict) -> Optional[Path]:
    """Salva uma entrada individual de um plano de conhecimento no vault."""
    vault_root = Path(VAULT_PATH)
    client_folder = _VAULT_CLIENT_FOLDERS.get(persona_slug or "global", "00_GLOBAL")
    content_type = entry.get("content_type") or "other"
    type_folder = _CONTENT_TYPE_FOLDERS.get(content_type, "00_OTHER")
    
    # Prefere o slug como base do nome do arquivo, fallback para o titulo
    base_name = entry.get("slug") or entry.get("title") or "untitled"
    safe_name = _safe_filename(base_name)

    target_dir = vault_root / "AI-BRAIN" / "05_ENTITIES" / "CLIENTS" / client_folder / type_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{safe_name}.md"
    target_path = target_dir / filename

    now = datetime.now(timezone.utc).isoformat()
    # Monta frontmatter rico
    fm = {
        "title": entry.get("title"),
        "client": persona_slug,
        "type": content_type,
        "slug": entry.get("slug"),
        "created_at": now,
        "status": entry.get("status", "pendente_validacao"),
    }
    if entry.get("metadata"):
        fm.update(entry["metadata"])
    if entry.get("tags"):
        fm["tags"] = entry["tags"]

    fm_lines = ["---"]
    for k, v in fm.items():
        val = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        fm_lines.append(f"{k}: {val}")
    fm_lines.append("---")

    body = entry.get("content") or ""
    target_path.write_text("\n".join(fm_lines) + "\n\n" + body, encoding="utf-8")
    return target_path


def _create_rag_links(persona_id: str, links: list[dict], slug_to_id: dict) -> None:
    """Cria links entre entradas RAG baseadas nos slugs do plano."""
    for link in links:
        src_slug = link.get("source")
        tgt_slug = link.get("target")
        rel = link.get("relation_type") or "same_topic_as"
        
        src_id = slug_to_id.get(src_slug)
        tgt_id = slug_to_id.get(tgt_slug)
        
        if src_id and tgt_id and src_id != tgt_id:
            supabase_client.upsert_knowledge_rag_link({
                "persona_id": persona_id,
                "source_entry_id": src_id,
                "target_entry_id": tgt_id,
                "relation_type": rel,
                "weight": 1.0,
                "confidence": 0.8,
                "created_by": "classifier"
            })


def _write_file(session: dict, content_text: str) -> Path:
    cls = session["classification"]
    vault_root = Path(VAULT_PATH)
    client_folder = _VAULT_CLIENT_FOLDERS.get(cls["persona_slug"] or "global", "00_GLOBAL")
    type_folder = _CONTENT_TYPE_FOLDERS.get(cls["content_type"] or "other", "00_OTHER")
    safe_title = _safe_filename(cls["title"] or "untitled")

    ext = cls.get("file_ext") or ""
    is_binary_asset = ext.lower() in _ASSET_EXTS and cls.get("file_bytes")

    if is_binary_asset:
        target_dir = vault_root / "AI-BRAIN" / "05_ENTITIES" / "CLIENTS" / client_folder / "assets"
        filename = f"{safe_title}{ext}"
    else:
        target_dir = vault_root / "AI-BRAIN" / "05_ENTITIES" / "CLIENTS" / client_folder / type_folder
        filename = f"{safe_title}.md"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if is_binary_asset:
        target_path.write_bytes(cls["file_bytes"])
    else:
        now = datetime.now(timezone.utc).isoformat()
        lines = ["---", f"title: {cls['title']}", f"client: {cls['persona_slug']}",
                 f"type: {cls['content_type']}"]
        if cls.get("link"):
            lines.append(f"link: {cls['link']}")
        if cls.get("asset_type"):
            lines.append(f"asset_type: {cls['asset_type']}")
        if cls.get("asset_function"):
            lines.append(f"asset_function: {cls['asset_function']}")
        lines += [f"created_at: {now}", "---", "", content_text or ""]
        target_path.write_text("\n".join(lines), encoding="utf-8")

    return target_path


def _git_ops(vault_path: str, rel_path: str, title: str, client: str) -> dict:
    def run(args: list, **kw) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=vault_path, capture_output=True, text=True, timeout=60, **kw)

    add = run(["git", "add", rel_path])
    commit = run(["git", "commit", "-m", f"kb: add {title} [{client}]"])
    push = run(["git", "push"])

    return {
        "add_ok": add.returncode == 0,
        "commit_ok": commit.returncode == 0,
        "push_ok": push.returncode == 0,
        "commit_out": commit.stdout.strip()[:200],
        "push_err": push.stderr.strip()[:200],
    }


def save(session_id: str, content_text: str = "") -> dict:
    session = _get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    _apply_save_inference(session)
    cls = session["classification"]
    missing = [k for k in ("persona_slug", "content_type", "title") if not cls.get(k)]
    if missing:
        return {
            "error": "Classification incomplete — missing " + ", ".join(missing),
            "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
        }

    persona_id = supabase_client._resolve_persona_id(cls["persona_slug"])

    # Detecta se ha um plano para salvar multiplos arquivos
    plan_entries = []
    plan_links = []
    for msg in reversed(session.get("messages", [])):
        content = msg.get("content") or ""
        if msg.get("role") == "assistant" and "<knowledge_plan>" in content:
            plan = _extract_plan(content)
            plan_entries = plan.get("entries", [])
            plan_links = plan.get("links", [])
            break

    # ── 1. Write to vault and Structured Ingest ───────────────────────
    try:
        saved_paths = []
        slug_to_rag_id = {}

        if plan_entries:
            for entry in plan_entries:
                # 1.a Write to vault
                p = _write_entry_file(cls["persona_slug"], entry)
                if p: saved_paths.append(p)
                
                # 1.b Structured RAG intake (immediately creates layers/importance)
                try:
                    rag_res = knowledge_rag_intake.process_intake(
                        raw_text=entry.get("content") or "",
                        persona_slug=cls["persona_slug"],
                        source="classifier",
                        source_ref=session_id,
                        title=entry.get("title"),
                        content_type=entry.get("content_type"),
                        tags=entry.get("tags"),
                        metadata=entry.get("metadata"),
                        validate=True
                    )
                    if rag_res and rag_res.get("rag_entry"):
                        slug_to_rag_id[entry.get("slug")] = rag_res["rag_entry"].get("id")
                except Exception as rag_exc:
                    print(f"kb_intake: RAG processing failed for entry {entry.get('title')}: {rag_exc}")

            # 1.c Create semantic links in RAG
            if plan_links and persona_id:
                _create_rag_links(persona_id, plan_links, slug_to_rag_id)

            file_path = saved_paths[0] if saved_paths else None
        else:
            # Fallback single entry
            content_text = _build_content(session, content_text)
            file_path = _write_file(session, content_text)
            if file_path: saved_paths = [file_path]
            
        if not file_path:
            return {"error": "No files were written."}
    except Exception as e:
        from services import sre_logger
        sre_logger.error("kb_intake", f"Write failed: {e}", e)
        return {"error": f"Write failed: {e}"}

    # ── 2. Git (best-effort) ───────────────────────────────────────────
    try:
        # Adiciona cada arquivo individualmente para evitar lock de pasta
        git_results = []
        for p in saved_paths:
            rel_p = str(p.relative_to(Path(VAULT_PATH)))
            res = _git_ops(VAULT_PATH, rel_p, p.name, cls["persona_slug"])
            git_results.append(res)
        git_result = git_results[0] if git_results else {"ok": True, "git": "skipped"}
    except Exception as exc:
        git_result = {
            "add_ok": False, "commit_ok": False, "push_ok": False,
            "error": f"git unavailable: {exc}".strip()[:200],
        }

    try:
        rel_path = str(file_path.relative_to(Path(VAULT_PATH)))
    except Exception:
        rel_path = file_path.name if file_path else "unknown"

    # ── 3. Vault sync into knowledge_items (best-effort) ───────────────
    try:
        sync_result = run_sync(VAULT_PATH, persona_filter=cls["persona_slug"])
    except Exception as exc:
        sync_result = {"error": f"sync failed: {exc}".strip()[:200], "new": 0, "updated": 0}

    # ── 4. Audit event (best-effort) ──────────────────────────────────
    try:
        supabase_client.insert_event({
            "event_type": "kb_intake",
            "payload": {
                "title": cls["title"],
                "persona_slug": cls["persona_slug"],
                "content_type": cls["content_type"],
                "file_path": rel_path,
                "git": git_result,
                "sync_new": sync_result.get("new", 0),
                "sync_updated": sync_result.get("updated", 0),
            },
        })
    except Exception:
        pass  # insert_event is fire-and-forget anyway

    session["stage"] = "done"
    _save_session(session)

    return {
        "ok": True,
        "file_path": rel_path,
        "git": git_result,
        "sync": {
            "new": sync_result.get("new", 0),
            "updated": sync_result.get("updated", 0),
            "error": sync_result.get("error"),
        },
    }
