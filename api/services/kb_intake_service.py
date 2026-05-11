"""
KB Intake Service — conversational classifier for knowledge ingestion.
Writes to vault → git commit → sync Supabase.
"""
import os
import base64
import hashlib
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
from services.vault_sync import run_sync, VAULT_PATH, ensure_persona_vault_structure, persona_folder_name
from services.model_router import AVAILABLE_MODELS as ROUTER_MODELS
from services.model_router import ModelRouter, ModelRouterError

AVAILABLE_MODELS = {
    **ROUTER_MODELS,
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5 - fallback",
}

_GLOBAL_VAULT_CLIENT_FOLDER = "00_GLOBAL"

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
    "offer":         "13_OFFERS",
    "prompt":        "11_PROMPTS",
    "maker_material":"12_MAKER",
    "asset":         "assets",
    "other":         "00_OTHER",
}

_CONTENT_ALIASES = {
    "faq": "faq", "pergunta": "faq", "perguntas": "faq", "kb": "faq",
    "produto": "product", "product": "product",
    "oferta": "offer", "ofertas": "offer", "offer": "offer", "offers": "offer",
    "opcao": "offer", "opção": "offer", "variacao": "offer", "variação": "offer",
    "pacote": "offer", "kit": "offer", "product_variant": "offer", "purchase_option": "offer",
    "copy": "copy",
    "campanha": "campaign", "campaign": "campaign",
    "briefing": "briefing",
    "tom": "tone", "tone": "tone",
    "moodboard": "maker_material", "maker": "maker_material",
    "regra": "rule", "regras": "rule", "rule": "rule", "rules": "rule",
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

_PERSONA_DOMAINS = {
    "tockfatal.com": "tock-fatal",
    "www.tockfatal.com": "tock-fatal",
    "vzlupas.com": "vz-lupas",
    "www.vzlupas.com": "vz-lupas",
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
_BLOCK_COUNT_KEYS = ("brand", "briefing", "campaign", "audience", "product", "offer", "copy", "faq", "rule", "tone", "asset")
_OFFER_CONTENT_TYPES = {"offer", "product_variant", "purchase_option"}
_INVALID_CRIAR_PERSONAS = {"", "all", "todos", "global"}

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

POLITICA DE RAMIFICACAO DO PLAN:
Por padrao, emita `"tree_mode": "single_branch"` e `"branch_policy": "single_branch_by_default"`.
No primeiro prompt simples, a arvore principal deve ser unica. Para fluxo comercial/oferta, use:
  persona -> briefing -> audience -> product -> copy -> faq
Se houver copy no mesmo fluxo, FAQ comercial/oferta fica abaixo da copy. Use `product -> faq` somente quando o operador pedir FAQ tecnico/factual do produto ou quando nao houver copy. No modo CRIAR, mantenha `"tree_mode": "single_branch"` e `"branch_policy": "single_branch_by_default"`.

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

GERAÇÃO AUTOMÁTICA DE FAQ — POR FLUXO COMERCIAL, NÃO GENÉRICO:
Para CADA produto ou campanha criados, emita entries do tipo `faq` com perguntas + respostas concretas respeitando `faq_count_policy`. O padrao e FAQ total, nao FAQ por produto/oferta, salvo confirmacao explicita. Se existir copy no mesmo fluxo comercial, cada FAQ deve ter `metadata.parent_slug` = slug da copy especifica daquele produto/oferta; use `product -> faq` somente quando nao houver copy aplicavel ou quando o operador pedir FAQ tecnico do produto. NUNCA crie um único FAQ genérico que responde por vários produtos — quebre em FAQs separados por copy/oferta quando for necessario. O slug da entry FAQ deve incluir o slug do produto/copy correspondente quando aplicavel. Mesma regra para copy: uma copy por produto/oferta/canal, nunca uma copy compartilhada. Marque `status: "pendente_validacao"` quando a resposta for inferida. NÃO pergunte ao operador "quais dúvidas você quer incluir?" — isso bloqueia o fluxo. Gere primeiro; depois ofereça expandir.

EXPANSÃO POR PRODUTO (PROIBIDO COLAPSAR):
Se há 2 produtos no plano, gere AMBAS as árvores derivadas separadamente:
  Product: Produto A
    ├── Copy-1 (parent_slug = produto-a)
    ├── FAQ-1.1, FAQ-1.2 (parent_slug = copy-1 quando houver copy; senao produto-a)
    └── Rule-1 / Asset-1 (parent_slug = produto-a)
  Product: Produto B
    ├── Copy-2 (parent_slug = produto-b)
    ├── FAQ-2.1, FAQ-2.2 (parent_slug = copy-2 quando houver copy; senao produto-b)
    └── Rule-2 / Asset-2 (parent_slug = produto-b)
NUNCA combine "FAQ Geral dos Produtos" como um só nó cobrindo os dois produtos. Cada produto recebe sua própria sub-árvore. Idem para audience: se há audiência atacadista E final, ambas geram cards separados, e cada produto pode receber copies/FAQs voltadas a cada uma.

ORDEM SEMÂNTICA (TOP-DOWN, PROIBIDO INVERTER OU ENCURTAR):
A árvore final SEMPRE flui top-down nesta ordem ESTRITA:
  Persona → Brand → Campaign | Briefing → Audience → Product → FAQ | Copy | Asset → Embedded (só após aprovação)

Audience NUNCA fica lateral ao Product. Audience é PAI semântico do Product no contexto de uma campanha — quem o Product está mirando. Por isso `metadata.parent_slug` do Product DEVE apontar para a Audience correspondente, NÃO para a Campanha. A Campanha vira ancestral indireto (Audience → Campaign → Brand).

Encurtamentos PROIBIDOS:
- Persona → Audience direto: errado (faltou Brand/Campaign).
- Persona → Product direto: errado (faltou Brand → Campaign → Audience).
- Persona → FAQ direto: errado salvo se for FAQ institucional/fallback da persona inteira.
- Campaign → Product direto (sem Audience entre): errado quando há Audience no plano.
- Copy solta como filha da Persona/Brand/Campaign quando se refere a um produto específico: errado, vai como filha do Product. FAQ comercial vai como filha da Copy quando houver copy no mesmo fluxo; sem copy, vai como filha do Product.

Edges com semântica explícita (use estas no `links[]` quando aplicável):
  Persona → Brand     : `has_brand` ou `contains`
  Brand → Campaign    : `contains`
  Brand → Briefing    : `contains`
  Briefing → Campaign : `briefed_by` (campaign briefed_by briefing)
  Campaign → Audience : `targets_audience` ou `contains`
  Audience → Product  : `offers_product` ou `about_product`
  Product → Copy      : `supports_copy`
  Product → FAQ       : `answers_question` apenas para FAQ tecnico/sem copy
  Copy → FAQ          : `answers_question` no fluxo comercial single_branch
  Product → Asset     : `uses_asset`
  Approved FAQ → Embedded : `manual` (só após o operador aprovar — você NÃO emite isso)

Quando a chain ficar incompleta (ex.: faltou Audience no contexto), você deve INFERIR uma audience razoável (ex.: "público-geral") e marcar `status: "pendente_validacao"` em vez de pular o passo.

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

Você consegue extrair múltiplas informações de uma única mensagem. Por exemplo, se o usuário diz "background da marca", você já sabe content_type=asset e asset_type=background; a persona deve vir da sessao ou da confirmacao do operador.

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
  "persona_slug": "global",
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
- `content_type` ESTRITAMENTE in {brand, briefing, product, offer, campaign, copy, asset, prompt, faq, maker_material, tone, competitor, audience, rule, entity, other}. Qualquer outro valor (incluindo "rules", "publico", "category", "kit") sera rejeitado pelo banco.
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

Se durante a conversa o operador pedir outro bloco ou mudar o objetivo, atualize a proposta e pergunte as lacunas desse novo bloco. Nao exija que o operador escreva IDs de grafo como "brand:nome-da-persona"; voce deve transformar respostas naturais em entries atomicas.

=== QUANDO FALTAR INFORMACAO ===
Atencao: o MODO GERAR no topo do prompt sobrepoe esta secao. Aplique-a SOMENTE quando ainda nao houve nenhum gatilho de geracao e voce realmente nao tem dados minimos para construir UMA arvore.

Bloqueadores REAIS (so esses devem travar a geracao):
- persona/cliente: se nao identificado, pergunte;
- titulo canonico: se nao tiver, sugira um a partir da fonte (ex.: "Catalogo principal da colecao").

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

=== CONHECIMENTO DE NEGOCIO ===
- Nao assuma regras comerciais, precos, lotes minimos, trocas ou politicas sem evidencia confirmada na sessao, na fonte ou pelo operador.

=== VISUALIZAÇÃO E ENTREGÁVEIS ===
- Responda em Markdown visualmente rico (use tabelas para preços, negrito para ênfase e listas claras). 
- Suas mensagens serão exibidas em um componente com toggle "View/Code". Capriche na organização do Markdown para que a versão "View" seja elegante e profissional.
- Ao gerar cards de conhecimento (<knowledge_plan>), certifique-se de que cada entrada (regras, faqs, produtos, briefings, públicos) seja uma entry ATÔMICA e DETALHADA.
- Se o operador solicitar um volume alto (ex: 20+ cards), crie uma entry individual para cada FAQ, cada Regra e cada Produto. Não agrupe tudo em um único card de "FAQ Geral" se puder criar 10 cards de FAQ específicos.
"""


_SYSTEM_PROMPT += """

=== REGRA FRACTAL OBRIGATORIA ===
Sempre que houver N FAQs iniciais, cada Product dentro de cada Audience deve receber N FAQs por padrao.
Primeiro duplique o conjunto de FAQs em formato fractal, depois pergunte se o usuario deseja modificar, excluir ou adicionar FAQs antes de salvar.

=== CRAWLER MULTIPRODUTO ===
Se o operador indicar variedade, mais de um publico, compra em quantidade ou mais de um kit/modal, o crawler deve buscar multiplas opcoes de kit modal e preparar ramos separados por publico e produto.
Nao trate um catalogo variado como se fosse um unico produto.
"""

_SYSTEM_PROMPT += """

=== CONTRATO SIMPLES DO MODO CRIAR / SOFIA ===
Esta secao corrige e substitui regras anteriores conflitantes sobre multiplicacao automatica de FAQ.

Sua prioridade nao e escrever texto bonito. Sua prioridade e montar uma arvore de conhecimento valida.
Siga sempre este fluxo: explorar -> confirmar -> montar normalizedPlan -> validar -> resumir curto.

No modo create, use sempre:
  tree_mode = single_branch
  branch_policy = single_branch_by_default
  faq_count_policy = total

A branch principal deve seguir, quando aplicavel:
  persona -> brand -> briefing -> campaign -> audience -> product -> offer -> copy -> faq -> embedded
Se brand ou campaign nao existirem, pule o nivel, mas nao quebre a branch.

Regras estruturais obrigatorias:
- Se houver preco, quantidade, kit, pacote, opcao ou variacao comercial, crie offer obrigatoriamente.
- Offer fica abaixo de product.
- Copy fica abaixo de offer; se nao houver offer, fica abaixo de product ou campaign.
- FAQ comercial fica abaixo de copy. Nao use product -> faq quando existe copy ou offer.
- Product fica abaixo de audience.
- Audience fica abaixo de campaign ou briefing.
- Briefing fica abaixo de brand ou persona.
- Rule deve usar content_type = "rule" e ficar abaixo de campaign ou briefing.
- Nunca use content_type = "rules".
- Tags e mentions sao auxiliares; nunca entram na primary tree.
- Nunca crie knowledge_item como node visual da arvore principal.
- Nunca diga "plano pronto" se normalizedPlan.entries estiver vazio ou invalido.

Se o usuario disser "conecte a audiencia padrao":
- procure audiencia existente da persona;
- se houver uma audiencia compativel, use automaticamente;
- se houver mais de uma audiencia compativel, faca no maximo 1 pergunta objetiva;
- se nao houver audiencia, crie uma audiencia padrao abaixo do briefing.

Quando gerar plano, retorne sempre:
1. normalizedPlan.entries;
2. current_block_counts;
3. blocking_violations;
4. short_summary derivado do normalizedPlan.

O resumo visivel deve ser curto:
Status: plano gerado
Blocos: briefing N, publico N, produto N, offer N, copy N, FAQ N, regra N
Branch: briefing -> publico -> produto -> offer -> copy -> FAQ
Pendencias bloqueantes: nenhuma | lista curta
Acao: revisar preview

Se nao conseguir montar a arvore:
Status: bloqueado
Motivo: normalizedPlan vazio, parent ausente, offer ausente ou rule ausente
Acao: responder os campos pendentes

Nao escreva longas propostas sem gerar normalizedPlan. Se precisar perguntar, faca no maximo 2 perguntas objetivas.
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


def _strip_knowledge_plan(text: str) -> str:
    return re.sub(r"\s*<knowledge_plan>.*?</knowledge_plan>", "", text, flags=re.DOTALL).strip()


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


def count_blocks_by_type(entries: list[dict] | None) -> dict[str, int]:
    counts = {key: 0 for key in _BLOCK_COUNT_KEYS}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        ctype = _normalize_content_type_alias(entry.get("content_type"))
        if ctype in counts:
            counts[ctype] += 1
        elif ctype in _OFFER_CONTENT_TYPES:
            counts["offer"] += 1
    return counts


def _normalize_content_type_alias(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return _CONTENT_ALIASES.get(raw, raw)


def _invalid_criar_persona(persona_slug: str | None) -> bool:
    return str(persona_slug or "").strip().lower() in _INVALID_CRIAR_PERSONAS


def _normalize_block_counts(value: Any) -> dict[str, int]:
    counts = {key: 0 for key in _BLOCK_COUNT_KEYS}
    if not isinstance(value, dict):
        return counts
    for key in counts:
        try:
            counts[key] = max(0, int(value.get(key) or 0))
        except Exception:
            counts[key] = 0
    return counts


def _counts_from_plan_or_initial(plan: Optional[dict], initial_counts: Optional[dict] = None) -> dict[str, int]:
    entries = plan.get("entries") if isinstance(plan, dict) else None
    if isinstance(entries, list) and entries:
        return count_blocks_by_type(entries)
    return _normalize_block_counts(initial_counts)


def _format_block_counts(counts: Optional[dict[str, Any]]) -> str:
    normalized = _normalize_block_counts(counts)
    return ", ".join(f"{key} {value}" for key, value in normalized.items() if value) or "sem blocos"


def _build_live_memory_summary(session: dict, plan: Optional[dict] = None, *, last_change: str = "") -> str:
    persona = session.get("persona_slug") or (session.get("classification") or {}).get("persona_slug") or "nao informada"
    source = session.get("source_url") or (((session.get("mission_state") or {}).get("source") or {}).get("url")) or "nao informada"
    initial_counts = _format_block_counts(session.get("initial_block_counts"))
    current_counts = _format_block_counts(session.get("current_block_counts"))
    tree_mode = (plan or session.get("knowledge_plan") or {}).get("tree_mode") if isinstance(plan or session.get("knowledge_plan"), dict) else None
    branch_policy = (plan or session.get("knowledge_plan") or {}).get("branch_policy") if isinstance(plan or session.get("knowledge_plan"), dict) else None
    lines = [
        f"Persona global da sessao: {persona}.",
        f"Fonte principal: {source}.",
        f"Plano inicial: {initial_counts}.",
        f"Plano atual: {current_counts}.",
        f"Politica de arvore: {branch_policy or 'single_branch_by_default'}.",
        f"Modo da arvore: {tree_mode or 'single_branch'}.",
        "Nao salvar usando o plano inicial se o plano atual foi expandido.",
    ]
    if last_change:
        lines.append(f"Ultima alteracao do operador/agente: {last_change}.")
    return "\n".join(lines)


def _count_mismatch_message(expected: dict[str, int], actual: dict[str, int]) -> str | None:
    for key in _BLOCK_COUNT_KEYS:
        exp = int(expected.get(key) or 0)
        got = int(actual.get(key) or 0)
        if exp > 0 and got != exp:
            label = "FAQ" if key == "faq" else key
            return f"Plan mismatch: current plan has {exp} {label} but save payload has {got} {label}."
    return None


def summarize_normalized_plan(plan: dict) -> dict[str, Any]:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    counts = count_blocks_by_type(entries)
    return {
        "entry_count": len(entries),
        "current_block_counts": counts,
        "link_count": len(plan.get("links") or []),
        "tree_mode": plan.get("tree_mode") or "single_branch",
        "branch_policy": plan.get("branch_policy") or "single_branch_by_default",
        "faq_count_policy": plan.get("faq_count_policy") or "total",
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _plan_hash(plan: dict) -> str:
    canonical = {
        key: value
        for key, value in (plan or {}).items()
        if key not in {"summary", "validation", "plan_hash"}
    }
    return hashlib.sha256(_stable_json(canonical).encode("utf-8")).hexdigest()


def _plan_validation(violations: list[str] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    blocking = [str(item) for item in (violations or []) if str(item).strip()]
    return {
        "valid": len(blocking) == 0,
        "blocking_violations": blocking,
        "warnings": [str(item) for item in (warnings or []) if str(item).strip()],
    }


def _plan_state_from_normalized(plan: dict, session: Optional[dict] = None, *, violations: Optional[list[str]] = None) -> dict[str, Any]:
    normalized_plan = dict(plan or {})
    summary = summarize_normalized_plan(normalized_plan)
    normalized_plan["summary"] = summary
    validation = _plan_validation(violations if violations is not None else validate_sofia_knowledge_plan(normalized_plan, session=session))
    plan_hash = _plan_hash(normalized_plan)
    return {
        "normalized_plan": normalized_plan,
        "validation": validation,
        "summary": summary,
        "plan_hash": plan_hash,
    }


def normalize_validate_summarize_plan(raw_plan: dict, session: dict, *, live_edit: bool = False) -> dict[str, Any]:
    effective_session = session
    if live_edit and isinstance(raw_plan, dict):
        effective_session = dict(session or {})
        effective_session["current_block_counts"] = count_blocks_by_type(raw_plan.get("entries") or [])
    normalized_plan = _normalize_sofia_knowledge_plan(raw_plan, effective_session)
    plan_state = _plan_state_from_normalized(normalized_plan, session=effective_session)
    return plan_state


def _store_plan_state(session: dict, plan_state: dict[str, Any], *, last_change: str = "") -> None:
    normalized_plan = plan_state.get("normalized_plan") or {}
    summary = plan_state.get("summary") or summarize_normalized_plan(normalized_plan)
    validation = plan_state.get("validation") or _plan_validation()
    plan_hash = str(plan_state.get("plan_hash") or _plan_hash(normalized_plan))
    session["normalized_plan"] = normalized_plan
    session["knowledge_plan"] = normalized_plan
    session["last_proposed_plan"] = normalized_plan
    session["plan_validation"] = validation
    session["plan_summary"] = summary
    session["knowledge_plan_summary"] = summary
    session["plan_hash"] = plan_hash
    session["current_block_counts"] = summary.get("current_block_counts") or count_blocks_by_type(normalized_plan.get("entries") or [])
    session["plan_changed"] = True
    session["memory_summary"] = _build_live_memory_summary(session, normalized_plan, last_change=last_change)


# Top-level node_types that may be a tree root without an explicit parent.
# Everything else MUST connect to one of these (transitively) via parent_slug
# or links[]. Keeps the operator's "no isolated node" rule enforceable.
SOFIA_TOP_LEVEL_TYPES: frozenset[str] = frozenset({"persona", "brand", "briefing"})

# Preferred parent node_types per child type. When Sofia emits an entry
# without parent_slug, _auto_infer_parent_slugs walks this list and picks
# the FIRST matching entry already declared in the plan (most recent of
# that type). This mirrors the architectural intent: faq belongs to a
# product, products belong to a campaign, copies belong to a product, etc.
# Top-down chain enforced by the operator's hierarchy:
#   Persona → Brand → Campaign|Briefing → Audience → Product → Copy|FAQ|Asset
# Each child's preferred parents are listed from CLOSEST to fallback. The
# audience pivot between campaign and product is what prevents a flat
# "campaign → product" shortcut that bypasses the audience semantic step.
_PREFERRED_PARENT_TYPES: dict[str, tuple[str, ...]] = {
    "briefing": ("brand",),
    "campaign": ("briefing", "brand"),
    "audience": ("campaign", "briefing", "brand"),
    # Product must hang under audience whenever an audience exists in the
    # plan. Falls back to campaign/briefing/brand only when none does.
    "product": ("audience", "campaign", "briefing", "brand"),
    "offer": ("product",),
    "entity": ("product", "audience", "campaign", "briefing", "brand"),
    "tone": ("brand", "briefing", "campaign"),
    "rule": ("campaign", "briefing", "brand"),
    "competitor": ("brand", "briefing"),
    # Per-product children prefer the product directly. Falling back to
    # audience preserves the semantic step instead of jumping to campaign.
    "copy": ("offer", "product", "campaign"),
    "faq": ("copy", "offer", "product"),
    "asset": ("product", "audience", "campaign", "brand"),
    "maker_material": ("product", "campaign", "brand"),
    "prompt": ("campaign", "brand", "briefing"),
    "other": ("product", "audience", "campaign", "brand", "briefing"),
}


def _shared_slug_tokens(a: str, b: str) -> set[str]:
    """Return tokens shared between two slugs, excluding generic content-type
    prefixes/suffixes (faq, copy, briefing, etc.). Single-digit tokens like
    '1' or '2' are kept because they distinguish "Produto A" from "Kit
    Modal 2" in slugs like 'faq-preco-produto-b'."""
    if not a or not b:
        return set()
    blacklist = {
        "faq", "copy", "produto", "product", "audiencia", "audience",
        "campanha", "campaign", "brand", "briefing", "rule", "regra",
        "tone", "tom", "asset", "ativo",
        # Generic positional/connector words.
        "para", "pra", "com", "sem", "do", "da", "de", "e", "a", "o",
    }
    tokens_a = {t for t in (a or "").lower().split("-") if t and t not in blacklist}
    tokens_b = {t for t in (b or "").lower().split("-") if t and t not in blacklist}
    return tokens_a & tokens_b


def _best_parent_by_slug(orphan: dict, candidates: list[dict]) -> Optional[dict]:
    """Pick the candidate whose slug shares the most non-generic tokens with
    the orphan's slug/title. Returns None when there is no signal at all.

    This enables per-product FAQ/copy/asset matching: an entry slugged
    `faq-preco-produto-a` correctly attaches to the product
    `produto-a-cores` instead of an unrelated product earlier in the plan.
    """
    if not candidates:
        return None
    orphan_slug = (orphan.get("slug") or "")
    orphan_title = (orphan.get("title") or "")
    orphan_blob = f"{orphan_slug} {orphan_title}".lower()
    best = None
    best_score = 0
    for cand in candidates:
        if cand is orphan:
            continue
        cand_slug = (cand.get("slug") or "")
        cand_title = (cand.get("title") or "")
        # Substring match on full slug = strong signal.
        if cand_slug and cand_slug in orphan_blob:
            return cand
        shared = _shared_slug_tokens(orphan_slug, cand_slug)
        shared |= _shared_slug_tokens(orphan_title, cand_title)
        if len(shared) > best_score:
            best_score = len(shared)
            best = cand
    return best if best_score >= 1 else None


def _auto_infer_parent_slugs(plan: dict) -> int:
    """Backstop hierarchy: when Sofia forgets parent_slug for non-top-level
    entries, infer one from the surrounding semantic order. Mutates the plan
    in place. Returns the number of entries that received an inferred parent.

    Algorithm (per orphan entry):
      1. Skip if the entry is top-level (brand, briefing, persona).
      2. Skip if metadata.parent_slug is already set, or the entry's slug
         appears as a target in plan.links (explicit parent already declared).
      3. Walk _PREFERRED_PARENT_TYPES[ctype] in order. For each preferred
         parent type, prefer the candidate whose slug/title shares tokens
         with the orphan (per-product matching). Fall back to MOST RECENT
         only when no slug-similar candidate exists. This keeps each
         product's FAQ/copy attached to its OWN product instead of
         collapsing into a single most-recent product.
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
            candidates = [c for c in (by_type.get(parent_type) or []) if c is not entry and c.get("slug")]
            if not candidates:
                continue
            # Try slug-similarity first so each FAQ/copy attaches to its OWN
            # parent product when there are multiple products in the plan.
            picked = _best_parent_by_slug(entry, candidates)
            if picked is None:
                # Fallback: most recent of that type.
                picked = candidates[-1]
            best = picked
            break

        # Fallback: first top-level entry anywhere in plan. Do not use this
        # for commercial outputs: if a copy/FAQ cannot find product/copy
        # context, the plan is ambiguous and must ask before saving.
        if best is None and ctype not in {"copy", "faq"}:
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


def validate_sofia_knowledge_plan(plan: dict, session: Optional[dict] = None) -> list[str]:
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

        content_type = _normalize_content_type_alias(entry.get("content_type"))
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

    slug_to_entry = {
        str(entry.get("slug")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("slug")
    }
    product_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "product"]
    faq_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "faq"]
    offer_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "offer"]
    copy_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "copy"]
    rule_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "rule"]

    slugs = [str(entry.get("slug")) for entry in entries if isinstance(entry, dict) and entry.get("slug")]
    if len(slugs) != len(set(slugs)):
        errors.append("plan.entries must not contain duplicate slugs")

    if session and _offers_required(session, plan) and not offer_entries:
        errors.append("offer required when the request includes price, quantity, kit, package or commercial variation")
    if session and _rule_required(session, plan) and not rule_entries:
        errors.append("rule required when the request includes commercial governing rules")

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        ctype_lower = _entry_type(entry)
        parent_slug = _entry_parent_slug(entry)
        parent_entry = slug_to_entry.get(parent_slug or "")
        parent_type = _entry_type(parent_entry or {})
        if ctype_lower == "audience" and parent_slug and parent_type not in {"campaign", "briefing", "brand", "product", "other", ""}:
            errors.append(f"entry[{idx}] audience must stay under campaign/briefing/brand, got parent {parent_slug!r}")
        if ctype_lower == "product":
            if parent_slug and parent_type not in {"audience", "campaign", "briefing", "brand", "entity", "other", ""}:
                errors.append(f"entry[{idx}] product has invalid parent {parent_slug!r}")
            if "audience" in str(entry.get("slug") or "").lower():
                errors.append(f"entry[{idx}] product slug must not embed audience slug")
        if ctype_lower == "offer" and parent_type != "product":
            errors.append(f"entry[{idx}] offer must stay under product, got parent {parent_slug!r}")
        if ctype_lower == "copy":
            allowed_copy_parents = {"offer", "product", "campaign", "briefing", "brand", ""}
            if parent_type not in allowed_copy_parents:
                errors.append(f"entry[{idx}] copy has invalid parent {parent_slug!r}")
            if offer_entries and parent_type != "offer":
                errors.append(f"entry[{idx}] copy must stay under offer when commercial offers exist")
        if ctype_lower == "faq":
            if parent_slug and parent_type not in {"copy", "offer", "product", "audience", "campaign", "briefing", "brand", "persona", ""}:
                errors.append(f"entry[{idx}] faq has invalid parent {parent_slug!r}")
            if copy_entries and parent_type != "copy" and not _technical_product_faq_requested(session or {}):
                errors.append(f"entry[{idx}] faq must stay under copy when copy exists")
        if ctype_lower == "rule" and parent_type not in {"campaign", "briefing", "brand", "persona", ""}:
            errors.append(f"entry[{idx}] rule must stay under campaign/briefing/brand, got parent {parent_slug!r}")

    tree_mode = str(plan.get("tree_mode") or "single_branch").strip() or "single_branch"
    if tree_mode == "single_branch" and not _technical_product_faq_requested(session or {}):
        copy_slugs_by_product: dict[str, set[str]] = {}
        for copy in [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "copy"]:
            product_slug = _entry_parent_slug(copy)
            if product_slug:
                copy_slugs_by_product.setdefault(product_slug, set()).add(str(copy.get("slug") or ""))
        for idx, faq in enumerate(faq_entries):
            parent_slug = _entry_parent_slug(faq)
            parent_entry = slug_to_entry.get(parent_slug or "")
            if _entry_type(parent_entry or {}) == "product" and copy_slugs_by_product.get(parent_slug or ""):
                errors.append(
                    f"entry[{idx}] faq must use copy parent in single_branch when product {parent_slug!r} has copy"
                )

    faq_policy = str(plan.get("faq_count_policy") or "total").strip() or "total"
    if session and faq_policy == "total":
        requested_total = _requested_variation_count(session or {}, "faq", 8)
        if requested_total >= 0 and len(faq_entries) > requested_total:
            errors.append(
                f"faq_count_policy total allows at most {requested_total} FAQs without confirmation (found {len(faq_entries)})"
            )

    if product_entries and faq_policy != "total":
        faq_count_by_product: dict[str, int] = {}
        for faq in faq_entries:
            parent_slug = _entry_parent_slug(faq)
            if not parent_slug:
                continue
            parent_entry = slug_to_entry.get(parent_slug)
            if _entry_type(parent_entry or {}) == "copy":
                parent_slug = _entry_parent_slug(parent_entry or {})
            if parent_slug:
                faq_count_by_product[parent_slug] = faq_count_by_product.get(parent_slug, 0) + 1
        target_faq_count = _requested_variation_count(session or {}, "faq", 2) if session else None
        for entry in product_entries:
            product_slug = str(entry.get("slug") or "")
            branch_count = faq_count_by_product.get(product_slug, 0)
            if target_faq_count is not None and branch_count < target_faq_count:
                errors.append(
                    f"product {product_slug!r} must receive at least {target_faq_count} FAQs in the fractal plan (found {branch_count})"
                )

    if len(entries) > 1 and not (plan.get("links") or []):
        errors.append("plan.links must not be empty when the hierarchy already contains clear parent/child relations")

    return errors


def _entry_type(entry: dict) -> str:
    if not isinstance(entry, dict):
        return ""
    return _normalize_content_type_alias(entry.get("content_type")) or ""


def _entry_metadata(entry: dict) -> dict:
    meta = entry.get("metadata")
    if isinstance(meta, dict):
        return meta
    meta = {}
    entry["metadata"] = meta
    return meta


def _entry_parent_slug(entry: dict) -> Optional[str]:
    parent = _entry_metadata(entry).get("parent_slug")
    return str(parent).strip() if parent else None


def _set_entry_parent_slug(entry: dict, parent_slug: Optional[str]) -> None:
    meta = _entry_metadata(entry)
    if parent_slug:
        meta["parent_slug"] = parent_slug
    else:
        meta.pop("parent_slug", None)


def _normalize_parent_slug_value(parent_slug: Optional[str], persona_slug: str) -> Optional[str]:
    raw = str(parent_slug or "").strip()
    if not raw:
        return None
    if raw.lower() in {"global", "root", "persona", "persona-root"}:
        return "self"
    if _slug_for_plan_entry(raw) == _slug_for_plan_entry(persona_slug or ""):
        return "self"
    return raw


_PARALLEL_BRANCH_RE = re.compile(
    r"\b(outputs?\s+paralelos?|galhos?\s+paralelos?|branches?\s+paralelos?|"
    r"separ(e|ar)\s+copy\s+e\s+faq|copys?\s+e\s+faqs?\s+como\s+galhos?|"
    r"faqs?\s+direto\s+no\s+produto|diretamente\s+abaixo\s+do\s+produto)\b",
    re.I,
)
_TECHNICAL_FAQ_RE = re.compile(
    r"\b(faq\s+t[eé]cnic[oa]|perguntas?\s+t[eé]cnicas?|d[uú]vidas?\s+t[eé]cnicas?|"
    r"factual\s+do\s+produto|sobre\s+especifica[cç][oõ]es|especifica[cç][oõ]es\s+do\s+produto)\b",
    re.I,
)


def _session_text_for_branch_policy(session: dict) -> str:
    parts = [str(session.get("context") or "")]
    for msg in session.get("messages") or []:
        if isinstance(msg, dict):
            parts.append(str(msg.get("content") or ""))
    return "\n".join(parts)


def _explicit_parallel_outputs_requested(session: dict) -> bool:
    return bool(_PARALLEL_BRANCH_RE.search(_session_text_for_branch_policy(session)))


def _technical_product_faq_requested(session: dict) -> bool:
    return bool(_TECHNICAL_FAQ_RE.search(_session_text_for_branch_policy(session)))


def _normalize_plan_parent_slugs(plan: dict, persona_slug: str) -> None:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    brand_slugs = {
        str(entry.get("slug") or "").strip()
        for entry in entries
        if _entry_type(entry) == "brand" and entry.get("slug")
    }
    for entry in plan.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        meta = _entry_metadata(entry)
        raw_parent = str(meta.get("parent_slug") or "").strip()
        if (
            raw_parent
            and _entry_type(entry) != "brand"
            and raw_parent in brand_slugs
            and _slug_for_plan_entry(raw_parent) == _slug_for_plan_entry(persona_slug or "")
        ):
            normalized_parent = raw_parent
        else:
            normalized_parent = _normalize_parent_slug_value(raw_parent, persona_slug)
        if normalized_parent:
            meta["parent_slug"] = normalized_parent
        else:
            meta.pop("parent_slug", None)


def _knowledge_plan_title_from_session(session: dict) -> str:
    cls = session.get("classification") or {}
    if cls.get("title"):
        return str(cls["title"])
    context = str(session.get("context") or "")
    source_url = _source_url_from_context(context)
    if source_url:
        return f"Captura de {source_url.split('//')[-1]}"
    return "Plano de conhecimento"


def _requested_variation_count(session: dict, block_id: str, default: int) -> int:
    for key in ("current_block_counts", "initial_block_counts"):
        counts = session.get(key)
        if isinstance(counts, dict) and block_id in counts:
            try:
                return max(int(counts.get(block_id) or 0), 0)
            except Exception:
                pass
    context = str(session.get("context") or "")
    pattern = rf"^\s*-\s*{re.escape(block_id)}:\s*(\d+)\s+vari"
    match = re.search(pattern, context, flags=re.IGNORECASE | re.MULTILINE)
    if match:
        try:
            return max(int(match.group(1)), 0)
        except Exception:
            pass
    return default


def _has_explicit_variation_count(session: dict, block_id: str) -> bool:
    for key in ("current_block_counts", "initial_block_counts"):
        counts = session.get(key)
        if isinstance(counts, dict) and block_id in counts:
            return True
    context = str(session.get("context") or "")
    pattern = rf"^\s*-\s*{re.escape(block_id)}:\s*(\d+)\s+vari"
    return bool(re.search(pattern, context, flags=re.IGNORECASE | re.MULTILINE))


def _normalize_plan_entry(entry: dict) -> dict:
    normalized = dict(entry or {})
    normalized["content_type"] = _normalize_content_type_alias(_entry_type(normalized)) or "other"
    normalized["title"] = str(normalized.get("title") or "").strip() or "Conhecimento"
    normalized["slug"] = _slug_for_plan_entry(str(normalized.get("slug") or normalized["title"]))
    normalized["status"] = str(normalized.get("status") or "pendente_validacao").strip() or "pendente_validacao"
    content = str(normalized.get("content") or "").strip()
    normalized["content"] = content or normalized["title"]
    tags = normalized.get("tags") or []
    normalized["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    metadata = dict(normalized.get("metadata") or {})
    ctype = normalized["content_type"]
    if ctype == "briefing":
        metadata.setdefault("briefing_scope", "global")
        metadata.setdefault("governs_children", True)
    elif ctype == "audience":
        metadata.setdefault("audience_source", "manual")
        metadata.setdefault("import_page_url", None)
        metadata.setdefault("leads_page_url", None)
        metadata.setdefault("lead_segment_id", None)
        metadata.setdefault("crm_filters", {})
    elif ctype == "product":
        metadata.setdefault("product_source", "manual")
        metadata.setdefault("product_external_id", None)
        metadata.setdefault("product_page_url", None)
        metadata.setdefault("price_status", "pending_validation")
        metadata.setdefault("stock_status", "unknown")
    elif ctype == "offer":
        metadata.setdefault("offer_source", "manual")
        metadata.setdefault("price_status", "pending_validation")
        metadata.setdefault("stock_status", "unknown")
    elif ctype in {"entity", "other"} and str(metadata.get("entity_role") or "").strip():
        metadata.setdefault("entity_structural", metadata.get("entity_role") in {"product_group", "audience_group", "category_group"})
    normalized["metadata"] = metadata
    return normalized


def _relation_type_for_parent(parent_type: str, child_type: str) -> str:
    mapping = {
        ("persona", "brand"): "contains",
        ("persona", "briefing"): "contains",
        ("persona", "campaign"): "contains",
        ("persona", "audience"): "contains",
        ("persona", "product"): "contains",
        ("brand", "briefing"): "contains",
        ("brand", "product"): "contains",
        ("brand", "audience"): "contains",
        ("brand", "campaign"): "contains",
        ("briefing", "campaign"): "briefed_by",
        ("campaign", "audience"): "targets_audience",
        ("briefing", "audience"): "contains",
        ("briefing", "product"): "contains",
        ("product", "briefing"): "contains",
        ("audience", "briefing"): "contains",
        ("audience", "product"): "offers_product",
        ("product", "offer"): "contains",
        ("offer", "copy"): "supports_copy",
        ("offer", "faq"): "answers_question",
        ("campaign", "rule"): "contains",
        ("briefing", "rule"): "contains",
        ("brand", "rule"): "contains",
        ("entity", "product"): "contains",
        ("other", "product"): "contains",
        ("brand", "entity"): "contains",
        ("brand", "other"): "contains",
        ("briefing", "entity"): "contains",
        ("briefing", "other"): "contains",
        ("audience", "product"): "offers_product",
        ("product", "faq"): "answers_question",
        ("product", "copy"): "supports_copy",
        ("copy", "faq"): "answers_question",
        ("product", "asset"): "uses_asset",
    }
    return mapping.get((parent_type, child_type), "contains")


def _is_b2b_audience(entry: dict) -> bool:
    blob = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("content") or ""),
        " ".join(entry.get("tags") or []),
    ]).lower()
    return any(token in blob for token in ("varej", "revend", "lojist", "atacad", "empreended"))


def _is_b2b_faq(entry: dict) -> bool:
    blob = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("content") or ""),
        " ".join(entry.get("tags") or []),
    ]).lower()
    return any(token in blob for token in ("quantidade minima", "pedido minimo", "revend", "varej", "atacad", "empreended", "5 pec"))


def _known_colors_from_session(session: dict, plan: dict) -> list[str]:
    blob_parts = [str(session.get("context") or ""), json.dumps(plan, ensure_ascii=False)]
    blob = " ".join(blob_parts).lower()
    known = []
    for color in ("preta", "preto", "vermelha", "vermelho", "roxa", "roxo", "azul", "rosa", "branca", "branco"):
        if color in blob:
            normalized = color[:-1] + "a" if color.endswith("o") else color
            if normalized not in known:
                known.append(normalized)
    return known


def _plan_blob(session: dict, plan: Optional[dict] = None) -> str:
    parts = [str(session.get("context") or "")]
    for message in session.get("messages") or []:
        if isinstance(message, dict):
            parts.append(str(message.get("content") or ""))
    if plan:
        try:
            parts.append(json.dumps(plan, ensure_ascii=False))
        except Exception:
            pass
    return "\n".join(parts)


def _commercial_offer_specs(session: dict, plan: dict) -> list[dict[str, Any]]:
    blob = _plan_blob(session, plan)
    specs: dict[int, dict[str, Any]] = {}
    for match in re.finditer(
        r"(?P<qty>\d+)\s*(?:pe[cç]as?|unidades?|itens?)\s*(?:por|=|:|-)?\s*R\$\s*(?P<price>\d{1,4}(?:[.,]\d{2})?)",
        blob,
        flags=re.IGNORECASE,
    ):
        qty = int(match.group("qty"))
        price = match.group("price")
        if qty <= 0:
            continue
        specs[qty] = {"quantity": qty, "price": price, "audience_role": None}
    for match in re.finditer(
        r"(?P<qty>\d+)\s*(?:pe[cç]as?|unidades?|itens?)",
        blob,
        flags=re.IGNORECASE,
    ):
        qty = int(match.group("qty"))
        if qty > 0:
            specs.setdefault(qty, {"quantity": qty, "price": None, "audience_role": None})
    lowered = blob.lower()
    if re.search(r"\b1\s*pe[cç]a\s+(?:é|e|=|para|pra).{0,80}(cliente|final)", lowered):
        specs.setdefault(1, {"quantity": 1, "price": None, "audience_role": None})["audience_role"] = "final"
    if re.search(r"\b(?:5\s*(?:e|,|/)\s*10|5|10)\s*pe[cç]as?\s+(?:s[aã]o|=|para|pra).{0,100}(empreended|revend|lojist|atacad)", lowered):
        for qty in (5, 10):
            specs.setdefault(qty, {"quantity": qty, "price": None, "audience_role": None})["audience_role"] = "b2b"
    for qty, spec in specs.items():
        if not spec.get("audience_role"):
            spec["audience_role"] = "final" if qty == 1 else "b2b" if qty >= 5 else "any"
    return [specs[key] for key in sorted(specs)]


def _offers_required(session: dict, plan: dict) -> bool:
    if _commercial_offer_specs(session, plan):
        return True
    blob = _plan_blob(session, plan).lower()
    return bool(re.search(r"\b(pre[cç]o|r\$|pacote|op[cç][aã]o|pe[cç]as?)\b", blob))


def _rule_required(session: dict, plan: dict) -> bool:
    blob = _plan_blob(session, plan).lower()
    return bool(re.search(r"\b(regra|1\s*pe[cç]a\s*(?:=|é|e)|5\s*(?:e|,|/)\s*10|n[aã]o inventar|n[aã]o prometer)\b", blob))


def _is_final_audience(entry: dict) -> bool:
    blob = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("content") or ""),
        " ".join(entry.get("tags") or []),
    ]).lower()
    return any(token in blob for token in ("cliente final", "clientes finais", "consumidor", "final"))


def _offer_applies_to_audience(spec: dict[str, Any], audience: Optional[dict]) -> bool:
    role = spec.get("audience_role") or "any"
    if role == "any" or not audience:
        return True
    if role == "b2b":
        return _is_b2b_audience(audience)
    if role == "final":
        return _is_final_audience(audience) or not _is_b2b_audience(audience)
    return True


def _dedupe_slug(base: str, used: set[str]) -> str:
    raw = _slug_for_plan_entry(base)
    if raw not in used:
        used.add(raw)
        return raw
    idx = 2
    while f"{raw}-{idx}" in used:
        idx += 1
    slug = f"{raw}-{idx}"
    used.add(slug)
    return slug


def _governing_scope_slug(entries: list[dict]) -> Optional[str]:
    for ctype in ("campaign", "briefing", "brand"):
        found = next((entry for entry in entries if _entry_type(entry) == ctype and entry.get("slug")), None)
        if found:
            return str(found.get("slug"))
    return "self"


def _ensure_governing_rule(plan: dict, session: dict) -> None:
    if not _rule_required(session, plan):
        return
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    parent_slug = _governing_scope_slug(entries)
    rules = [entry for entry in entries if _entry_type(entry) == "rule"]
    if rules:
        for rule in rules:
            if not _entry_parent_slug(rule):
                _set_entry_parent_slug(rule, parent_slug)
        return
    rule = _normalize_plan_entry({
        "content_type": "rule",
        "title": "Regra comercial por quantidade",
        "slug": "rule-regra-publico-quantidade",
        "status": "pendente_validacao",
        "content": "1 peca se destina a cliente final. Pacotes de 5 e 10 pecas se destinam a empreendedoras/revendedoras. Nao inventar preco, estoque ou disponibilidade sem validacao.",
        "tags": ["rule", "comercial", "quantidade"],
        "metadata": {"parent_slug": parent_slug, "governs_children": True, "rule_scope": "campaign"},
    })
    entries.append(rule)
    plan["entries"] = entries


def _ensure_offer_entries(plan: dict, session: dict) -> None:
    if not _offers_required(session, plan):
        return
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    specs = _commercial_offer_specs(session, plan) or [{"quantity": 1, "price": None, "audience_role": "any"}]
    used = {str(entry.get("slug")) for entry in entries if entry.get("slug")}
    existing_offer_keys = {
        (_entry_parent_slug(entry), str(_entry_metadata(entry).get("quantity") or ""))
        for entry in entries
        if _entry_type(entry) == "offer"
    }
    new_entries: list[dict] = []
    for product in [entry for entry in entries if _entry_type(entry) == "product" and entry.get("slug")]:
        audience = by_slug.get(_entry_parent_slug(product) or "")
        for spec in specs:
            if not _offer_applies_to_audience(spec, audience):
                continue
            qty = int(spec.get("quantity") or 0)
            key = (str(product.get("slug")), str(qty))
            if key in existing_offer_keys:
                continue
            label = f"{qty} peca" if qty == 1 else f"{qty} pecas"
            title = f"{product.get('title')} - {label}"
            if spec.get("price"):
                title = f"{title} R$ {spec['price']}"
            offer = _normalize_plan_entry({
                "content_type": "offer",
                "title": title,
                "slug": _dedupe_slug(f"offer-{product.get('slug')}-{qty}-pecas", used),
                "status": "pendente_validacao",
                "content": f"Oferta comercial de {label} para {product.get('title')}. Preco informado: {spec.get('price') or 'pendente de validacao'}.",
                "tags": ["offer", "preco", "quantidade"],
                "metadata": {
                    "parent_slug": str(product.get("slug")),
                    "quantity": qty,
                    "price": spec.get("price"),
                    "audience_role": spec.get("audience_role"),
                    "commercial_offer": True,
                },
            })
            new_entries.append(offer)
    if new_entries:
        entries.extend(new_entries)
        plan["entries"] = entries


def _ensure_copies_for_offers(plan: dict) -> None:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    offers = [entry for entry in entries if _entry_type(entry) == "offer" and entry.get("slug")]
    if not offers:
        return
    used = {str(entry.get("slug")) for entry in entries if entry.get("slug")}
    by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    copies = [entry for entry in entries if _entry_type(entry) == "copy"]
    product_copy_templates: dict[str, list[dict]] = {}
    for copy in copies:
        parent_slug = _entry_parent_slug(copy)
        parent = by_slug.get(parent_slug or "")
        if _entry_type(parent) == "product":
            product_copy_templates.setdefault(parent_slug or "", []).append(copy)
    remove_copy_slugs: set[str] = set()
    for offer in offers:
        offer_slug = str(offer.get("slug"))
        if any(_entry_parent_slug(copy) == offer_slug for copy in copies):
            continue
        product_slug = _entry_parent_slug(offer) or ""
        templates = product_copy_templates.get(product_slug) or copies
        template = templates[0] if templates else {}
        title = str((template or {}).get("title") or f"Copy para {offer.get('title')}")
        copy = _normalize_plan_entry({
            **(template if isinstance(template, dict) else {}),
            "content_type": "copy",
            "title": title if str(offer.get("title") or "") in title else f"{title} - {offer.get('title')}",
            "slug": _dedupe_slug(f"copy-{offer_slug}", used),
            "status": "pendente_validacao",
            "content": str((template or {}).get("content") or f"Mensagem comercial para {offer.get('title')}."),
            "tags": list(dict.fromkeys([*((template or {}).get("tags") or []), "copy", "offer"])),
            "metadata": {**((template or {}).get("metadata") or {}), "parent_slug": offer_slug, "copied_for_offer": True},
        })
        entries.append(copy)
        copies.append(copy)
        if template and _entry_parent_slug(template) == product_slug:
            remove_copy_slugs.add(str(template.get("slug") or ""))
    if remove_copy_slugs:
        entries[:] = [
            entry for entry in entries
            if _entry_type(entry) != "copy" or str(entry.get("slug") or "") not in remove_copy_slugs
        ]
    plan["entries"] = entries


def _reparent_copies_to_offers(plan: dict) -> None:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    offers = [entry for entry in entries if _entry_type(entry) == "offer" and entry.get("slug")]
    if not offers:
        return
    by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    for copy in [entry for entry in entries if _entry_type(entry) == "copy"]:
        parent = by_slug.get(_entry_parent_slug(copy) or "")
        if _entry_type(parent or {}) == "offer":
            continue
        picked = _best_parent_by_slug(copy, offers) or offers[0]
        if picked and picked.get("slug"):
            _set_entry_parent_slug(copy, str(picked.get("slug")))
    plan["entries"] = entries


def _faq_leaf_entries(plan: dict) -> list[dict]:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    return [
        entry for entry in entries
        if _entry_type(entry) == "copy" and entry.get("slug")
    ] or [
        entry for entry in entries
        if _entry_type(entry) == "offer" and entry.get("slug")
    ] or [
        entry for entry in entries
        if _entry_type(entry) == "product" and entry.get("slug")
    ]


def _ensure_total_faq_policy(plan: dict, session: dict) -> None:
    if (plan.get("tree_mode") or "single_branch") != "single_branch":
        return
    policy = str(plan.get("faq_count_policy") or "total").strip() or "total"
    plan["faq_count_policy"] = policy
    if policy != "total":
        return
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    target = max(0, _requested_variation_count(session, "faq", 8))
    if target <= 0:
        return
    leaves = _faq_leaf_entries(plan)
    if not leaves:
        return
    used = {str(entry.get("slug")) for entry in entries if entry.get("slug")}
    faqs = [entry for entry in entries if _entry_type(entry) == "faq"]
    for idx, faq in enumerate(faqs):
        leaf = leaves[idx % len(leaves)]
        if _entry_type(leaf) == "copy":
            _set_entry_parent_slug(faq, str(leaf.get("slug")))
        elif not _entry_parent_slug(faq):
            _set_entry_parent_slug(faq, str(leaf.get("slug")))
    if len(faqs) > target:
        keep = set(id(entry) for entry in faqs[:target])
        entries[:] = [entry for entry in entries if _entry_type(entry) != "faq" or id(entry) in keep]
        faqs = faqs[:target]
    slot = len(faqs) + 1
    while len(faqs) < target:
        leaf = leaves[(slot - 1) % len(leaves)]
        title = f"FAQ {slot} - {leaf.get('title')}"
        faq = _normalize_plan_entry({
            "content_type": "faq",
            "title": title,
            "slug": _dedupe_slug(f"faq-{slot}-{leaf.get('slug')}", used),
            "status": "pendente_validacao",
            "content": f"Pergunta e resposta comercial sobre {leaf.get('title')}. Validar detalhes antes de publicar.",
            "tags": ["faq", "pendente-validacao"],
            "metadata": {"parent_slug": str(leaf.get("slug")), "faq_count_policy": "total", "fractal_generated": True},
        })
        entries.append(faq)
        faqs.append(faq)
        slot += 1
    plan["entries"] = entries


def _dedupe_plan_entries(plan: dict) -> None:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    used: set[str] = set()
    remap: dict[str, str] = {}
    for index, entry in enumerate(entries, 1):
        old_slug = str(entry.get("slug") or _slug_for_plan_entry(entry.get("title") or f"entry-{index}"))
        if _entry_type(entry) == "product" and "-audience-" in old_slug:
            old_slug = old_slug.split("-audience-", 1)[0]
        new_slug = _dedupe_slug(old_slug, used)
        original_slug = str(entry.get("slug") or "")
        if new_slug != original_slug:
            if original_slug:
                remap[original_slug] = new_slug
            remap[old_slug] = new_slug
            entry["slug"] = new_slug
        meta = _entry_metadata(entry)
        meta.setdefault("plan_entry_id", f"plan-{index:03d}-{new_slug}")
        meta.setdefault("client_id", meta["plan_entry_id"])
    if remap:
        for entry in entries:
            parent = _entry_parent_slug(entry)
            if parent in remap:
                _set_entry_parent_slug(entry, remap[parent])
        for link in plan.get("links") or []:
            if not isinstance(link, dict):
                continue
            if link.get("source_slug") in remap:
                link["source_slug"] = remap[link["source_slug"]]
            if link.get("target_slug") in remap:
                link["target_slug"] = remap[link["target_slug"]]
    plan["entries"] = entries


def _clone_plan_entry(template: dict, *, title: str, slug: str, parent_slug: str, content: str, tags: Optional[list[str]] = None) -> dict:
    clone = _normalize_plan_entry(template)
    clone["title"] = title
    clone["slug"] = slug
    clone["content"] = content
    clone["status"] = "pendente_validacao"
    clone["tags"] = [str(tag).strip() for tag in (tags or clone.get("tags") or []) if str(tag).strip()]
    metadata = dict(clone.get("metadata") or {})
    metadata["parent_slug"] = parent_slug
    metadata["fractal_generated"] = True
    clone["metadata"] = metadata
    return clone


def _default_faq_payload(*, audience: dict, product: dict, slot_index: int, colors: list[str]) -> tuple[str, str, list[str]]:
    product_title = str(product.get("title") or "Produto")
    audience_title = str(audience.get("title") or "")
    color_text = ", ".join(colors) if colors else "as cores disponiveis"
    if _is_b2b_audience(audience):
        defaults = [
            (
                f"Quantidade minima para revenda de {product_title}",
                f"Para {audience_title or 'revendedores'}, {product_title} segue a regra comercial de pedido minimo para revenda. "
                "Use a validacao humana para confirmar o lote minimo e destaque a regra vigente somente quando ela estiver confirmada na fonte ou pelo operador.",
                ["faq", "revenda", "pedido-minimo"],
            ),
            (
                f"Cores, preco e politica do pedido de {product_title}",
                f"Para {audience_title or 'revendedores'}, confirme cores disponiveis, faixa de preco e politica comercial de {product_title}. "
                f"As cores citadas ate agora sao {color_text}. Mantenha a resposta como pendente_validacao ate revisar a fonte final.",
                ["faq", "revenda", "pedido"],
            ),
        ]
    else:
        defaults = [
            (
                f"Cores disponiveis de {product_title}",
                f"Para {audience_title or 'clientes finais'}, explique quais cores estao disponiveis para {product_title}. "
                f"Use {color_text} como referencia inicial e marque qualquer variacao adicional como pendente_validacao.",
                ["faq", "cores", "cliente-final"],
            ),
            (
                f"Preco, conforto e beneficios de {product_title}",
                f"Para {audience_title or 'clientes finais'}, responda como {product_title} combina preco, conforto, uso e beneficios. "
                "Nao invente valores finais; sinalize como pendente_validacao quando a fonte nao confirmar.",
                ["faq", "beneficios", "cliente-final"],
            ),
        ]
    return defaults[(slot_index - 1) % len(defaults)]


def _build_links_from_parent_slugs(plan: dict) -> None:
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    slug_to_type = {str(entry.get("slug")): _entry_type(entry) for entry in entries if entry.get("slug")}
    deduped: dict[tuple[str, str], dict] = {}
    for link in plan.get("links") or []:
        if not isinstance(link, dict):
            continue
        source_slug = str(link.get("source_slug") or "").strip()
        target_slug = str(link.get("target_slug") or "").strip()
        if not source_slug or not target_slug:
            continue
        deduped[(source_slug, target_slug)] = {
            "source_slug": source_slug,
            "target_slug": target_slug,
            "relation_type": str(link.get("relation_type") or "").strip() or _relation_type_for_parent(
                slug_to_type.get(source_slug, ""),
                slug_to_type.get(target_slug, ""),
            ),
        }
    for entry in entries:
        source_slug = _entry_parent_slug(entry)
        target_slug = str(entry.get("slug") or "").strip()
        if not source_slug or not target_slug or source_slug == target_slug:
            continue
        deduped[(source_slug, target_slug)] = {
            "source_slug": source_slug,
            "target_slug": target_slug,
            "relation_type": _relation_type_for_parent(slug_to_type.get(source_slug, ""), _entry_type(entry)),
        }
    plan["links"] = list(deduped.values())


def _copy_parent_slug_for_product(entries_by_slug: dict[str, dict], product_slug: str, faq: Optional[dict] = None) -> Optional[str]:
    copies = [
        entry
        for entry in entries_by_slug.values()
        if _entry_type(entry) == "copy" and _entry_parent_slug(entry) == product_slug and entry.get("slug")
    ]
    if not copies:
        return None
    if faq:
        picked = _best_parent_by_slug(faq, copies)
        if picked and picked.get("slug"):
            return str(picked["slug"])
    return str(copies[-1]["slug"])


def _base_product_slug(entry: dict) -> str:
    meta = _entry_metadata(entry)
    return str(meta.get("fractal_base_slug") or entry.get("slug") or "").strip()


def _fractal_base_product_slug(entry: dict) -> str:
    raw = _base_product_slug(entry)
    raw = raw.split("-audience-", 1)[0]
    return re.sub(r"-branch-\d+$", "", raw)


def _find_scoped_copy_for_product(entries: list[dict], product: dict, template: Optional[dict] = None) -> Optional[dict]:
    product_slug = str(product.get("slug") or "")
    copies = [
        entry
        for entry in entries
        if _entry_type(entry) == "copy" and _entry_parent_slug(entry) == product_slug and entry.get("slug")
    ]
    if not copies:
        return None
    if template:
        picked = _best_parent_by_slug(template, copies)
        if picked:
            return picked
    return copies[-1]


def _faq_parent_slug_for_product(entries: list[dict], product: dict, plan: dict, session: dict, template: Optional[dict] = None) -> Optional[str]:
    product_slug = str(product.get("slug") or "")
    if not product_slug:
        return None
    if (plan.get("tree_mode") or "single_branch") != "single_branch":
        return product_slug
    if _technical_product_faq_requested(session):
        return product_slug
    copy = _find_scoped_copy_for_product(entries, product, template)
    return str(copy.get("slug")) if copy and copy.get("slug") else product_slug


def _clone_product_scoped_entry(template: dict, *, product: dict, parent_slug: str, suffix: Optional[str] = None) -> dict:
    base_slug = str(template.get("slug") or _slug_for_plan_entry(template.get("title") or "entry"))
    product_slug = str(product.get("slug") or "")
    clone_slug = f"{base_slug}-{product_slug}" if product_slug and product_slug not in base_slug else base_slug
    if suffix:
        clone_slug = f"{clone_slug}-{suffix}"
    clone = _clone_plan_entry(
        template,
        title=str(template.get("title") or product.get("title") or "Conhecimento"),
        slug=clone_slug,
        parent_slug=parent_slug,
        content=str(template.get("content") or template.get("title") or ""),
        tags=template.get("tags") or [],
    )
    meta = _entry_metadata(clone)
    meta["fractal_base_slug"] = str(template.get("slug") or "")
    meta["fractal_product_slug"] = product_slug
    return clone


def _expand_copies_for_products(entries: list[dict], products: list[dict], product_expansions: dict[str, list[str]]) -> None:
    if not products:
        return
    product_by_slug = {str(product.get("slug")): product for product in products if product.get("slug")}
    entry_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    copies = [entry for entry in list(entries) if _entry_type(entry) == "copy"]
    if not copies:
        return

    remove: set[str] = set()
    clones: list[dict] = []
    for copy in copies:
        copy_slug = str(copy.get("slug") or "")
        parent_slug = _entry_parent_slug(copy)
        if _entry_type(entry_by_slug.get(parent_slug or "", {})) == "offer":
            continue
        parent_product = product_by_slug.get(parent_slug or "")
        if parent_product:
            continue

        scoped_products: list[dict] = []
        if parent_slug and parent_slug in product_expansions:
            scoped_products = [
                product_by_slug[slug]
                for slug in product_expansions[parent_slug]
                if slug in product_by_slug
            ]
        if not scoped_products:
            picked = _best_parent_by_slug(copy, products)
            if picked and picked.get("slug"):
                scoped_products = [picked]
            elif len(products) == 1:
                scoped_products = [products[0]]
            else:
                scoped_products = list(products)

        if not scoped_products:
            continue
        if len(scoped_products) == 1 and not (parent_slug and parent_slug in product_expansions and len(product_expansions[parent_slug]) > 1):
            _set_entry_parent_slug(copy, str(scoped_products[0].get("slug") or ""))
            continue
        remove.add(copy_slug)
        for product in scoped_products:
            parent = str(product.get("slug") or "")
            clone = _clone_product_scoped_entry(copy, product=product, parent_slug=parent)
            clones.append(clone)

    if remove:
        entries[:] = [entry for entry in entries if str(entry.get("slug") or "") not in remove]
        entries.extend(clones)


def _apply_native_single_branch_faq_parents(plan: dict, session: dict) -> int:
    if (plan.get("tree_mode") or "single_branch") != "single_branch":
        return 0
    if _technical_product_faq_requested(session):
        return 0
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    changed = 0
    for faq in [entry for entry in entries if _entry_type(entry) == "faq"]:
        parent_slug = _entry_parent_slug(faq)
        parent = entries_by_slug.get(parent_slug or "")
        product_slug: Optional[str] = None
        if _entry_type(parent or {}) == "copy":
            continue
        if _entry_type(parent or {}) == "product":
            product_slug = str(parent_slug)
        elif not parent_slug:
            product = _best_parent_by_slug(faq, [entry for entry in entries if _entry_type(entry) == "product"])
            product_slug = str(product.get("slug")) if product and product.get("slug") else None
        if not product_slug:
            continue
        copy_slug = _copy_parent_slug_for_product(entries_by_slug, product_slug, faq)
        if not copy_slug or copy_slug == parent_slug:
            continue
        _set_entry_parent_slug(faq, copy_slug)
        changed += 1
    return changed


def _apply_single_branch_policy(plan: dict, session: dict) -> int:
    """Legacy airbag for product -> faq plans that escaped native planning.

    Parallel product children are only preserved when the operator explicitly
    asked for them or the prompt asks for technical/factual product FAQ.
    """
    if (plan.get("tree_mode") or "single_branch") != "single_branch":
        return 0
    if _technical_product_faq_requested(session):
        return 0
    entries = [entry for entry in (plan.get("entries") or []) if isinstance(entry, dict)]
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    rewrites = 0
    for faq in [entry for entry in entries if _entry_type(entry) == "faq"]:
        parent_slug = _entry_parent_slug(faq)
        parent = entries_by_slug.get(parent_slug or "")
        product_slug: Optional[str] = None
        if _entry_type(parent or {}) == "product":
            product_slug = str(parent_slug)
        elif not parent_slug:
            product = _best_parent_by_slug(faq, [entry for entry in entries if _entry_type(entry) == "product"])
            product_slug = str(product.get("slug")) if product and product.get("slug") else None
        if not product_slug:
            continue
        copy_slug = _copy_parent_slug_for_product(entries_by_slug, product_slug, faq)
        if not copy_slug or copy_slug == parent_slug:
            continue
        _set_entry_parent_slug(faq, copy_slug)
        metadata = _entry_metadata(faq)
        metadata.setdefault("single_branch_parent_rewritten", True)
        metadata.setdefault("previous_parent_slug", product_slug)
        warnings = plan.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append({
                "warning_type": "planner_parent_rewrite",
                "message": "Planner generated product -> faq, but single_branch policy required copy -> faq.",
                "original_parent_slug": product_slug,
                "resolved_parent_slug": copy_slug,
                "should_fix_planner": True,
            })
        rewrites += 1
    return rewrites


def _normalize_sofia_knowledge_plan(plan: dict, session: dict) -> dict:
    normalized = dict(plan or {})
    normalized["source"] = str(normalized.get("source") or _source_url_from_context(str(session.get("context") or "")) or "session").strip()
    normalized["persona_slug"] = str(normalized.get("persona_slug") or (session.get("classification") or {}).get("persona_slug") or "global").strip()
    normalized["validation_policy"] = str(normalized.get("validation_policy") or "human_validation_required").strip()
    raw_tree_mode = str(normalized.get("tree_mode") or "").strip()
    if raw_tree_mode != "single_branch":
        raw_tree_mode = "single_branch"
    normalized["tree_mode"] = raw_tree_mode
    normalized["branch_policy"] = "single_branch_by_default"
    normalized["faq_count_policy"] = str(normalized.get("faq_count_policy") or "total").strip() or "total"

    entries = [_normalize_plan_entry(entry) for entry in (normalized.get("entries") or []) if isinstance(entry, dict)]
    normalized["entries"] = entries
    _normalize_plan_parent_slugs(normalized, normalized["persona_slug"])

    # Root scaffolding: persona -> brand? -> briefing -> campaign? -> audience.
    # A briefing without brand is a valid first real node below persona; never
    # leave it pointing to loose sentinels such as "global".
    brands = [entry for entry in entries if _entry_type(entry) == "brand"]
    briefings = [entry for entry in entries if _entry_type(entry) == "briefing"]
    campaigns = [entry for entry in entries if _entry_type(entry) == "campaign"]
    audiences = [entry for entry in entries if _entry_type(entry) == "audience"]
    root_brand = brands[0] if brands else None
    root_briefing = briefings[0] if briefings else None
    root_campaign = campaigns[0] if campaigns else None

    if root_briefing is None:
        title = _knowledge_plan_title_from_session(session)
        root_briefing = _normalize_plan_entry({
            "content_type": "briefing",
            "title": title,
            "slug": _slug_for_plan_entry(title),
            "status": "pendente_validacao",
            "content": f"Briefing operacional para {title}. Fonte principal: {normalized['source']}.",
            "tags": ["briefing", normalized["persona_slug"]],
            "metadata": {},
        })
        entries.insert(0, root_briefing)

    if root_brand and _entry_parent_slug(root_brand) in {None, "", "global", "root", "persona"}:
        _set_entry_parent_slug(root_brand, "self")
    briefing_parent = _entry_parent_slug(root_briefing) if root_briefing else None
    if root_briefing and (
        briefing_parent in {None, "", "global", "root", "persona"}
        or (root_brand and briefing_parent == "self")
    ):
        _set_entry_parent_slug(root_briefing, str((root_brand or {}).get("slug") or "self"))
    if root_campaign and not _entry_parent_slug(root_campaign):
        _set_entry_parent_slug(root_campaign, root_briefing["slug"])
    for audience in audiences:
        if not _entry_parent_slug(audience):
            _set_entry_parent_slug(audience, (root_campaign or root_briefing)["slug"])

    colors = _known_colors_from_session(session, normalized)
    faq_policy = str(normalized.get("faq_count_policy") or "total").strip() or "total"
    target_faq_count = 0 if faq_policy == "total" else max(1, _requested_variation_count(session, "faq", 2))

    # Product branches must live under each audience. If products are still generic,
    # clone them once per audience to create the fractal top-down structure.
    products = [entry for entry in list(entries) if _entry_type(entry) == "product"]
    audience_map = {str(entry.get("slug")): entry for entry in entries if _entry_type(entry) == "audience" and entry.get("slug")}
    product_expansions: dict[str, list[str]] = {}
    if audience_map:
        expanded_products: list[dict] = []
        remove_slugs: set[str] = set()
        existing_product_slugs = {str(product.get("slug")) for product in products if product.get("slug")}
        audience_index = {slug: index for index, slug in enumerate(audience_map.keys(), 1)}
        requested_product_count = _requested_variation_count(session, "product", len(products) or 0)
        distribute_without_cloning = (
            _has_explicit_variation_count(session, "product")
            and requested_product_count > 0
            and len(products) >= requested_product_count
        )
        audience_order = list(audience_map.keys())
        audience_slugs = set(audience_map.keys())
        coverage_by_base: dict[str, set[str]] = {}
        product_slugs_by_base: dict[str, list[str]] = {}
        for product in products:
            parent_slug = _entry_parent_slug(product)
            if parent_slug not in audience_map:
                continue
            base = _fractal_base_product_slug(product)
            coverage_by_base.setdefault(base, set()).add(str(parent_slug))
            if product.get("slug"):
                product_slugs_by_base.setdefault(base, []).append(str(product.get("slug")))
        complete_bases = {
            base for base, covered in coverage_by_base.items()
            if audience_slugs and audience_slugs.issubset(covered)
        }
        for product_index, product in enumerate(products):
            parent_slug = _entry_parent_slug(product)
            parent_type = _entry_type(audience_map.get(parent_slug, {})) if parent_slug else ""
            base_slug = str(product.get("slug"))
            branch_base_slug = _fractal_base_product_slug(product)
            if parent_type == "audience":
                if branch_base_slug in complete_bases:
                    product_expansions[branch_base_slug] = list(dict.fromkeys(product_slugs_by_base.get(branch_base_slug, [base_slug])))
                    product_expansions.setdefault(base_slug, [base_slug])
                    continue
                product_expansions.setdefault(base_slug, [base_slug])
                if len(audience_map) == 1 or distribute_without_cloning:
                    continue
                for audience_slug, audience in audience_map.items():
                    if audience_slug == parent_slug:
                        continue
                    clone_slug = _dedupe_slug(f"{branch_base_slug}-branch-{audience_index.get(audience_slug, 1)}", existing_product_slugs)
                    clone = _clone_plan_entry(
                        product,
                        title=product["title"],
                        slug=clone_slug,
                        parent_slug=audience_slug,
                        content=str(product.get("content") or ""),
                        tags=product.get("tags") or [],
                    )
                    clone_meta = _entry_metadata(clone)
                    clone_meta["fractal_base_slug"] = base_slug
                    expanded_products.append(clone)
                    product_expansions.setdefault(base_slug, [base_slug]).append(clone_slug)
                continue
            if len(audience_map) == 1:
                _set_entry_parent_slug(product, next(iter(audience_map.keys())))
                product_expansions.setdefault(base_slug, [base_slug])
                continue
            if distribute_without_cloning and audience_order:
                _set_entry_parent_slug(product, audience_order[product_index % len(audience_order)])
                product_expansions.setdefault(base_slug, [base_slug])
                continue
            remove_slugs.add(base_slug)
            for audience_slug, audience in audience_map.items():
                clone_slug = _dedupe_slug(f"{branch_base_slug}-branch-{audience_index.get(audience_slug, 1)}", existing_product_slugs)
                clone = _clone_plan_entry(
                    product,
                    title=product["title"],
                    slug=clone_slug,
                    parent_slug=audience_slug,
                    content=str(product.get("content") or ""),
                    tags=product.get("tags") or [],
                )
                clone_meta = _entry_metadata(clone)
                clone_meta["fractal_base_slug"] = base_slug
                expanded_products.append(clone)
                product_expansions.setdefault(base_slug, []).append(clone_slug)
        if remove_slugs:
            entries[:] = [entry for entry in entries if str(entry.get("slug")) not in remove_slugs]
        if expanded_products:
            entries.extend(expanded_products)

    # Copies and FAQs replicate per audience->product branch. In the default
    # single_branch marketing policy, FAQs are born below copy before save.
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    products = [entry for entry in entries if _entry_type(entry) == "product"]
    normalized["entries"] = entries
    _ensure_offer_entries(normalized, session)
    entries = [entry for entry in (normalized.get("entries") or []) if isinstance(entry, dict)]
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    products = [entry for entry in entries if _entry_type(entry) == "product"]
    _expand_copies_for_products(entries, products, product_expansions)
    normalized["entries"] = entries
    _ensure_copies_for_offers(normalized)
    _reparent_copies_to_offers(normalized)
    entries = [entry for entry in (normalized.get("entries") or []) if isinstance(entry, dict)]
    _apply_native_single_branch_faq_parents(normalized, session)
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    products = [entry for entry in entries if _entry_type(entry) == "product"]
    copies = [entry for entry in entries if _entry_type(entry) == "copy"]
    copy_slugs = {str(copy.get("slug")) for copy in copies if copy.get("slug")}
    existing_faqs = [entry for entry in entries if _entry_type(entry) == "faq"]
    global_templates = [
        entry for entry in existing_faqs
        if _entry_parent_slug(entry) not in entries_by_slug
        or _entry_type(entries_by_slug.get(_entry_parent_slug(entry), {})) not in {"product", "copy"}
    ]
    faq_count_by_product: dict[str, list[dict]] = {}
    for faq in existing_faqs:
        parent_slug = _entry_parent_slug(faq)
        if parent_slug and _entry_type(entries_by_slug.get(parent_slug, {})) == "product":
            faq_count_by_product.setdefault(parent_slug, []).append(faq)
        elif parent_slug and _entry_type(entries_by_slug.get(parent_slug, {})) == "copy":
            copy_parent_slug = _entry_parent_slug(entries_by_slug.get(parent_slug, {}))
            if copy_parent_slug:
                faq_count_by_product.setdefault(copy_parent_slug, []).append(faq)
    for product in products:
        product_slug = str(product.get("slug"))
        audience = entries_by_slug.get(_entry_parent_slug(product) or "")
        branch_faqs = faq_count_by_product.setdefault(product_slug, [])
        templates = list(branch_faqs)
        if not templates:
            audience_slug = str((audience or {}).get("slug") or "")
            audience_templates = []
            for candidate in existing_faqs:
                candidate_parent = entries_by_slug.get(_entry_parent_slug(candidate) or "")
                if _entry_type(candidate_parent) == "audience" and str(candidate_parent.get("slug")) == audience_slug:
                    audience_templates.append(candidate)
            templates = audience_templates or global_templates
        slot_index = len(branch_faqs) + 1
        while len(branch_faqs) < target_faq_count:
            if templates:
                template = templates[(slot_index - 1) % len(templates)]
                template_title = str(template.get("title") or "")
                template_content = str(template.get("content") or "")
                if audience and not _is_b2b_audience(audience) and _is_b2b_faq(template):
                    title, content, tags = _default_faq_payload(
                        audience=audience,
                        product=product,
                        slot_index=slot_index,
                        colors=colors,
                    )
                else:
                    previous_parent_title = str(entries_by_slug.get(_entry_parent_slug(template) or "", {}).get("title") or "")
                    title = (
                        template_title.replace(previous_parent_title, str(product.get("title") or "")).strip()
                        if previous_parent_title
                        else template_title.strip()
                    )
                    if not title or title == template_title:
                        title = f"{template_title} — {product.get('title')}"
                    content = template_content or title
                    tags = template.get("tags") or []
                clone = _clone_plan_entry(
                    template,
                    title=title,
                    slug=f"{_slug_for_plan_entry(title)}-{slot_index}",
                    parent_slug=_faq_parent_slug_for_product(entries, product, normalized, session, template) or product_slug,
                    content=content,
                    tags=tags,
                )
            else:
                title, content, tags = _default_faq_payload(
                    audience=audience or {"title": ""},
                    product=product,
                    slot_index=slot_index,
                    colors=colors,
                )
                clone = _normalize_plan_entry({
                    "content_type": "faq",
                    "title": title,
                    "slug": f"{_slug_for_plan_entry(title)}-{slot_index}",
                    "status": "pendente_validacao",
                    "content": content,
                    "tags": tags,
                    "metadata": {"parent_slug": _faq_parent_slug_for_product(entries, product, normalized, session) or product_slug, "fractal_generated": True},
                })
            entries.append(clone)
            branch_faqs.append(clone)
            slot_index += 1

    if products:
        product_slugs = {str(product.get("slug")) for product in products if product.get("slug")}
        copy_slugs = {str(copy.get("slug")) for copy in entries if _entry_type(copy) == "copy" and copy.get("slug")}
        entries[:] = [
            entry for entry in entries
            if _entry_type(entry) != "faq" or (_entry_parent_slug(entry) in product_slugs or _entry_parent_slug(entry) in copy_slugs)
        ]

    # Product children should never stay directly under campaign/root when audiences exist.
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    for faq in [entry for entry in entries if _entry_type(entry) == "faq"]:
        parent_slug = _entry_parent_slug(faq)
        parent_type = _entry_type(entries_by_slug.get(parent_slug, {}))
        if not parent_slug or parent_type not in {"product", "copy"}:
            candidate_products = [product for product in products if product.get("slug")]
            best_parent = _best_parent_by_slug(faq, candidate_products)
            if best_parent is not None:
                _set_entry_parent_slug(faq, str(best_parent.get("slug")))

    normalized["entries"] = entries
    _ensure_governing_rule(normalized, session)
    _ensure_total_faq_policy(normalized, session)
    _dedupe_plan_entries(normalized)
    _auto_infer_parent_slugs(normalized)
    _apply_native_single_branch_faq_parents(normalized, session)
    _apply_single_branch_policy(normalized, session)
    _normalize_plan_parent_slugs(normalized, normalized["persona_slug"])
    _build_links_from_parent_slugs(normalized)
    normalized["summary"] = summarize_normalized_plan(normalized)
    return normalized


def _normalize_live_session_plan(plan: dict, session: dict) -> dict:
    normalized = dict(plan or {})
    normalized["source"] = str(
        normalized.get("source")
        or session.get("source_url")
        or _source_url_from_context(str(session.get("context") or ""))
        or "session"
    ).strip()
    normalized["persona_slug"] = str(
        normalized.get("persona_slug")
        or session.get("persona_slug")
        or (session.get("classification") or {}).get("persona_slug")
        or "global"
    ).strip()
    normalized["validation_policy"] = str(normalized.get("validation_policy") or "human_validation_required").strip()
    normalized["tree_mode"] = str(normalized.get("tree_mode") or "single_branch").strip() or "single_branch"
    normalized["branch_policy"] = str(normalized.get("branch_policy") or "single_branch_by_default").strip() or "single_branch_by_default"
    normalized["entries"] = [
        _normalize_plan_entry(entry)
        for entry in (normalized.get("entries") or [])
        if isinstance(entry, dict)
    ]
    links: list[dict[str, str]] = []
    for link in normalized.get("links") or []:
        if not isinstance(link, dict):
            continue
        source_slug = str(link.get("source_slug") or "").strip()
        target_slug = str(link.get("target_slug") or "").strip()
        if not source_slug or not target_slug:
            continue
        links.append({
            "source_slug": source_slug,
            "target_slug": target_slug,
            "relation_type": str(link.get("relation_type") or "contains").strip() or "contains",
        })
    normalized["links"] = links
    return normalized


def _rewrite_visible_plan_summary(message: str, plan_payload: Optional[dict]) -> str:
    if not message or not isinstance(plan_payload, dict):
        return message
    summary = summarize_normalized_plan(plan_payload)
    counts = summary.get("current_block_counts") or {}
    summary_line = (
        "Resumo normalizado: "
        f"{summary.get('entry_count', 0)} entries; "
        f"públicos={counts.get('audience', 0)}, produtos={counts.get('product', 0)}, "
        f"ofertas={counts.get('offer', 0)}, copys={counts.get('copy', 0)}, "
        f"FAQs={counts.get('faq', 0)}, regras={counts.get('rule', 0)}."
    )
    link_count = len(plan_payload.get("links") or [])
    if re.search(r"(?im)^Conex\S*:\s*\d+\s+edges no plano\s*$", message):
        updated = re.sub(
            r"(?im)^Conex\S*:\s*\d+\s+edges no plano\s*$",
            f"Conexões: {link_count} edges no plano",
            message,
        )
        return updated if summary_line in updated else f"{updated}\n{summary_line}"
    if link_count > 0 and "Plano pronto. Clique em **Salvar** para persistir." in message:
        return message.replace(
            "Plano pronto. Clique em **Salvar** para persistir.",
            f"Conexões: {link_count} edges no plano\n{summary_line}\nPlano pronto. Clique em **Salvar** para persistir.",
        )
    return message if summary_line in message else f"{message}\n\n{summary_line}"


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
    persona_slug = session.get("persona_slug") or cls.get("persona_slug")
    return {
        "session_id": session.get("id"),
        "agent_key": session.get("agent_key"),
        "agent_name": session.get("agent_name"),
        "model": session.get("model"),
        "persona_slug": persona_slug,
        "content_type": cls.get("content_type"),
        "title": cls.get("title"),
        "stage": session.get("stage"),
        "source_url": session.get("source_url"),
        "initial_block_counts": session.get("initial_block_counts"),
        "current_block_counts": session.get("current_block_counts"),
        "tree_mode": ((session.get("knowledge_plan") or {}).get("tree_mode") if isinstance(session.get("knowledge_plan"), dict) else None),
        "branch_policy": ((session.get("knowledge_plan") or {}).get("branch_policy") if isinstance(session.get("knowledge_plan"), dict) else None),
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
    try:
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
    except Exception as exc:
        try:
            from services import sre_logger
            sre_logger.warn(
                "kb_intake_event",
                f"event emission skipped type={event_type} source={source}: {exc}",
                exc,
            )
        except Exception:
            pass


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
    persona = "global"
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


def _session_matches_resume_candidate(
    session: dict,
    *,
    persona_slug: str | None,
    agent_key: str,
    objective: str,
    source_url: str | None,
) -> bool:
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
    if source_url:
        candidate_source = str(((session.get("mission_state") or {}).get("source") or {}).get("url") or "").strip().lower()
        if candidate_source and candidate_source != source_url.strip().lower():
            return False
    return True


def _latest_local_resume_session(initial_context: str, agent_key: str) -> Optional[dict]:
    persona_slug = _context_persona_slug(initial_context)
    objective = _context_objective(initial_context)
    source_url = _source_url_from_context(initial_context)
    candidates: list[tuple[float, dict]] = []
    try:
        if not _SESSION_DIR.exists():
            return None
        for path in _SESSION_DIR.glob("*.json"):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not _session_matches_resume_candidate(
                session,
                persona_slug=persona_slug,
                agent_key=agent_key,
                objective=objective,
                source_url=source_url,
            ):
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
    source_url = (_source_url_from_context(initial_context) or "").strip().lower()
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
        candidate_source = str(payload.get("source") or "").strip().lower()
        if source_url and candidate_source and candidate_source != source_url:
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


def _session_public_state(session: dict) -> dict[str, Any]:
    normalized_plan = session.get("normalized_plan") or session.get("knowledge_plan")
    plan_summary = session.get("plan_summary") or (
        summarize_normalized_plan(normalized_plan) if isinstance(normalized_plan, dict) else None
    )
    plan_validation = session.get("plan_validation") or _plan_validation(warnings=session.get("plan_validation_warnings") or [])
    plan_hash = session.get("plan_hash") or (_plan_hash(normalized_plan) if isinstance(normalized_plan, dict) else None)
    plan_state = None
    if isinstance(normalized_plan, dict) and normalized_plan.get("entries"):
        plan_state = {
            "normalized_plan": normalized_plan,
            "validation": plan_validation,
            "summary": plan_summary,
            "plan_hash": plan_hash,
        }
    return {
        "persona_slug": session.get("persona_slug") or (session.get("classification") or {}).get("persona_slug"),
        "source_url": session.get("source_url"),
        "mode": session.get("mode") or "legacy",
        "status": session.get("status") or session.get("stage"),
        "initial_block_counts": _normalize_block_counts(session.get("initial_block_counts")),
        "current_block_counts": _normalize_block_counts((plan_summary or {}).get("current_block_counts") or session.get("current_block_counts")),
        "knowledge_plan": normalized_plan,
        "normalized_plan": normalized_plan,
        "plan_state": plan_state,
        "plan_validation": plan_validation,
        "plan_summary": plan_summary,
        "plan_hash": plan_hash,
        "confirmed_plan_hash": session.get("confirmed_plan_hash"),
        "memory_summary": session.get("memory_summary") or "",
        "plan_changed": bool(session.get("plan_changed")),
    }


def _bootstrap_result_payload(session: dict, result: dict[str, Any]) -> dict[str, Any]:
    live_state = _session_public_state(session)
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
        "knowledge_plan": live_state["knowledge_plan"] or result.get("proposed_plan"),
        "normalized_plan": live_state.get("normalized_plan"),
        "plan_state": live_state.get("plan_state") or result.get("plan_state"),
        "plan_validation": live_state.get("plan_validation"),
        "plan_summary": live_state.get("plan_summary"),
        "plan_hash": live_state.get("plan_hash"),
        "confirmed_plan_hash": live_state.get("confirmed_plan_hash"),
        "current_block_counts": live_state["current_block_counts"],
        "initial_block_counts": live_state["initial_block_counts"],
        "persona_slug": live_state["persona_slug"],
        "source_url": live_state["source_url"],
        "memory_summary": live_state["memory_summary"],
        "plan_changed": bool(result.get("plan_changed")),
    }


def _persona_to_slug(raw: str) -> str:
    val = _fold(raw).strip()
    return _PERSONA_ALIASES.get(val, val.replace(" ", "-"))


def _coerce_urlish_value(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.strip("`'\"()[]{}<>.,; ")
    if not raw:
        return None
    if re.match(r"^https?://[^\s/$.?#].[^\s]*$", raw, re.I):
        return raw
    if re.match(r"^(?:www\.)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s]*)?$", raw, re.I):
        return f"https://{raw}"
    return None


def _persona_from_urlish(value: str) -> str | None:
    site = _coerce_urlish_value(value)
    if not site:
        return None
    host = re.sub(r"^https?://", "", site, flags=re.I).split("/", 1)[0].strip().lower()
    return _PERSONA_DOMAINS.get(host)


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

    if not patch:
        site = _coerce_urlish_value(text)
        if site:
            state["source"] = {"type": "website", "url": site}
            inferred_persona = _persona_from_urlish(site)
            if inferred_persona and (state.get("persona") in {None, "", "global"}):
                state["persona"] = inferred_persona
                patch["persona"] = inferred_persona
            patch["source.url"] = site

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


def create_session(
    model: str = "gpt-4o-mini",
    initial_context: str = "",
    agent_key: str = "sofia",
    initial_state: Optional[dict[str, Any]] = None,
) -> dict:
    sid = str(uuid.uuid4())
    agent = get_agent_profile(agent_key)
    created_at = datetime.now(timezone.utc).isoformat()
    resume_meta = _build_resume_metadata(initial_context or "", agent_key if agent_key in AGENT_PROFILES else "sofia")
    initial_state = dict(initial_state or {})
    persona_slug = str(initial_state.get("persona_slug") or _context_persona_slug(initial_context or "") or "").strip().lower()
    source_url = _coerce_urlish_value(str(initial_state.get("source_url") or "")) or _source_url_from_context(initial_context or "")
    mode = str(initial_state.get("mode") or "legacy").strip().lower() or "legacy"
    initial_block_counts = _normalize_block_counts(initial_state.get("initial_block_counts"))
    initial_plan = initial_state.get("knowledge_plan") if isinstance(initial_state.get("knowledge_plan"), dict) else None
    current_block_counts = _counts_from_plan_or_initial(initial_plan, initial_block_counts)
    mission_state = _default_mission_state(initial_context or "")
    if persona_slug:
        mission_state["persona"] = persona_slug
    if source_url:
        mission_state["source"] = {"type": "website", "url": source_url}
    session = {
        "id": sid,
        "model": model,
        "agent_key": agent_key if agent_key in AGENT_PROFILES else "sofia",
        "agent_name": agent["name"],
        "agent_role": agent["role"],
        "agent_greeting": agent["greeting"],
        "stage": "chatting",
        "mode": mode,
        "status": "collecting",
        "persona_slug": persona_slug or None,
        "source_url": source_url,
        "initial_block_counts": initial_block_counts,
        "current_block_counts": current_block_counts,
        "knowledge_plan": initial_plan,
        "memory_summary": str(initial_state.get("memory_summary") or "").strip(),
        "plan_changed": False,
        "messages": [],
        "context": _context_with_resume(initial_context or "", resume_meta),
        "mission_state": mission_state,
        "crawler_captures": [],
        "telemetry_transcript": [],
        "telemetry_flags": {"dialog_started_emitted": False},
        "resumed_from_session_id": resume_meta.get("resumed_from_session_id"),
        "resume_source": resume_meta.get("resume_source"),
        "resume_summary": resume_meta.get("resume_summary"),
        "classification": {
            "persona_slug": persona_slug or None,
            "content_type": None,
            "asset_type": None,
            "asset_function": None,
            "title": None,
            "file_ext": None,
            "file_bytes": None,
        },
        "created_at": created_at,
    }
    if initial_plan:
        try:
            initial_plan_state = normalize_validate_summarize_plan(initial_plan, session, live_edit=True)
            _store_plan_state(session, initial_plan_state, last_change="plano inicial normalizado")
        except Exception:
            session["knowledge_plan"] = initial_plan
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
    if mode == "criar":
        _emit_kb_event(
            "kb_intake_preconfirmation_created",
            session=session,
            source="kb-intake.start",
            status="created",
            extra={
                "initial_block_counts": initial_block_counts,
                "current_block_counts": current_block_counts,
                "entry_count": len((initial_plan or {}).get("entries") or []),
                "tree_mode": (initial_plan or {}).get("tree_mode") or "single_branch",
                "branch_policy": (initial_plan or {}).get("branch_policy") or "single_branch_by_default",
            },
        )
    return session


def start_bootstrap_session(
    model: str = "gpt-4o-mini",
    initial_context: str = "",
    agent_key: str = "sofia",
    initial_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if str((initial_state or {}).get("mode") or "").strip().lower() == "criar" and _invalid_criar_persona((initial_state or {}).get("persona_slug")):
        return {
            "ok": False,
            "error_code": "VALIDATION_ERROR",
            "message": "Selecione uma persona especifica antes de criar conhecimento.",
        }
    session = create_session(model, initial_context=initial_context, agent_key=agent_key, initial_state=initial_state)
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


def update_session_plan(
    session_id: str,
    knowledge_plan: dict[str, Any],
    *,
    status: Optional[str] = None,
    source: str = "kb-intake.session.plan",
    last_change: str = "",
) -> dict[str, Any]:
    session = _get_session(session_id)
    if not session:
        return {"ok": False, "error": "Session not found"}
    if not isinstance(knowledge_plan, dict) or not isinstance(knowledge_plan.get("entries"), list):
        return {"ok": False, "error": "knowledge_plan.entries is required"}
    plan_state = normalize_validate_summarize_plan(knowledge_plan, session, live_edit=True)
    normalized_plan = plan_state["normalized_plan"]
    validation = plan_state["validation"]
    summary = plan_state["summary"]
    counts = summary.get("current_block_counts") or count_blocks_by_type(normalized_plan.get("entries") or [])
    _store_plan_state(session, plan_state, last_change=last_change or "frontend plan sync")
    if status:
        if status == "ready_to_save" and not validation.get("valid"):
            status = "planning"
        session["status"] = status
        if status == "ready_to_save" and validation.get("valid"):
            session["stage"] = "ready_to_save"
            session["confirmed_plan_hash"] = plan_state["plan_hash"]
    elif session.get("stage") == "idle":
        session["stage"] = "chatting"
    _save_session(session)
    event_type = "kb_intake_ready_to_save" if status == "ready_to_save" else "kb_intake_plan_updated"
    _emit_kb_event(
        event_type,
        session=session,
        source=source,
        status=status or "updated",
        extra={
            "current_block_counts": counts,
            "initial_block_counts": session.get("initial_block_counts"),
            "entry_count": summary.get("entry_count"),
            "tree_mode": summary.get("tree_mode"),
            "branch_policy": summary.get("branch_policy"),
            "plan_summary": summary,
            "plan_hash": plan_state.get("plan_hash"),
            "validation": validation,
            "last_change": last_change,
        },
    )
    if "sidebar" in source:
        _emit_kb_event(
            "kb_intake_sidebar_counts_updated",
            session=session,
            source=source,
            status="updated",
            extra={
                "current_block_counts": counts,
                "entry_count": summary.get("entry_count"),
                "plan_hash": plan_state.get("plan_hash"),
            },
        )
    return {
        "ok": True,
        "knowledge_plan": normalized_plan,
        "normalized_plan": normalized_plan,
        "plan_state": plan_state,
        "plan_validation": validation,
        "plan_hash": plan_state.get("plan_hash"),
        "current_block_counts": counts,
        "plan_summary": summary,
        "memory_summary": session.get("memory_summary") or "",
        "status": session.get("status") or session.get("stage"),
        "stage": session.get("stage"),
        "plan_changed": True,
    }


def _source_url_from_context(context: str) -> str | None:
    match = re.search(r"fonte principal:\s*([^\n]+)", context or "", re.I)
    if match:
        coerced = _coerce_urlish_value(match.group(1))
        if coerced:
            return coerced
    match = re.search(r"https?://\S+", context or "")
    if match:
        return match.group(0).strip()
    match = re.search(r"\b(?:www\.)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s]*)?\b", context or "", re.I)
    return _coerce_urlish_value(match.group(0)) if match else None


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
    """Public chat wrapper that NEVER raises. Any exception escaping the
    real implementation is converted into a controlled `{ok: false, ...}`
    dict so the route layer never has to decide between 500 and 200."""
    try:
        return _chat_impl(session_id, user_message, file_info=file_info, internal=internal)
    except Exception as exc:
        import traceback as _tb
        tb_text = _tb.format_exc()
        try:
            from services import sre_logger
            sre_logger.error(
                "kb_intake_chat_wrapper",
                f"chat() escaped exception session={(session_id or '')[:8]}: {exc}",
                exc,
            )
        except Exception:
            pass
        try:
            session = _get_session(session_id)
        except Exception:
            session = None
        return {
            "ok": False,
            "error_code": "INTERNAL_ERROR",
            "exception_type": type(exc).__name__,
            "message": (
                "Nao consegui processar sua mensagem agora. Sua configuracao "
                "foi mantida — tente novamente ou clique em Salvar se ja houver plano."
            ),
            "detail": str(exc)[:300],
            "traceback_tail": tb_text.splitlines()[-12:],
            "state": (session or {}).get("mission_state") if session else None,
        }


def _chat_impl(session_id: str, user_message: str, file_info: Optional[dict] = None, internal: bool = False) -> dict:
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
- Persona global da sessao: {session.get('persona_slug') or cls['persona_slug'] or '—'}
- Fonte principal: {session.get('source_url') or ((mission_state.get('source') or {}).get('url')) or '—'}
- Tipo de conteúdo: {cls['content_type'] or '—'}
- Tipo de asset: {cls['asset_type'] or '—'}
- Função do asset: {cls['asset_function'] or '—'}
- Título: {cls['title'] or '—'}
- Arquivo binário recebido: {'Sim (' + cls['file_ext'] + ')' if cls.get('file_bytes') else 'Não'}
- Plano inicial: {_format_block_counts(session.get('initial_block_counts'))}
- Plano atual: {_format_block_counts(session.get('current_block_counts'))}
- Memoria viva da sessao: {session.get('memory_summary') or 'plano atual ainda nao expandido'}
- Regra: nao voltar ao plano inicial quando houver knowledge_plan/current_block_counts atualizados.
"""

    if session.get("context"):
        state_ctx += "\nContexto inicial confirmado pelo operador:\n" + session["context"][:6000] + "\n"
    if isinstance(session.get("knowledge_plan"), dict) and (session.get("knowledge_plan") or {}).get("entries"):
        state_ctx += "\nPlano atual vivo em JSON (fonte de verdade para proximas alteracoes):\n"
        state_ctx += json.dumps(session.get("knowledge_plan"), ensure_ascii=False)[:6000] + "\n"
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
    plan_payload = _extract_plan(raw)
    plan_changed = False
    current_block_counts = _normalize_block_counts(session.get("current_block_counts"))
    plan_violations: list[str] = []
    plan_summary: dict[str, Any] | None = None
    plan_state: dict[str, Any] | None = None
    if plan_payload:
        plan_state = normalize_validate_summarize_plan(plan_payload, session)
        plan_payload = plan_state["normalized_plan"]
        plan_violations = plan_state["validation"]["blocking_violations"]
        plan_summary = plan_state["summary"]
        _store_plan_state(session, plan_state, last_change="knowledge_plan gerado pela Sofia")
        if plan_violations:
            session["plan_validation_warnings"] = plan_violations
            session["last_invalid_plan"] = plan_payload
            current_block_counts = plan_summary["current_block_counts"]
            session["status"] = "planning"
        else:
            session.pop("plan_validation_warnings", None)
            current_block_counts = plan_summary["current_block_counts"]
            plan_changed = True
    visible = _strip_knowledge_plan(_strip_cls(raw))
    if plan_violations:
        visible = (
            f"{visible}\n\nPlano recebido, mas bloqueado antes da preview/save por violacoes:\n- "
            + "\n- ".join(plan_violations)
        ).strip()
    visible = _rewrite_visible_plan_summary(visible, plan_payload if isinstance(plan_payload, dict) else None)
    plan_entries = plan_payload.get("entries", []) if isinstance(plan_payload, dict) and not plan_violations else []

    if cls_data:
        for key in ("persona_slug", "content_type", "asset_type", "asset_function", "title"):
            if cls_data.get(key):
                cls[key] = cls_data[key]
        if cls_data.get("complete") and not plan_violations:
            session["stage"] = "ready_to_save"
    if plan_violations:
        session["stage"] = "chatting"
        session["status"] = "planning"

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
                    "plan_summary": plan_summary,
                },
            )
        except Exception:
            pass

        try:
            _emit_kb_event(
                "kb_intake_plan_updated",
                session=session,
                source="kb-intake.chat",
                status="updated",
                extra={
                    "current_block_counts": current_block_counts,
                    "initial_block_counts": session.get("initial_block_counts"),
                    "entry_count": len(plan_entries),
                    "tree_mode": plan_payload.get("tree_mode") if isinstance(plan_payload, dict) else None,
                    "branch_policy": plan_payload.get("branch_policy") if isinstance(plan_payload, dict) else None,
                    "plan_summary": plan_summary,
                },
            )
        except Exception:
            pass

    if session.get("stage") == "ready_to_save" and previous_stage != "ready_to_save" and not plan_violations:
        session["status"] = "ready_to_save"
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
        "proposed_plan": plan_payload or None,
        "knowledge_plan": plan_payload or session.get("knowledge_plan"),
        "current_block_counts": current_block_counts,
        "memory_summary": session.get("memory_summary") or "",
            "plan_summary": plan_summary,
            "plan_violations": plan_violations,
            "plan_state": plan_state,
            "normalized_plan": plan_payload,
            "plan_validation": (plan_state or {}).get("validation") if plan_state else None,
            "plan_hash": (plan_state or {}).get("plan_hash") if plan_state else None,
            "plan_changed": plan_changed,
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
            cls["title"] = f"Extracao: {url.split('//')[-1]}"
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


def _vault_client_folder(persona_slug: Optional[str]) -> str:
    if not persona_slug:
        return _GLOBAL_VAULT_CLIENT_FOLDER
    return persona_folder_name(persona_slug)


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
    ensure_persona_vault_structure(persona_slug, VAULT_PATH)
    client_folder = _vault_client_folder(persona_slug)
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
        "created_via": "kb_intake_sofia",
        "sync_origin": "direct_save",
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
    ensure_persona_vault_structure(cls["persona_slug"], VAULT_PATH)
    client_folder = _vault_client_folder(cls["persona_slug"])
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
                 f"type: {cls['content_type']}", "created_via: kb_intake_sofia", "sync_origin: direct_save"]
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


def save(session_id: str, content_text: str = "", plan_override: Optional[dict] = None) -> dict:
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
                "has_plan_override": bool(isinstance(plan_override, dict) and (plan_override.get("entries") or plan_override.get("normalized_plan") or plan_override.get("plan_hash"))),
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

    session_plan_hash = str(session.get("plan_hash") or "")
    plan_payload: dict = {}
    plan_state: dict[str, Any] | None = None
    if isinstance(plan_override, dict):
        override_hash = str(plan_override.get("plan_hash") or "")
        override_plan = plan_override.get("normalized_plan") if isinstance(plan_override.get("normalized_plan"), dict) else None
        if override_plan is None and isinstance(plan_override.get("entries"), list):
            override_plan = plan_override
        if override_hash and session_plan_hash and override_hash != session_plan_hash:
            error = "Plan mismatch: save payload is not the current normalized plan."
            _emit_kb_event(
                "kb_intake_dialog_rejected",
                session=session,
                source="kb-intake.save",
                status="rejected",
                transcript=True,
                result={"error": error, "session_plan_hash": session_plan_hash, "save_plan_hash": override_hash},
            )
            return {"error": error, "session_plan_hash": session_plan_hash, "save_plan_hash": override_hash}
        if isinstance(override_plan, dict) and override_plan.get("entries"):
            if override_hash and override_hash == session_plan_hash and isinstance(session.get("normalized_plan"), dict):
                plan_payload = dict(session.get("normalized_plan") or {})
                plan_state = _session_public_state(session).get("plan_state")
            else:
                plan_state = normalize_validate_summarize_plan(override_plan, session, live_edit=True)
                if session_plan_hash and plan_state["plan_hash"] != session_plan_hash:
                    error = "Plan mismatch: save payload is not the current normalized plan."
                    _emit_kb_event(
                        "kb_intake_dialog_rejected",
                        session=session,
                        source="kb-intake.save",
                        status="rejected",
                        transcript=True,
                        result={"error": error, "session_plan_hash": session_plan_hash, "save_plan_hash": plan_state["plan_hash"]},
                    )
                    return {"error": error, "session_plan_hash": session_plan_hash, "save_plan_hash": plan_state["plan_hash"]}
                plan_payload = plan_state["normalized_plan"]

    if not plan_payload and isinstance(session.get("normalized_plan"), dict) and (session.get("normalized_plan") or {}).get("entries"):
        plan_payload = dict(session.get("normalized_plan") or {})
        plan_state = _session_public_state(session).get("plan_state")
    elif not plan_payload and isinstance(session.get("knowledge_plan"), dict) and (session.get("knowledge_plan") or {}).get("entries"):
        plan_state = normalize_validate_summarize_plan(dict(session.get("knowledge_plan") or {}), session, live_edit=True)
        plan_payload = plan_state["normalized_plan"]
        _store_plan_state(session, plan_state, last_change="save normalized legacy plan")
    elif not plan_payload:
        plan_state = normalize_validate_summarize_plan(_fallback_plan_payload(session, content_text), session)
        plan_payload = plan_state["normalized_plan"]
        _store_plan_state(session, plan_state, last_change="save fallback plan")

    if plan_state is None:
        plan_state = _plan_state_from_normalized(plan_payload, session=session)
    validation = plan_state.get("validation") or _plan_validation()
    if not validation.get("valid"):
        error = "Plano ainda não pode ser salvo. Corrija as pendências bloqueantes primeiro."
        _emit_kb_event(
            "kb_intake_dialog_rejected",
            session=session,
            source="kb-intake.save",
            status="rejected",
            transcript=True,
            result={"error": error, "violations": validation.get("blocking_violations") or []},
        )
        return {"error": error, "violations": validation.get("blocking_violations") or [], "plan_state": plan_state}

    plan_entries = plan_payload.get("entries", [])
    expected_counts = _normalize_block_counts((plan_state.get("summary") or {}).get("current_block_counts") or session.get("current_block_counts"))
    actual_counts = count_blocks_by_type(plan_entries)
    mismatch = _count_mismatch_message(expected_counts, actual_counts)
    if mismatch or len(plan_entries) != int((plan_state.get("summary") or {}).get("entry_count") or len(plan_entries)):
        mismatch = mismatch or "Plan mismatch: normalized plan entry_count differs from save payload entry_count."
        _emit_kb_event(
            "kb_intake_dialog_rejected",
            session=session,
            source="kb-intake.save",
            status="rejected",
            transcript=True,
            result={
                "error": mismatch,
                "current_block_counts": expected_counts,
                "save_payload_counts": actual_counts,
            },
        )
        return {
            "error": mismatch,
            "current_block_counts": expected_counts,
            "save_payload_counts": actual_counts,
        }
    _emit_kb_event(
        "kb_intake_save_payload_validated",
        session=session,
        source="kb-intake.save",
        status="validated",
        extra={
            "current_block_counts": expected_counts,
            "save_payload_counts": actual_counts,
            "entry_count": len(plan_entries),
            "tree_mode": (plan_state.get("summary") or {}).get("tree_mode") or "single_branch",
            "branch_policy": (plan_state.get("summary") or {}).get("branch_policy") or "single_branch_by_default",
            "plan_summary": plan_state.get("summary"),
            "plan_hash": plan_state.get("plan_hash"),
        },
    )
    plan_warnings = [
        warning
        for warning in (plan_payload.get("warnings") or [])
        if isinstance(warning, dict)
    ]

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
            item_classification = {
                **{k: v for k, v in cls.items() if k != "file_bytes"},
                "content_type": payload["content_type"],
            }
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
                    "tree_mode": plan_payload.get("tree_mode") or "single_branch",
                    "branch_policy": plan_payload.get("branch_policy") or "single_branch_by_default",
                    "sync_origin": "direct_save",
                    "classification": item_classification,
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
            try:
                repaired = knowledge_graph.repair_primary_tree_connections(
                    persisted_items[0].get("persona_id"),
                    node_ids=[
                        (item.get("metadata") or {}).get("knowledge_node_id")
                        for item in persisted_items
                        if (item.get("metadata") or {}).get("knowledge_node_id")
                    ],
                )
                hierarchy_result["tree_guard"] = repaired
            except Exception as guard_exc:
                hierarchy_result["tree_guard_error"] = str(guard_exc)
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
            if hierarchy_item.get("resolution_mode"):
                evidence["resolution_mode"] = hierarchy_item.get("resolution_mode")
            if hierarchy_item.get("quarantine_reason"):
                evidence["quarantine_reason"] = hierarchy_item.get("quarantine_reason")
        for persisted in persisted_items:
            hierarchy_item = hierarchy_by_item.get(persisted.get("id")) or {}
            if not hierarchy_item:
                continue
            updated_metadata = {
                **(persisted.get("metadata") or {}),
                "resolution_mode": hierarchy_item.get("resolution_mode"),
                "quarantine_state": "structural" if hierarchy_item.get("resolution_mode") == "quarantined" else None,
                "quarantine_reason": hierarchy_item.get("quarantine_reason"),
                "resolved_parent_slug": hierarchy_item.get("parent_slug"),
                "resolved_parent_node_id": hierarchy_item.get("parent_node_id"),
            }
            updated_metadata = {k: v for k, v in updated_metadata.items() if v is not None}
            supabase_client.update_knowledge_item(persisted["id"], {"metadata": updated_metadata})
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

    session["stage"] = "done"
    session["status"] = "saved"
    _save_session(session)
    git_warnings = [
        {
            "stage": "git_push",
            "message": "Knowledge saved, but git push failed.",
            "detail": git_result.get("error"),
        }
    ] if not bool(git_result.get("push_ok", True)) else []
    completion_warnings = [*plan_warnings, *git_warnings]
    completion_payload = {
        "file_path": rel_path,
        "saved_paths": [str(p) for p in saved_paths],
        "git": git_result,
        "success": True,
        "status": "saved_with_warnings" if completion_warnings else "saved",
        "warnings": completion_warnings,
        "sync_mode": "manual_only",
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
        "plan_state": plan_state,
        "plan_hash": plan_state.get("plan_hash"),
        "vault_write": {"paths": [str(p) for p in saved_paths]},
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
        "success": True,
        "status": "saved_with_warnings" if completion_warnings else "saved",
        "warnings": completion_warnings,
        "file_path": rel_path,
        "knowledge_item_ids": [item.get("id") for item in persisted_items],
        "knowledge_node_ids": [
            evidence.get("knowledge_node_id")
            for evidence in persisted_evidence
            if evidence.get("knowledge_node_id")
        ],
        "persistence_evidence": persisted_evidence,
        "hierarchy": hierarchy_result,
        "plan_state": plan_state,
        "plan_hash": plan_state.get("plan_hash"),
        "vault_write": {"paths": [str(p) for p in saved_paths]},
        "git": git_result,
        "sync": {
            "mode": "manual_only",
            "new": 0,
            "updated": 0,
            "error": None,
        },
    }
