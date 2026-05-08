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
from typing import Any, Optional

from services import supabase_client
from services import knowledge_graph
from services import knowledge_lifecycle
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
_EVENT_PREVIEW_LIMIT = 280
_EVENT_TRANSCRIPT_MAX_TURNS = 120
_EVENT_CONTEXT_PREVIEW_LIMIT = 400
_BOOTSTRAP_PROMPT = (
    "Use o contexto inicial confirmado pelo operador e a retomada da sessao para continuar "
    "o trabalho imediatamente. Nao cumprimente, nao pergunte 'o que posso fazer por voce hoje' "
    "e nao trate isso como uma conversa vazia. Considere que a segunda tela ja iniciou a conversa. "
    "Responda com o proximo passo util: confirme o que ja entendeu, aponte o que esta pendente, "
    "proponha estrutura de conhecimento se ja houver contexto suficiente e use no maximo 3 perguntas objetivas "
    "somente se faltarem dados criticos."
)

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


_SYSTEM_PROMPT = """Você é uma agente especializada em classificar materiais para a base de conhecimento da plataforma Brain AI.

Sua identidade de conversa vem do estado da sessão. Por padrão, a agente é Sofia, agente de inteligência marketing comercial. Em fluxos futuros, a identidade pode mudar organicamente para Zaya, agente de marketing visual. Nunca se apresente como "Criar"; Criar é o nome da ferramenta/tela, não da agente.

Sua função: conduzir uma conversa objetiva para coletar as informações necessárias de classificação. Seja direto e eficiente. Não utilize mensagens padrão de agradecimento ou explicações sobre o processo técnico de salvamento.

VOCÊ NÃO TEM CAPACIDADE DE SALVAR. Salvar é uma ação exclusiva do operador, executada quando ele clica no botão "Salvar" da interface. Por isso:
- NUNCA diga "salvei", "foi salvo", "salvamento concluído", "estou salvando", "realizando o salvamento" ou frases equivalentes.
- NUNCA simule resultado de salvamento. Não existe IO de gravação no seu lado.
- Após apresentar o `<knowledge_plan>` e obter a confirmação ("sim", "pode", "ok"), apenas finalize com uma frase curta como: "Plano pronto. Clique em **Salvar** para persistir." e marque `"complete": true` no bloco `<classification>`.
- Se o operador perguntar "foi salvo?", responda que o salvamento depende do clique dele no botão Salvar — você não tem essa permissão.

=== MODO GERAR (PRIORIDADE MÁXIMA — SOBREPÕE QUALQUER OUTRA REGRA) ===
Esta seção rege seu comportamento conversacional. Em caso de conflito, ela vence.

GATILHOS DE GERAÇÃO IMEDIATA (não peça mais confirmação, GERE):
- "gere", "gera", "gerar", "pode gerar", "gera agora"
- "sim", "ok", "pode", "manda", "manda ver", "vai", "avança", "continua"
- "cria", "criar", "construa", "monta", "monte", "executa", "executar"
- "estrutura", "estrutura agora", "fecha o plano", "fecha"
Quando QUALQUER um aparecer, você responde com `<knowledge_plan>` completo na MESMA mensagem. Não responda "vou gerar agora" ou "pode confirmar?" — apenas gere.

NÃO RESTRINJA POR content_type INICIAL:
O `content_type` que o operador escolheu na tela (ex.: faq) sinaliza a INTENÇÃO PRINCIPAL, não limita você a um só nó. Quando houver catálogo, produto, campanha, briefing ou crawler envolvido, você DEVE construir a árvore completa de contexto que aquele FAQ/copy/asset precisa pra fazer sentido. Um FAQ nunca nasce solto.

CADEIA OBRIGATÓRIA QUANDO SÓ HÁ UMA OPÇÃO (vertical):
Se o contexto deixar evidente uma única persona, uma única fonte e uma única campanha (caso típico de extração de catálogo), monte AUTOMATICAMENTE a linha vertical sem perguntar:
  persona → briefing → campanha → público → produto → copy → faq
Cada elo desses precisa de pelo menos uma entry. NÃO pergunte "esse FAQ é de qual produto?" quando só existe um produto candidato.

ORDEM SEMÂNTICA NO JSON (entries[]):
Emita as entries SEMPRE nesta ordem semântica, independente de qual o operador "selecionou primeiro":
  1. brand          (se ainda não existir)
  2. briefing       (raiz da captura)
  3. campaign       (vem ANTES de produto/copy/faq, NUNCA depois)
  4. audience       (público-alvo da campanha)
  5. product        (item)
  6. copy           (do produto/canal)
  7. faq            (do produto, com pergunta+resposta)
Campanha jamais aparece depois de FAQ. FAQ é folha. Briefing é raiz.

GERAÇÃO AUTOMÁTICA DE FAQ:
Para CADA produto ou campanha criados, emita NO MÍNIMO 2 entries do tipo `faq` com perguntas + respostas concretas. Use defaults razoáveis baseados no contexto disponível (fabricação, público, indicação de uso). Marque `status: "pendente_validacao"` quando a resposta for inferida. NÃO pergunte ao operador "quais dúvidas você quer incluir?" — isso bloqueia o fluxo. Gere primeiro; depois ofereça expandir.

USO DE DEFAULTS QUANDO FALTAR DADO:
Se o operador respondeu apenas o público (ex.: "mulheres 30-55 loja física"), use isso para preencher campanha/produto/copy/faq sem nova rodada de perguntas. Marque os campos inferidos com `status: "pendente_validacao"` e adicione `metadata.inferred_from: "operator_hint"`. NÃO trave esperando dado adicional — apenas o conjunto persona+título é absolutamente obrigatório; tudo o mais aceita default.

CONEXÕES (parent_slug + links) SÃO OBRIGATÓRIAS:
Toda entry NÃO top-level (top-level = brand, briefing) precisa de UM dos dois:
  (a) `metadata.parent_slug` apontando para o slug do nó pai imediato, OU
  (b) aparecer como `target_slug` em `links[]` com `relation_type` apropriado.
Sem isso a árvore vira plana e o save é rejeitado pelo validador. NUNCA emita entry sem pai (exceto top-level).

Mapa default de relation_type por par (use no `links[]` ou implícito via parent_slug):
  brand     → contains            → briefing
  briefing  → briefed_by           → campaign
  campaign  → contains            → audience
  campaign  → contains            → product
  product   → answers_question    → faq
  product   → supports_copy       → copy
  audience  → about_product       → product   (uso secundário)

RESUMO ANTES DO SAVE:
Após o `<knowledge_plan>`, sempre apresente, no markdown legível, um resumo conciso ANTES de pedir o save:
  - "Briefing: 1 ✓"
  - "Campanha: 1 ✓"
  - "Público: 1 ✓"
  - "Produto: N ✓"
  - "Copy: N ✓"
  - "FAQ: N ✓ (gerados automaticamente, marcados como pendente_validacao)"
  - "Conexões: <count> edges no plano"
  - "Pendências: <lista curta ou 'nenhuma'>"
Aí finalize: "Plano pronto. Clique em **Salvar** para persistir." e marque `"complete": true` no `<classification>`.

NUNCA DECLARE "estruturado" SEM EMITIR `<knowledge_plan>`:
Se você for dizer "o conhecimento está estruturado e pronto para salvar", o `<knowledge_plan>` precisa estar na MESMA mensagem. Caso contrário, o operador não consegue ver/salvar nada e a sessão fica inconsistente.

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
2. entries a criar ou atualizar por nivel hierarquico: brand, campaign, audience, product, variant/color, copy, faq, rule e tone;
3. riscos de invencao e perguntas pendentes.

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

Ao final da coleta, gere varios conhecimentos, um para cada bloco selecionado pelo operador. Exemplo minimo quando os blocos forem briefing, audience, product, copy e faq:
1. briefing: fonte, escopo, riscos do crawler e regras de validacao;
2. audience: revendedoras e clientes finais, com dores/objetivos/criterios de preco;
3. product: uma entry por produto candidato, usando o titulo do produto quando disponivel. Cor, tamanho, kit, material e preco vao em `metadata` ou `tags` do product, nunca como content_type proprio;
4. copy: copys separadas por publico/canal quando houver informacao suficiente;
5. faq: perguntas e respostas recuperaveis sobre preco, cores, kits, varejo e atacado.

Antes de salvar, apresente a lista concreta de entries que serao criadas. Nao finalize com um resumo generico.

=== SAIDA ESTRUTURADA OBRIGATORIA PARA GERACAO ===
Quando o operador pedir "gerar conhecimento", "pode gerar", "criar a arvore" ou equivalente, OU se houver resultados de crawler e blocos selecionados no contexto inicial, OU se a sessao for iniciada com URL e blocos:
- nao responda com resumo generico;
- PRIORIZE gerar o plano imediatamente se houver evidências capturadas;
- gere uma proposta completa em Markdown para leitura humana;
- inclua obrigatoriamente um bloco JSON entre <knowledge_plan> e </knowledge_plan>.
- nao substitua <knowledge_plan> por bloco ```json; o teste E2E e o parser do backend exigem as tags literais.

REGRA CRITICA DE FORMATACAO (NAO QUEBRE):
- ERRADO: ```json\n{...}\n``` (markdown fence)
- ERRADO: JSON solto sem nada ao redor
- CORRETO: <knowledge_plan>\n{...}\n</knowledge_plan>
As tags abertura/fechamento sao OBRIGATORIAS, em letras minusculas, exatamente assim. Nao adicione "json" depois do <knowledge_plan>. Nao envolva em fence. Se voce escrever ```json em vez das tags, o backend cai num fallback inseguro e rejeita o save com "content must be a non-empty string".

O JSON deve seguir este formato:
{
  "source": "URL ou origem",
  "persona_slug": "tock-fatal",
  "validation_policy": "human_validation_required",
  "entries": [
    {
      "content_type": "brand|briefing|product|campaign|copy|asset|prompt|faq|maker_material|tone|competitor|audience|rule|other",
      "title": "titulo concreto",
      "slug": "slug-canonico",
      "status": "confirmado|inferido|pendente_validacao",
      "content": "conteudo do conhecimento",
      "tags": ["tag"],
      "metadata": {
        "parent_slug": "slug-do-no-pai"
      }
    }
  ],
  "links": [
    {
      "source_slug": "slug-do-no-pai",
      "target_slug": "slug-do-conhecimento",
      "relation_type": "manual"
    }
  ],
  "missing_questions": []
}

Regras para esse bloco:
- Cada entry deve ter uma ligacao principal. Use `metadata.parent_slug` ou inclua um item em `links`.
- Se nao souber o galho correto, pergunte antes de salvar: brand, briefing/campanha, produto, audiencia ou criar novo galho.
- Sugira o galho a partir de padroes semanticos existentes, mas transforme a decisao em edge principal no JSON.
- Briefings nunca sao soltos: conecte ao produto, audiencia, campanha ou outro no indicado.
- Se ainda nao houver pai melhor, conecte ao menos na persona da sessao.
- precisa conter uma entry para cada bloco selecionado no inicio;
- sempre crie uma estrutura de conhecimento em arvore com multiplos galhos: brand/campaign como raiz quando existirem, audience/product como galhos intermediarios, e copy/faq/rule/asset como folhas;
- evite listas planas: cada entry deve ter titulo, conteudo e contexto suficientes para ficar clara sem depender de relacoes obrigatorias;
- se os blocos incluirem product, gere uma entry por produto conhecido ou candidato;
- se o operador pediu uma quantidade minima, essa quantidade e obrigatoria;
- se o operador pediu 3 produtos e o crawler encontrou so 2, crie o terceiro como produto candidato com status pendente_validacao;
- nao encerre um plano que pediu 3 produtos com apenas 2 products;
- se os blocos incluirem audience, gere publicos concretos, nao "publico geral";
- se os blocos incluirem copy, gere copies concretas e use a ferramenta mental de geracao de copy;
- se os blocos incluirem faq, gere perguntas e respostas recuperaveis;
- se o operador pediu FAQ sobre preco, cores e kits, gere no minimo 2 FAQs: uma para preco/kits e outra para cores;
- `links` e opcional somente quando todas as entries ja trouxerem `metadata.parent_slug`;
- campos desconhecidos devem ficar como pendente_validacao, nao bloquear a arvore inteira.

=== OUTPUT VALIDATION (HARD CONTRACT) ===
Antes de fechar `<knowledge_plan>`, verifique entrada por entrada:
- `content_type` ESTRITAMENTE ∈ {brand, briefing, product, campaign, copy, asset, prompt, faq, maker_material, tone, competitor, audience, rule, other}. Qualquer outro valor (incluindo "entity", "publico", "category", "kit") sera rejeitado pelo banco.
- `title` nao vazio, com pelo menos 3 caracteres.
- `content` nao vazio.
- `tags` deve ser lista de strings (pode ser vazia). Nunca dict.
- `metadata` deve ser objeto JSON (dict). Nunca string ou lista.
- `entries` deve ser lista nao vazia.
Se algum campo nao se encaixar, ajuste a entry — nao gere o plano.

=== BLOCOS SELECIONADOS NA CAPTURA ===
O contexto inicial pode trazer "Blocos de conhecimento solicitados". Trate esses blocos como a intencao inicial do operador, nao como um grafo fixo.

Para cada bloco selecionado, identifique lacunas minimas antes de propor entries:
- brand: nome, posicionamento, promessa, provas e restricoes;
- briefing: objetivo, fonte, escopo, publico e formato de saida;
- campaign: nome, periodo, oferta, publico e produtos relacionados;
- audience: segmento, dores, desejos, objecoes e linguagem;
- product: nome, categoria, beneficios, atributos, preco, cores e disponibilidade;
- (cores, materiais, variantes nao sao bloco proprio: registre como atributo do product correspondente em metadata/tags);
- copy: canal, publico, oferta, tom, CTA e prova;
- faq: pergunta real, resposta confirmada, fonte e produto/campanha ligados;
- rule: politica, condicao, excecao e fonte;
- tone: voz, palavras preferidas, palavras proibidas e exemplos;
- asset: tipo visual, uso, fonte, proporcao e restricoes.

Se durante a conversa o operador pedir outro bloco ou mudar o objetivo, atualize a proposta e pergunte as lacunas desse novo bloco. Nao exija que o operador escreva IDs de grafo como "brand:tock-fatal"; voce deve transformar respostas naturais em entries atomicas.

=== QUANDO FALTAR INFORMACAO ===
Atencao: o MODO GERAR no topo do prompt sobrepoe esta secao. Aplique-a SOMENTE quando ainda nao houve nenhum gatilho de geracao e voce realmente nao tem dados minimos para construir UMA arvore.

Bloqueadores REAIS (so esses devem travar a geracao):
- persona/cliente: se nao identificado, pergunte;
- titulo canonico: se nao tiver, sugira um a partir da fonte (ex.: "Catalogo Modal Tock Fatal").

Para QUALQUER outro campo faltante (preco, cor, disponibilidade, politica, FAQ especifico, etc.) NAO pergunte antes de gerar — preencha com `status: "pendente_validacao"` e adicione na lista `missing_questions[]` do plano. O operador valida depois.

Quando faltar persona OU titulo:
1. "Para continuar preciso confirmar:"
2. Lista numerada curta (no maximo 2 perguntas).
3. Mantenha "complete": false no bloco <classification>.

Apos gerar o plano via <knowledge_plan>, marque "complete": true no <classification> imediatamente. Nao espere mais uma confirmacao.

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


def _candidate_plan_blocks(text: str) -> list[str]:
    """Yield candidate JSON strings that might contain a knowledge_plan.

    Strategy, in order of trust:
      1. <knowledge_plan>...</knowledge_plan>  (the one true contract)
      2. ```json ... ``` fenced block that contains "entries"
      3. ```...``` fenced block (any language tag) that contains "entries"
      4. Top-level JSON object that contains both "entries" and "persona_slug"

    The model occasionally drops the tags despite the prompt rules. Salvaging
    the output is preferable to failing the save and losing the operator's
    work — but we still log a warning so we know it happened.
    """
    candidates: list[str] = []

    for m in re.finditer(r"<knowledge_plan>\s*(.*?)\s*</knowledge_plan>", text, re.DOTALL):
        candidates.append(m.group(1).strip())

    for m in re.finditer(r"```(?:json|JSON)?\s*\n(.*?)\n```", text, re.DOTALL):
        block = m.group(1).strip()
        if '"entries"' in block:
            candidates.append(block)

    # Last resort: a bare JSON object that walks like a plan.
    if not candidates:
        for m in re.finditer(r"\{[^{}]*\"entries\"[^{}]*\"persona_slug\"[\s\S]*?\}", text):
            candidates.append(m.group(0).strip())
        # Bare object with "entries" only (e.g. when persona_slug is below entries).
        for m in re.finditer(r"\{[\s\S]*?\"entries\"\s*:\s*\[[\s\S]*?\]\s*[\s\S]*?\}", text):
            candidates.append(m.group(0).strip())

    return candidates


def _extract_plan(text: str) -> dict:
    """Extract the knowledge_plan JSON object from a Sofia message."""
    for raw in _candidate_plan_blocks(text):
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    return {}


def _extract_plan_entries(text: str) -> list[dict]:
    """Extrai entradas do knowledge_plan para renderizacao de cards no chat."""
    plan = _extract_plan(text)
    entries = plan.get("entries") if isinstance(plan, dict) else None
    return entries if isinstance(entries, list) else []


# Top-level node_types that may be a tree root without an explicit parent.
# Everything else MUST connect to one of these (transitively) via parent_slug
# or links[]. Keeps the operator's "no isolated node" rule enforceable.
SOFIA_TOP_LEVEL_TYPES: frozenset[str] = frozenset({"persona", "brand", "briefing"})

# Preferred parent node_types per child type. When Sofia emits an entry
# without parent_slug, _auto_infer_parent_slugs walks this list and picks
# the FIRST matching entry already declared in the plan (most recent of
# that type). This mirrors the architectural intent: faq belongs to a
# product, products belong to a campaign, copies belong to a product, etc.
_PREFERRED_PARENT_TYPES: dict[str, tuple[str, ...]] = {
    "briefing": ("brand",),
    "campaign": ("briefing", "brand"),
    "audience": ("campaign", "briefing", "brand"),
    "product": ("campaign", "briefing", "brand"),
    "tone": ("brand", "briefing", "campaign"),
    "rule": ("product", "campaign", "briefing", "brand"),
    "competitor": ("brand", "briefing"),
    "copy": ("product", "campaign", "audience", "briefing"),
    "faq": ("product", "campaign", "audience", "briefing"),
    "asset": ("product", "campaign", "brand"),
    "maker_material": ("product", "campaign", "brand"),
    "prompt": ("campaign", "brand", "briefing"),
    "other": ("product", "campaign", "brand", "briefing"),
}


def _auto_infer_parent_slugs(plan: dict) -> int:
    """Backstop hierarchy: when Sofia forgets parent_slug for non-top-level
    entries, infer one from the surrounding semantic order. Mutates the plan
    in place. Returns the number of entries that received an inferred parent.

    Algorithm (per orphan entry):
      1. Skip if the entry is top-level (brand, briefing, persona).
      2. Skip if metadata.parent_slug is already set, or the entry's slug
         appears as a target in plan.links (explicit parent already declared).
      3. Walk _PREFERRED_PARENT_TYPES[ctype] in order. For the first parent
         type that has at least one matching entry in the plan, pick the
         MOST RECENT (last declared) one — keeps the chain stable when
         operators emit multiple products or campaigns.
      4. If no preferred match, fall back to the first top-level entry
         (brand/briefing) anywhere in the plan.
      5. If still no candidate, the entry stays orphan; the validator will
         reject the plan with a precise message.
    """
    if not isinstance(plan, dict):
        return 0
    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries:
        return 0

    # Pre-compute link targets so explicit links aren't overwritten.
    raw_links = plan.get("links")
    link_targets: set[str] = set()
    if isinstance(raw_links, list):
        for link in raw_links:
            if isinstance(link, dict) and link.get("target_slug"):
                link_targets.add(str(link["target_slug"]))

    # Index existing entries by lowercase content_type → list (preserve order).
    by_type: dict[str, list[dict]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ctype = (entry.get("content_type") or "").lower()
        if ctype:
            by_type.setdefault(ctype, []).append(entry)

    inferred_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ctype = (entry.get("content_type") or "").lower()
        if not ctype or ctype in SOFIA_TOP_LEVEL_TYPES:
            continue
        slug = entry.get("slug")
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        if metadata.get("parent_slug"):
            continue
        if slug and str(slug) in link_targets:
            continue

        best: Optional[dict] = None
        for parent_type in _PREFERRED_PARENT_TYPES.get(ctype, ("brand", "briefing")):
            candidates = by_type.get(parent_type) or []
            for candidate in reversed(candidates):  # most recent of that type
                if candidate is entry or not candidate.get("slug"):
                    continue
                best = candidate
                break
            if best is not None:
                break

        # Fallback: first top-level entry anywhere in plan.
        if best is None:
            for candidate in entries:
                if not isinstance(candidate, dict) or not candidate.get("slug"):
                    continue
                if (candidate.get("content_type") or "").lower() in SOFIA_TOP_LEVEL_TYPES:
                    best = candidate
                    break
        if best is None or best is entry:
            continue

        if not isinstance(entry.get("metadata"), dict):
            entry["metadata"] = {}
        entry["metadata"]["parent_slug"] = str(best.get("slug"))
        entry["metadata"].setdefault("parent_inferred", True)
        entry["metadata"].setdefault(
            "parent_inferred_from",
            (best.get("content_type") or "unknown"),
        )
        inferred_count += 1
    return inferred_count


def validate_sofia_knowledge_plan(plan: dict) -> list[str]:
    """Validate a Sofia <knowledge_plan> JSON against the DB contract.

    Returns a list of human-readable violations (empty list = valid). Mirrors the
    constraints enforced by knowledge_items (NOT NULL, CHECK content_type, types)
    AND the architectural rule "no isolated node": every non-top-level entry
    needs an explicit parent (metadata.parent_slug or appearance as
    links[*].target_slug).
    """
    errors: list[str] = []
    if not isinstance(plan, dict):
        return ["plan must be a JSON object"]

    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["plan.entries must be a non-empty list"]

    raw_links = plan.get("links")
    links: list[dict] = raw_links if isinstance(raw_links, list) else []
    if raw_links is not None and not isinstance(raw_links, list):
        errors.append("plan.links must be a list when present")

    # Build set of slugs that are referenced as link targets (i.e. have a parent
    # via the links[] array). Each link must carry source_slug + target_slug.
    target_slugs_with_parent: set[str] = set()
    declared_slugs: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict) and entry.get("slug"):
            declared_slugs.add(str(entry["slug"]))
    for lidx, link in enumerate(links):
        if not isinstance(link, dict):
            errors.append(f"links[{lidx}] must be a JSON object")
            continue
        src = link.get("source_slug")
        tgt = link.get("target_slug")
        if not src or not tgt:
            errors.append(f"links[{lidx}] requires source_slug and target_slug")
            continue
        target_slugs_with_parent.add(str(tgt))

    allowed = supabase_client.KNOWLEDGE_ITEM_CONTENT_TYPES
    for idx, entry in enumerate(entries):
        prefix = f"entry[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be a JSON object")
            continue

        content_type = entry.get("content_type")
        if not content_type:
            errors.append(f"{prefix} missing content_type")
        elif content_type not in allowed:
            errors.append(
                f"{prefix} content_type {content_type!r} not allowed "
                f"(expected one of {sorted(allowed)})"
            )

        title = entry.get("title")
        if not isinstance(title, str) or len(title.strip()) < 3:
            errors.append(f"{prefix} title must be a string of at least 3 chars")

        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"{prefix} content must be a non-empty string")

        tags = entry.get("tags")
        if tags is not None and not isinstance(tags, list):
            errors.append(f"{prefix} tags must be a list, got {type(tags).__name__}")

        metadata = entry.get("metadata") or {}
        if entry.get("metadata") is not None and not isinstance(entry.get("metadata"), dict):
            errors.append(f"{prefix} metadata must be a dict, got {type(entry.get('metadata')).__name__}")
            metadata = {}

        # Hierarchical contract: non-top-level entries need an explicit parent.
        ctype_lower = (content_type or "").lower()
        if ctype_lower and ctype_lower not in SOFIA_TOP_LEVEL_TYPES:
            slug = entry.get("slug")
            has_parent_slug = bool(metadata.get("parent_slug"))
            has_link_target = bool(slug) and str(slug) in target_slugs_with_parent
            if not has_parent_slug and not has_link_target:
                errors.append(
                    f"{prefix} content_type {ctype_lower!r} requires a parent "
                    f"(set metadata.parent_slug OR add an entry to links[] with target_slug={slug!r})"
                )

    return errors


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
    session = _sessions.get(session_id) or _load_session(session_id)
    if session:
        session.setdefault("telemetry_transcript", [])
        session.setdefault("telemetry_flags", {"dialog_started_emitted": False})
    return session


def _truncate(value: Any, limit: int = _EVENT_PREVIEW_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _metrics_from_session(session: dict) -> dict[str, Any]:
    transcript = session.get("telemetry_transcript") or []
    user_turns = sum(1 for turn in transcript if turn.get("role") == "user")
    assistant_turns = sum(1 for turn in transcript if turn.get("role") == "assistant")
    messages = session.get("messages") or []
    return {
        "n_user_turns": user_turns,
        "n_assistant_turns": assistant_turns,
        "n_total_turns": len(transcript),
        "message_count": len(messages),
        "has_plan": any(
            msg.get("role") == "assistant" and "<knowledge_plan>" in str(msg.get("content") or "")
            for msg in messages
        ),
        "has_file": bool(session.get("classification", {}).get("file_ext")),
        "has_crawler_capture": bool(session.get("crawler_captures")),
    }


def _session_identity_payload(session: dict) -> dict[str, Any]:
    cls = session.get("classification") or {}
    return {
        "session_id": session.get("id"),
        "agent_key": session.get("agent_key"),
        "agent_name": session.get("agent_name"),
        "model": session.get("model"),
        "persona_slug": cls.get("persona_slug"),
        "content_type": cls.get("content_type"),
        "title": cls.get("title"),
        "stage": session.get("stage"),
    }


def _build_event_payload(
    session: dict,
    *,
    status: str,
    result: Optional[dict] = None,
    transcript: bool = False,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload = {
        **_session_identity_payload(session),
        "status": status,
        "metrics": _metrics_from_session(session),
    }
    if result is not None:
        payload["result"] = result
    if transcript:
        payload["transcript"] = session.get("telemetry_transcript") or []
    if extra:
        payload.update(extra)
    return payload


def _emit_kb_event(
    event_type: str,
    *,
    session: dict,
    source: str,
    status: str,
    result: Optional[dict] = None,
    transcript: bool = False,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    payload = _build_event_payload(
        session,
        status=status,
        result=result,
        transcript=transcript,
        extra=extra,
    )
    supabase_client.insert_event(
        {
            "event_type": event_type,
            "payload": payload,
        },
        source=source,
    )


def _append_transcript_turn(
    session: dict,
    *,
    role: str,
    content: str,
    file_attached: bool = False,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    transcript = session.setdefault("telemetry_transcript", [])
    turn = {
        "turn_index": len(transcript),
        "role": role,
        "message_preview": _truncate(content),
        "message_chars": len(content or ""),
        "file_attached": file_attached,
        "stage": session.get("stage"),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        turn.update(extra)
    transcript.append(turn)
    if len(transcript) > _EVENT_TRANSCRIPT_MAX_TURNS:
        session["telemetry_transcript"] = transcript[-_EVENT_TRANSCRIPT_MAX_TURNS:]
        for idx, item in enumerate(session["telemetry_transcript"]):
            item["turn_index"] = idx
        transcript = session["telemetry_transcript"]
    return transcript[-1]


def _default_mission_state(initial_context: str) -> dict[str, Any]:
    url = _source_url_from_context(initial_context or "")
    persona = "tock-fatal"
    obj = "Criar inteligencia de marketing em grafo com evidencias reais."
    blocks = ["briefing", "audience", "product", "copy", "faq"]
    if initial_context:
        m = re.search(r"persona_slug:\s*([a-z0-9_-]+)", initial_context, re.I)
        if m:
            persona = m.group(1).strip().lower()
        m = re.search(r"objetivo:\s*(.+)", initial_context, re.I)
        if m:
            obj = m.group(1).strip()
        found_blocks: list[str] = []
        for line in initial_context.splitlines():
            s = line.strip().lower()
            if not s.startswith("- "):
                continue
            token = s[2:].split(":", 1)[0].strip()
            token = _CONTENT_ALIASES.get(token, token)
            if token in {"brand", "briefing", "campaign", "audience", "product", "entity", "copy", "faq", "rule", "tone", "asset"}:
                found_blocks.append(token)
        if found_blocks:
            blocks = sorted(set(found_blocks), key=found_blocks.index)
    return {
        "persona": persona,
        "objective": obj,
        "source": {"type": "website", "url": url},
        "knowledge_blocks": blocks,
        "requested_outputs": {"models": []},
        "format": "default_intelligence_graph",
        "status": "collecting",
        "evidence_items": [],
        "last_patch": {},
    }


def _context_persona_slug(initial_context: str) -> str | None:
    m = re.search(r"persona_slug:\s*([a-z0-9_-]+)", initial_context or "", re.I)
    if m:
        return m.group(1).strip().lower()
    return None


def _context_objective(initial_context: str) -> str:
    m = re.search(r"objetivo:\s*(.+)", initial_context or "", re.I)
    if m:
        return m.group(1).strip()
    return ""


def _session_matches_resume_candidate(session: dict, *, persona_slug: str | None, agent_key: str, objective: str) -> bool:
    if (session.get("agent_key") or "sofia") != agent_key:
        return False
    stage = (session.get("stage") or "").lower()
    if stage == "done":
        return False
    candidate_persona = (
        (session.get("classification") or {}).get("persona_slug")
        or (session.get("mission_state") or {}).get("persona")
    )
    if persona_slug and candidate_persona and candidate_persona != persona_slug:
        return False
    if objective:
        candidate_objective = str((session.get("mission_state") or {}).get("objective") or "").strip().lower()
        if candidate_objective and candidate_objective != objective.strip().lower():
            return False
    return True


def _latest_local_resume_session(initial_context: str, agent_key: str) -> Optional[dict]:
    persona_slug = _context_persona_slug(initial_context)
    objective = _context_objective(initial_context)
    candidates: list[tuple[float, dict]] = []
    try:
        if not _SESSION_DIR.exists():
            return None
        for path in _SESSION_DIR.glob("*.json"):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not _session_matches_resume_candidate(session, persona_slug=persona_slug, agent_key=agent_key, objective=objective):
                continue
            candidates.append((path.stat().st_mtime, session))
    except Exception:
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _resume_summary_from_payload(payload: dict[str, Any]) -> str:
    transcript = payload.get("transcript") or []
    last_assistant = next(
        (turn.get("message_preview") for turn in reversed(transcript) if turn.get("role") == "assistant" and turn.get("message_preview")),
        "",
    )
    parts = [
        f"Persona: {payload.get('persona_slug') or 'nao informada'}",
        f"Tipo: {payload.get('content_type') or 'nao definido'}",
        f"Titulo: {payload.get('title') or 'sem titulo'}",
    ]
    if last_assistant:
        parts.append(f"Ultima resposta: {last_assistant}")
    return "\n".join(parts)


def _latest_persisted_resume(initial_context: str, agent_key: str) -> Optional[dict[str, Any]]:
    persona_slug = _context_persona_slug(initial_context)
    try:
        events = supabase_client.get_events(limit=20, event_type="kb_intake_dialog_completed")
    except Exception:
        return None
    for event in events or []:
        payload = event.get("payload") or {}
        if (payload.get("agent_key") or "sofia") != agent_key:
            continue
        if persona_slug and payload.get("persona_slug") != persona_slug:
            continue
        return {
            "resumed_from_session_id": payload.get("session_id"),
            "resume_source": "system_events",
            "resume_summary": _resume_summary_from_payload(payload),
        }
    return None


def _build_resume_metadata(initial_context: str, agent_key: str) -> dict[str, Any]:
    local_session = _latest_local_resume_session(initial_context, agent_key)
    if local_session:
        payload = _build_event_payload(local_session, status=str(local_session.get("stage") or "chatting"))
        return {
            "resumed_from_session_id": local_session.get("id"),
            "resume_source": "local_session",
            "resume_summary": _resume_summary_from_payload(payload),
        }
    return _latest_persisted_resume(initial_context, agent_key) or {
        "resumed_from_session_id": None,
        "resume_source": None,
        "resume_summary": "",
    }


def _context_with_resume(initial_context: str, resume_meta: dict[str, Any]) -> str:
    context = (initial_context or "").strip()
    resume_summary = (resume_meta or {}).get("resume_summary") or ""
    if not resume_summary:
        return context
    block = [
        "## Retomada automatica",
        f"source: {resume_meta.get('resume_source')}",
        f"session_id_anterior: {resume_meta.get('resumed_from_session_id') or 'desconhecida'}",
        resume_summary,
    ]
    return "\n\n".join([part for part in [context, "\n".join(block)] if part])


def _bootstrap_result_payload(session: dict, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session["id"],
        "model": session["model"],
        "model_name": AVAILABLE_MODELS.get(session["model"], session["model"]),
        "agent": {
            "key": session.get("agent_key"),
            "name": session.get("agent_name"),
            "role": session.get("agent_role"),
        },
        "welcome": session.get("agent_greeting"),
        "bootstrap_message": result.get("message") or "",
        "classification": result.get("classification") or {},
        "stage": result.get("stage") or session.get("stage"),
        "state": result.get("state") or session.get("mission_state"),
        "resumed_from_session_id": session.get("resumed_from_session_id"),
        "resume_source": session.get("resume_source"),
        "resume_summary": session.get("resume_summary"),
    }


def _persona_to_slug(raw: str) -> str:
    val = _fold(raw).strip()
    return _PERSONA_ALIASES.get(val, val.replace(" ", "-"))


def _upsert_model(state: dict, name: str) -> dict:
    models = state.setdefault("requested_outputs", {}).setdefault("models", [])
    for m in models:
        if _fold(m.get("name", "")) == _fold(name):
            return m
    default_qty = state.setdefault("requested_outputs", {}).get("default_products_requested")
    row = {"name": name, "audience": None, "products_requested": default_qty, "fields": []}
    models.append(row)
    return row


def _merge_user_intent(state: dict[str, Any], message: str) -> dict[str, Any]:
    text = message.strip()
    low = _fold(text)
    patch: dict[str, Any] = {}

    m = re.search(r"mudar para\s+([a-z0-9 _-]+?)\s+no site\s+([a-z0-9._/-]+)", low, re.I)
    if m:
        persona = m.group(1).strip()
        site = m.group(2).strip()
        if not site.startswith("http"):
            site = f"https://{site}"
        state["persona"] = _persona_to_slug(persona)
        state["source"] = {"type": "website", "url": site}
        state["objective"] = f"Criar conhecimento de marketing para {persona.title()} a partir de {site}, mantendo os blocos selecionados."
        patch.update({"persona": state["persona"], "source.url": site, "objective": state["objective"]})

    if "os mesmos" in low:
        patch["knowledge_blocks"] = "preserve_existing"

    m2 = re.search(r"(\d+)\s+produtos?\s+de\s+cada", low)
    if m2:
        qty = int(m2.group(1))
        state.setdefault("requested_outputs", {})["default_products_requested"] = qty
        for model in state.setdefault("requested_outputs", {}).setdefault("models", []):
            model["products_requested"] = qty
            model["fields"] = ["price", "angle", "faq"]
        patch["requested_outputs.products_requested_each"] = qty

    for name in ("juliet", "radar ev", "radar"):
        if name in low:
            canonical = "Radar Ev" if "radar" in name else "Juliet"
            _upsert_model(state, canonical)

    if "street" in low and "juliet" in low:
        row = _upsert_model(state, "Juliet")
        row["audience"] = "Street"
        patch["requested_outputs.models.juliet.audience"] = "Street"
    if ("esportes" in low or "esporte" in low) and "radar" in low:
        row = _upsert_model(state, "Radar Ev")
        row["audience"] = "Esportes"
        patch["requested_outputs.models.radar_ev.audience"] = "Esportes"

    if "faq" in low and "angle" in low:
        for model in state.setdefault("requested_outputs", {}).setdefault("models", []):
            model["fields"] = ["price", "angle", "faq"]

    state["last_patch"] = patch
    return patch


def _mission_summary(state: dict[str, Any]) -> str:
    blocks = ", ".join(state.get("knowledge_blocks") or [])
    models = state.get("requested_outputs", {}).get("models", [])
    model_line = "; ".join(
        f"{m.get('name')} -> {m.get('audience') or 'sem publico'}"
        for m in models
    ) or "sem modelos"
    source = ((state.get("source") or {}).get("url") or "sem fonte")
    persona = state.get("persona") or "sem persona"
    return (
        "Atualizei a missao:\n"
        f"Persona: {persona}\n"
        f"Fonte: {source}\n"
        f"Blocos mantidos: {blocks}\n"
        f"Modelos: {model_line}\n"
        "Agora vou coletar dados reais do site. Nao vou inventar precos ou FAQs."
    )


def _extract_price(product: dict[str, Any]) -> str:
    prices = product.get("prices") or []
    if prices:
        return str(prices[0])
    if product.get("price"):
        return str(product["price"])
    return ""


def _build_evidence_items(state: dict[str, Any], capture: dict[str, Any]) -> list[dict[str, Any]]:
    products = capture.get("product_candidates") or []
    models = state.get("requested_outputs", {}).get("models", [])
    out: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc).isoformat()
    for req in models:
        model_name = req.get("name") or ""
        audience = req.get("audience") or ""
        matched = [p for p in products if model_name and _fold(model_name) in _fold(str(p.get("title") or ""))]
        limit = int(req.get("products_requested") or 0) or 10
        for p in matched[:limit]:
            out.append({
                "name": p.get("title") or model_name,
                "url": capture.get("final_url") or capture.get("url") or "",
                "price": _extract_price(p),
                "model": model_name,
                "audience": audience,
                "angle": "pendente_validacao",
                "faq": [],
                "evidence": {
                    "source_url": capture.get("url") or "",
                    "captured_at": ts,
                    "confidence": "high" if (capture.get("confidence") or 0) >= 0.72 else "medium" if (capture.get("confidence") or 0) >= 0.45 else "low",
                },
            })
    return out


def create_session(model: str = "gpt-4o-mini", initial_context: str = "", agent_key: str = "sofia") -> dict:
    sid = str(uuid.uuid4())
    agent = get_agent_profile(agent_key)
    created_at = datetime.now(timezone.utc).isoformat()
    resume_meta = _build_resume_metadata(initial_context or "", agent_key if agent_key in AGENT_PROFILES else "sofia")
    session = {
        "id": sid,
        "model": model,
        "agent_key": agent_key if agent_key in AGENT_PROFILES else "sofia",
        "agent_name": agent["name"],
        "agent_role": agent["role"],
        "agent_greeting": agent["greeting"],
        "stage": "chatting",
        "messages": [],
        "context": _context_with_resume(initial_context or "", resume_meta),
        "mission_state": _default_mission_state(initial_context or ""),
        "crawler_captures": [],
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": False},
        "resumed_from_session_id": resume_meta.get("resumed_from_session_id"),
        "resume_source": resume_meta.get("resume_source"),
        "resume_summary": resume_meta.get("resume_summary"),
        "classification": {
            "persona_slug": None,
            "content_type": None,
            "asset_type": None,
            "asset_function": None,
            "title": None,
            "file_ext": None,
            "file_bytes": None,
        },
        "created_at": created_at,
    }
    _sessions[sid] = session
    _save_session(session)
    _emit_kb_event(
        "kb_intake_session_opened",
        session=session,
        source="kb-intake.start",
        status="opened",
        extra={
            "initial_context_present": bool(session.get("context")),
            "initial_context_preview": _truncate(session.get("context"), _EVENT_CONTEXT_PREVIEW_LIMIT),
            "created_at": created_at,
            "resumed_from_session_id": session.get("resumed_from_session_id"),
            "resume_source": session.get("resume_source"),
            "resume_summary": session.get("resume_summary"),
        },
    )
    return session


def start_bootstrap_session(model: str = "gpt-4o-mini", initial_context: str = "", agent_key: str = "sofia") -> dict[str, Any]:
    session = create_session(model, initial_context=initial_context, agent_key=agent_key)
    result = chat(session["id"], _BOOTSTRAP_PROMPT, internal=True)
    if result.get("ok") is False:
        return _bootstrap_result_payload(
            session,
            {
                "message": result.get("message") or "Nao consegui iniciar a conversa automaticamente com o contexto informado.",
                "classification": {k: v for k, v in (session.get("classification") or {}).items() if k != "file_bytes"},
                "stage": session.get("stage"),
                "state": session.get("mission_state"),
            },
        )
    return _bootstrap_result_payload(session, result)


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


def chat(session_id: str, user_message: str, file_info: Optional[dict] = None, internal: bool = False) -> dict:
    session = _get_session(session_id)
    if not session:
        return {
            "ok": False,
            "error_code": "VALIDATION_ERROR",
            "message": "Sessao nao encontrada.",
            "state": None,
        }

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

    previous_stage = session.get("stage")
    session["messages"].append({"role": "user", "content": user_content})
    _append_transcript_turn(
        session,
        role="user",
        content="Bootstrap automatico com contexto inicial confirmado." if internal else user_content,
        file_attached=bool(file_info),
        extra={
            "file_name": file_info.get("filename") if file_info else None,
            "input_mode": "bootstrap_context" if internal else "user_message",
        },
    )
    mission_state = session.setdefault("mission_state", _default_mission_state(session.get("context") or ""))
    patch = {} if internal else _merge_user_intent(mission_state, user_content)
    progress_reasons: list[str] = []

    # Generation trigger detection — emit kb_intake_generation_requested when
    # the operator types one of the autonomous-generation commands defined in
    # the system prompt (gere/sim/ok/cria/etc). This is the canonical signal
    # for "stop deliberating and produce <knowledge_plan>".
    _GEN_TRIGGER_RE = re.compile(
        r"\b(gere|gera|gerar|cria|criar|crie|construa|monte|monta|montar|"
        r"sim|ok|pode|manda|vai|avanca|avança|continua|continue|"
        r"executa|executar|fecha)\b",
        re.IGNORECASE,
    )
    if not internal and user_content and _GEN_TRIGGER_RE.search(user_content):
        _emit_kb_event(
            "kb_intake_generation_requested",
            session=session,
            source="kb-intake.chat",
            status="requested",
            extra={
                "trigger_message_preview": _truncate(user_content),
                "stage_before": previous_stage,
            },
        )

    flags = session.setdefault("telemetry_flags", {})
    if not flags.get("dialog_started_emitted"):
        progress_reasons.append("dialog_started")
        flags["dialog_started_emitted"] = True
        _emit_kb_event(
            "kb_intake_dialog_started",
            session=session,
            source="kb-intake.chat",
            status="started",
            extra={
                "start_mode": "bootstrap_context" if internal else "user_message",
                "first_user_message_preview": _truncate(user_content),
            },
        )

    crawler_result = None
    if _should_crawl(user_content, session):
        source_url = (mission_state.get("source") or {}).get("url") or _source_url_from_context(session.get("context") or "")
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
            mission_state["evidence_items"] = _build_evidence_items(mission_state, crawler_result)
            progress_reasons.append("crawler_capture")
            if crawler_result.get("warnings"):
                progress_reasons.append("crawler_warning")

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
        _emit_kb_event(
            "kb_intake_dialog_failed",
            session=session,
            source="kb-intake.chat",
            status="failed",
            transcript=True,
            result={
                "error_code": "INTERNAL_ERROR",
                "error_message": f"LLM indisponivel: {exc}",
                "failure_type": "model_router",
            },
        )
        return {
            "ok": False,
            "error_code": "INTERNAL_ERROR",
            "message": f"LLM indisponivel: {exc}",
            "state": mission_state,
        }
    except Exception as exc:
        session["messages"].pop()
        _save_session(session)
        _emit_kb_event(
            "kb_intake_dialog_failed",
            session=session,
            source="kb-intake.chat",
            status="failed",
            transcript=True,
            result={
                "error_code": "INTERNAL_ERROR",
                "error_message": f"Erro inesperado no LLM: {exc}",
                "failure_type": "unexpected",
            },
        )
        return {
            "ok": False,
            "error_code": "INTERNAL_ERROR",
            "message": f"Erro inesperado no LLM: {exc}",
            "state": mission_state,
        }

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
    _append_transcript_turn(
        session,
        role="assistant",
        content=visible,
        extra={
            "has_knowledge_plan": bool(plan_entries),
            "response_mode": "bootstrap_context" if internal else "user_message",
        },
    )
    _apply_save_inference(session)

    # Auto-promote to ready_to_save when a valid plan is emitted and the
    # required classification fields are present. The model frequently emits
    # the <knowledge_plan> block but forgets to flip <classification> "complete"
    # to true, which leaves the operator without a Save button. The plan
    # itself is the strongest signal that the agent considers itself done.
    auto_promoted = False
    if (
        session.get("stage") != "ready_to_save"
        and plan_entries
        and cls.get("persona_slug")
        and cls.get("content_type")
        and cls.get("title")
    ):
        session["stage"] = "ready_to_save"
        auto_promoted = True

    if plan_entries:
        try:
            entry_types: list[str] = []
            for e in plan_entries:
                t = e.get("content_type") if isinstance(e, dict) else None
                if t:
                    entry_types.append(t)
            _emit_kb_event(
                "kb_intake_generation_completed",
                session=session,
                source="kb-intake.chat",
                status="generated",
                extra={
                    "entry_count": len(plan_entries),
                    "entry_types": entry_types,
                    "auto_promoted_stage": auto_promoted,
                },
            )
        except Exception:
            pass

    if session.get("stage") == "ready_to_save" and previous_stage != "ready_to_save":
        try:
            _emit_kb_event(
                "kb_intake_ready_to_save",
                session=session,
                source="kb-intake.chat",
                status="ready_to_save",
                extra={
                    "entry_count": len(plan_entries) if plan_entries else 0,
                    "from_stage": previous_stage,
                    "auto_promoted": auto_promoted,
                },
            )
        except Exception:
            pass

    if patch:
        progress_reasons.append("intent_patch")
    if plan_entries:
        progress_reasons.append("knowledge_plan_generated")
    if previous_stage != session.get("stage"):
        progress_reasons.append("stage_changed")

    missing_targets: list[str] = []
    for model in mission_state.get("requested_outputs", {}).get("models", []):
        req = int(model.get("products_requested") or 0)
        if req <= 0:
            continue
        found = len([
            e for e in mission_state.get("evidence_items") or []
            if _fold(str(e.get("model") or "")) == _fold(str(model.get("name") or ""))
        ])
        if found < req:
            missing_targets.append(f"{model.get('name')}: {found}/{req}")
    if missing_targets:
        mission_state["status"] = "partial_collection"
    elif mission_state.get("evidence_items"):
        mission_state["status"] = "collected"

    prefix = _mission_summary(mission_state) if patch else ""
    if missing_targets:
        prefix += (
            ("\n\n" if prefix else "")
            + "Coleta parcial: " + ", ".join(missing_targets)
            + ". Posso complementar manualmente ou buscar outra fonte."
        )
    visible_out = f"{prefix}\n\n{visible}".strip() if prefix else visible

    progress_reasons = [reason for reason in progress_reasons if reason != "dialog_started"]
    if internal:
        progress_reasons.append("bootstrap_response_generated")
    if progress_reasons:
        _emit_kb_event(
            "kb_intake_dialog_progress",
            session=session,
            source="kb-intake.chat",
            status="in_progress",
            extra={
                "progress_reasons": progress_reasons,
                "patch_keys": sorted((patch or {}).keys()),
                "crawler_confidence": (crawler_result or {}).get("confidence") if crawler_result else None,
                "missing_targets": missing_targets,
                "input_mode": "bootstrap_context" if internal else "user_message",
            },
        )

    _save_session(session)

    return {
        "ok": True,
        "message": visible_out,
        "stage": session["stage"],
        "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
        "crawler": crawler_result,
        "proposed_entries": plan_entries,
        "state": mission_state,
        "patch": patch,
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

    # If a previous assistant turn already produced a <knowledge_plan> and the
    # classification has the required fields, promote the session even if the
    # model forgot to mark complete:true. Without this the operator never sees
    # the Save button while the model keeps hallucinating "salvo com sucesso".
    if session.get("stage") != "ready_to_save" and cls.get("persona_slug") and cls.get("content_type") and cls.get("title"):
        for msg in session.get("messages", []):
            if msg.get("role") == "assistant" and "<knowledge_plan>" in (msg.get("content") or ""):
                if _extract_plan_entries(msg.get("content") or ""):
                    session["stage"] = "ready_to_save"
                    break


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


def _slug_for_plan_entry(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return text.strip("-") or "item"


def _fallback_plan_content(session: dict, content_text: str) -> str:
    built = _build_content(session, content_text)
    if built.strip():
        return built.strip()
    recent_messages: list[str] = []
    for msg in reversed(session.get("messages", [])):
        raw = _strip_cls(str(msg.get("content") or "")).strip()
        raw = re.sub(r"<knowledge_plan>.*?</knowledge_plan>", "", raw, flags=re.DOTALL).strip()
        if not raw:
            continue
        recent_messages.append(f"{msg.get('role')}: {raw}")
        if len(recent_messages) >= 4:
            break
    if recent_messages:
        return "## Transcript\n\n" + "\n\n".join(reversed(recent_messages))
    cls = session.get("classification") or {}
    return f"Conhecimento capturado para {cls.get('title') or 'item sem titulo'}."


def _fallback_plan_payload(session: dict, content_text: str) -> dict:
    cls = session.get("classification") or {}
    inferred = _infer_from_transcript(session)
    entry_slug = _slug_for_plan_entry(cls.get("title") or inferred.get("title") or "item")
    metadata = {
        **(cls.get("metadata") or {}),
        "slug": entry_slug,
        "parent_slug": "self",
        "generated_from": "session_fallback",
        "link": cls.get("link") or inferred.get("link"),
        "asset_type": cls.get("asset_type"),
        "asset_function": cls.get("asset_function"),
    }
    metadata = {k: v for k, v in metadata.items() if v not in (None, "", [], {})}
    return {
        "source": cls.get("link") or inferred.get("link") or "session_fallback",
        "persona_slug": cls.get("persona_slug"),
        "validation_policy": "human_validation_required",
        "entries": [
            {
                "content_type": cls.get("content_type") or "other",
                "title": cls.get("title") or inferred.get("title") or "Conhecimento",
                "slug": entry_slug,
                "status": "pendente_validacao",
                "content": _fallback_plan_content(session, content_text),
                "tags": cls.get("tags") or inferred.get("tags") or [],
                "metadata": metadata,
            }
        ],
        "links": [],
        "missing_questions": [],
    }


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
        _emit_kb_event(
            "kb_intake_dialog_rejected",
            session=session,
            source="kb-intake.save",
            status="rejected",
            transcript=True,
            result={
                "error": "Classification incomplete",
                "missing_fields": missing,
                "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
            },
        )
        return {
            "error": "Classification incomplete — missing " + ", ".join(missing),
            "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
        }

    # Detecta se ha um plano para salvar multiplos arquivos
    plan_entries = []
    for msg in reversed(session.get("messages", [])):
        content = msg.get("content") or ""
        if msg.get("role") == "assistant" and "<knowledge_plan>" in content:
            plan = _extract_plan(content)
            plan_entries = plan.get("entries", [])
            break

    # ── 1. Write to vault and Structured Ingest ───────────────────────
    try:
        saved_paths = []
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
                except Exception as rag_exc:
                    print(f"kb_intake: RAG processing failed for entry {entry.get('title')}: {rag_exc}")

            file_path = saved_paths[0] if saved_paths else None
        else:
            # Fallback single entry
            content_text = _build_content(session, content_text)
            file_path = _write_file(session, content_text)
            if file_path: saved_paths = [file_path]
            
        if not file_path:
            _emit_kb_event(
                "kb_intake_dialog_rejected",
                session=session,
                source="kb-intake.save",
                status="rejected",
                transcript=True,
                result={"error": "No files were written."},
            )
            return {"error": "No files were written."}
    except Exception as e:
        from services import sre_logger
        sre_logger.error("kb_intake", f"Write failed: {e}", e)
        _emit_kb_event(
            "kb_intake_dialog_failed",
            session=session,
            source="kb-intake.save",
            status="failed",
            transcript=True,
            result={"error": f"Write failed: {e}", "failure_type": "write"},
        )
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
    session["stage"] = "done"
    _save_session(session)
    _emit_kb_event(
        "kb_intake_dialog_completed",
        session=session,
        source="kb-intake.save",
        status="completed",
        transcript=True,
        result={
            "file_path": rel_path,
            "saved_paths": [str(p) for p in saved_paths],
            "git": git_result,
            "sync_new": sync_result.get("new", 0),
            "sync_updated": sync_result.get("updated", 0),
            "sync_error": sync_result.get("error"),
            "entries_written": len(saved_paths),
            "plan_entries": len(plan_entries),
        },
    )

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


def save(session_id: str, content_text: str = "") -> dict:
    session = _get_session(session_id)
    if not session:
        return {"error": "Session not found"}

    try:
        _emit_kb_event(
            "kb_intake_save_requested",
            session=session,
            source="kb-intake.save",
            status="requested",
            extra={
                "stage": session.get("stage"),
                "has_content_text_override": bool(content_text and content_text.strip()),
            },
        )
    except Exception:
        pass

    _apply_save_inference(session)
    cls = session["classification"]
    missing = [k for k in ("persona_slug", "content_type", "title") if not cls.get(k)]
    if missing:
        _emit_kb_event(
            "kb_intake_dialog_rejected",
            session=session,
            source="kb-intake.save",
            status="rejected",
            transcript=True,
            result={
                "error": "Classification incomplete",
                "missing_fields": missing,
                "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
            },
        )
        return {
            "error": "Classification incomplete - missing " + ", ".join(missing),
            "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
        }

    plan_entries = []
    plan_payload: dict = {}
    for msg in reversed(session.get("messages", [])):
        content = msg.get("content") or ""
        if msg.get("role") == "assistant" and "<knowledge_plan>" in content:
            plan_payload = _extract_plan(content)
            plan_entries = plan_payload.get("entries", [])
            break

    if not plan_entries:
        plan_payload = _fallback_plan_payload(session, content_text)
        plan_entries = plan_payload.get("entries", [])

    # Backstop: auto-infer parent_slug for any non-top-level entry that
    # arrived without one. This catches the most frequent Sofia regression
    # (model omits metadata.parent_slug despite the prompt rule), so the tree
    # is always hierarchical instead of flat. Records the inference in the
    # event payload for auditability.
    inferred_parents = _auto_infer_parent_slugs(plan_payload)
    if inferred_parents:
        try:
            from services import sre_logger
            sre_logger.info(
                "kb_intake",
                f"auto-inferred parent_slug for {inferred_parents} entries session={session_id[:8]}",
            )
        except Exception:
            pass

    plan_violations = validate_sofia_knowledge_plan(plan_payload)
    if plan_violations:
        from services import sre_logger
        sre_logger.warn(
            "kb_intake",
            f"Sofia output rejected session={session_id[:8]} violations={plan_violations}",
        )
        _emit_kb_event(
            "kb_intake_dialog_rejected",
            session=session,
            source="kb-intake.save",
            status="rejected",
            transcript=True,
            result={
                "error": "Sofia output invalid",
                "violations": plan_violations,
            },
        )
        return {
            "error": "Sofia output invalid",
            "violations": plan_violations,
        }

    persisted_items: list[dict] = []
    persisted_evidence: list[dict] = []
    hierarchy_result: dict[str, Any] = {"items": [], "resolved_links": 0, "missing_links": []}

    try:
        saved_paths = []
        saved_payloads: list[dict] = []
        file_path = None
        for entry in plan_entries:
            path_obj = _write_entry_file(cls["persona_slug"], entry)
            if not path_obj:
                continue
            saved_paths.append(path_obj)
            entry_metadata = {
                **(entry.get("metadata") or {}),
                "slug": entry.get("slug") or _slug_for_plan_entry(entry.get("title") or path_obj.stem),
            }
            saved_payloads.append({
                "title": entry.get("title") or path_obj.stem,
                "content": entry.get("content") or "",
                "content_type": entry.get("content_type") or cls.get("content_type") or "other",
                "tags": entry.get("tags") or [],
                "metadata": entry_metadata,
                "file_path": str(path_obj.relative_to(Path(VAULT_PATH))),
                "file_type": (path_obj.suffix or ".md").lstrip("."),
            })
        file_path = saved_paths[0] if saved_paths else None

        if not file_path:
            _emit_kb_event(
                "kb_intake_dialog_rejected",
                session=session,
                source="kb-intake.save",
                status="rejected",
                transcript=True,
                result={"error": "No files were written."},
            )
            return {"error": "No files were written."}
    except Exception as exc:
        from services import sre_logger
        sre_logger.error("kb_intake", f"Write failed: {exc}", exc)
        _emit_kb_event(
            "kb_intake_dialog_failed",
            session=session,
            source="kb-intake.save",
            status="failed",
            transcript=True,
            result={"error": f"Write failed: {exc}", "failure_type": "write"},
        )
        return {"error": f"Write failed: {exc}"}

    try:
        for payload in saved_payloads:
            persisted = knowledge_lifecycle.persist_pending_knowledge_item(
                persona_slug=cls["persona_slug"],
                title=payload["title"],
                content=payload["content"],
                content_type=payload["content_type"],
                file_path=payload["file_path"],
                file_type=payload["file_type"],
                metadata={
                    **(payload.get("metadata") or {}),
                    "session_id": session_id,
                    "classification": {k: v for k, v in cls.items() if k != "file_bytes"},
                },
                tags=payload.get("tags") or [],
                source_ref=session_id,
                agent_visibility=["SDR", "Closer", "Classifier"],
            )
            if not persisted or not persisted.get("id"):
                raise RuntimeError(f"Knowledge item was not persisted for {payload['file_path']}")
            persisted_items.append(persisted)
            persisted_evidence.append({
                "knowledge_item_id": persisted.get("id"),
                "knowledge_node_id": (persisted.get("metadata") or {}).get("knowledge_node_id"),
                "status": persisted.get("status"),
                "file_path": persisted.get("file_path"),
                "title": persisted.get("title"),
                "slug": ((persisted.get("metadata") or {}).get("slug")),
            })
        if not persisted_items:
            raise RuntimeError("No knowledge_items were persisted")
        # Hierarchy materialization is best-effort: items are already in the DB,
        # so a transient Supabase glitch here must NOT roll back the whole save.
        # Capture the failure in `hierarchy_result.error` and emit a warning so
        # operators can re-trigger the layout (apply_plan_hierarchy is idempotent).
        try:
            hierarchy_result = knowledge_graph.apply_plan_hierarchy(
                persona_id=persisted_items[0].get("persona_id"),
                persisted_items=persisted_items,
                plan_entries=plan_entries,
                plan_links=plan_payload.get("links") or [],
            )
        except Exception as hier_exc:
            from services import sre_logger
            sre_logger.warn(
                "kb_intake",
                f"apply_plan_hierarchy failed (items still persisted): {hier_exc}",
                hier_exc,
            )
            hierarchy_result = {
                "items": [],
                "resolved_links": 0,
                "missing_links": [],
                "error": str(hier_exc),
            }
        hierarchy_by_item = {
            item.get("knowledge_item_id"): item
            for item in hierarchy_result.get("items") or []
            if item.get("knowledge_item_id")
        }
        for evidence in persisted_evidence:
            hierarchy_item = hierarchy_by_item.get(evidence.get("knowledge_item_id")) or {}
            if hierarchy_item.get("main_tree_edge_id"):
                evidence["main_tree_edge_id"] = hierarchy_item.get("main_tree_edge_id")
            if hierarchy_item.get("parent_slug"):
                evidence["parent_slug"] = hierarchy_item.get("parent_slug")
    except Exception as exc:
        from services import sre_logger
        sre_logger.error("kb_intake", f"Persistence failed: {exc}", exc)
        failure_type = "db_persist"
        message = str(exc)
        violations: list[str] = []
        if message.startswith("contract:"):
            failure_type = "db_contract"
            violations = [v.strip() for v in message[len("contract:"):].split(";") if v.strip()]
        elif "insert failed" in message:
            failure_type = "db_insert"
        elif "returned no row" in message:
            failure_type = "db_confirm"
        elif "graph node not confirmed" in message:
            failure_type = "graph_confirm"
        elif "without id" in message:
            failure_type = "db_contract"
        result = {
            "error": f"Persistence failed: {exc}",
            "failure_type": failure_type,
            "saved_paths": [str(p) for p in saved_paths],
        }
        if violations:
            result["violations"] = violations
        _emit_kb_event(
            "kb_intake_dialog_failed",
            session=session,
            source="kb-intake.save",
            status="failed",
            transcript=True,
            result=result,
        )
        response = {"error": f"Persistence failed: {exc}"}
        if violations:
            response["violations"] = violations
        return response

    try:
        git_results = []
        for path_obj in saved_paths:
            rel_p = str(path_obj.relative_to(Path(VAULT_PATH)))
            git_results.append(_git_ops(VAULT_PATH, rel_p, path_obj.name, cls["persona_slug"]))
        git_result = git_results[0] if git_results else {"ok": True, "git": "skipped"}
    except Exception as exc:
        git_result = {
            "add_ok": False,
            "commit_ok": False,
            "push_ok": False,
            "error": f"git unavailable: {exc}".strip()[:200],
        }

    try:
        rel_path = str(file_path.relative_to(Path(VAULT_PATH)))
    except Exception:
        rel_path = file_path.name if file_path else "unknown"

    try:
        sync_result = run_sync(VAULT_PATH, persona_filter=cls["persona_slug"])
    except Exception as exc:
        sync_result = {"error": f"sync failed: {exc}".strip()[:200], "new": 0, "updated": 0}

    session["stage"] = "done"
    _save_session(session)
    completion_payload = {
        "file_path": rel_path,
        "saved_paths": [str(p) for p in saved_paths],
        "git": git_result,
        "sync_new": sync_result.get("new", 0),
        "sync_updated": sync_result.get("updated", 0),
        "sync_error": sync_result.get("error"),
        "entries_written": len(saved_paths),
        "plan_entries": len(plan_entries),
        "plan_links": len(plan_payload.get("links") or []),
        "knowledge_item_ids": [item.get("id") for item in persisted_items],
        "knowledge_node_ids": [
            evidence.get("knowledge_node_id")
            for evidence in persisted_evidence
            if evidence.get("knowledge_node_id")
        ],
        "persistence_evidence": persisted_evidence,
        "hierarchy": hierarchy_result,
    }
    _emit_kb_event(
        "kb_intake_dialog_completed",
        session=session,
        source="kb-intake.save",
        status="completed",
        transcript=True,
        result=completion_payload,
    )
    # Specific named event for "save successfully landed in DB+graph". Carries
    # the same payload as dialog_completed so subscribers that only watch the
    # specific name don't have to filter by status.
    try:
        _emit_kb_event(
            "kb_intake_saved",
            session=session,
            source="kb-intake.save",
            status="saved",
            transcript=False,
            result=completion_payload,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "file_path": rel_path,
        "knowledge_item_ids": [item.get("id") for item in persisted_items],
        "knowledge_node_ids": [
            evidence.get("knowledge_node_id")
            for evidence in persisted_evidence
            if evidence.get("knowledge_node_id")
        ],
        "persistence_evidence": persisted_evidence,
        "hierarchy": hierarchy_result,
        "git": git_result,
        "sync": {
            "new": sync_result.get("new", 0),
            "updated": sync_result.get("updated", 0),
            "error": sync_result.get("error"),
        },
    }
