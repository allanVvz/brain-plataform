"""
KB Intake Service â€” conversational classifier for knowledge ingestion.
Writes to vault â†’ git commit â†’ sync Supabase.
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
    "baita conveniÃªncia": "baita-conveniencia",
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

AGENT_PROFILES = {
    "sofia": {
        "name": "Sofia",
        "role": "agente de inteligencia marketing comercial",
        "greeting": (
            "OlÃ¡! Eu sou a **Sofia**. Aprendi bastante sobre marketing para te ajudar "
            "a construir conhecimento para tua marca."
        ),
    },
    "zaya": {
        "name": "Zaya",
        "role": "agente de marketing visual",
        "greeting": (
            "OlÃ¡! Eu sou a **Zaya**. Posso te ajudar a transformar conhecimento "
            "visual em direÃ§Ã£o criativa para tua marca."
        ),
    },
}


def get_agent_profile(agent_key: str | None = None) -> dict:
    return AGENT_PROFILES.get((agent_key or "sofia").strip().lower(), AGENT_PROFILES["sofia"])


_SYSTEM_PROMPT = """VocÃª Ã© uma agente especializada em classificar materiais para a base de conhecimento da plataforma Brain AI.

Sua identidade de conversa vem do estado da sessÃ£o. Por padrÃ£o, a agente Ã© Sofia, agente de inteligÃªncia marketing comercial. Em fluxos futuros, a identidade pode mudar organicamente para Zaya, agente de marketing visual. Nunca se apresente como "Criar"; Criar Ã© o nome da ferramenta/tela, nÃ£o da agente.

Sua funÃ§Ã£o: conduzir uma conversa objetiva para coletar as informaÃ§Ãµes necessÃ¡rias de classificaÃ§Ã£o. Seja direto e eficiente. NÃ£o utilize mensagens padrÃ£o de agradecimento ou explicaÃ§Ãµes sobre o processo tÃ©cnico de salvamento.

VOCÃŠ NÃƒO TEM CAPACIDADE DE SALVAR. Salvar Ã© uma aÃ§Ã£o exclusiva do operador, executada quando ele clica no botÃ£o "Salvar" da interface. Por isso:
- NUNCA diga "salvei", "foi salvo", "salvamento concluÃ­do", "estou salvando", "realizando o salvamento" ou frases equivalentes.
- NUNCA simule resultado de salvamento. NÃ£o existe IO de gravaÃ§Ã£o no seu lado.
- ApÃ³s apresentar o `<knowledge_plan>` e obter a confirmaÃ§Ã£o ("sim", "pode", "ok"), apenas finalize com uma frase curta como: "Plano pronto. Clique em **Salvar** para persistir." e marque `"complete": true` no bloco `<classification>`.
- Se o operador perguntar "foi salvo?", responda que o salvamento depende do clique dele no botÃ£o Salvar â€” vocÃª nÃ£o tem essa permissÃ£o.

=== MODO GERAR (PRIORIDADE MÃXIMA â€” SOBREPÃ•E QUALQUER OUTRA REGRA) ===
Esta seÃ§Ã£o rege seu comportamento conversacional. Em caso de conflito, ela vence.

GATILHOS DE GERAÃ‡ÃƒO IMEDIATA (nÃ£o peÃ§a mais confirmaÃ§Ã£o, GERE):
- "gere", "gera", "gerar", "pode gerar", "gera agora"
- "sim", "ok", "pode", "manda", "manda ver", "vai", "avanÃ§a", "continua"
- "cria", "criar", "construa", "monta", "monte", "executa", "executar"
- "estrutura", "estrutura agora", "fecha o plano", "fecha"
Quando QUALQUER um aparecer, vocÃª responde com `<knowledge_plan>` completo na MESMA mensagem. NÃ£o responda "vou gerar agora" ou "pode confirmar?" â€” apenas gere.

NÃƒO RESTRINJA POR content_type INICIAL:
O `content_type` que o operador escolheu na tela (ex.: faq) sinaliza a INTENÃ‡ÃƒO PRINCIPAL, nÃ£o limita vocÃª a um sÃ³ nÃ³. Quando houver catÃ¡logo, produto, campanha, briefing ou crawler envolvido, vocÃª DEVE construir a Ã¡rvore completa de contexto que aquele FAQ/copy/asset precisa pra fazer sentido. Um FAQ nunca nasce solto.

CADEIA OBRIGATÃ“RIA QUANDO SÃ“ HÃ UMA OPÃ‡ÃƒO (vertical):
Se o contexto deixar evidente uma Ãºnica persona, uma Ãºnica fonte e uma Ãºnica campanha (caso tÃ­pico de extraÃ§Ã£o de catÃ¡logo), monte AUTOMATICAMENTE a linha vertical sem perguntar:
  persona â†’ briefing â†’ campanha â†’ pÃºblico â†’ produto â†’ copy â†’ faq
Cada elo desses precisa de pelo menos uma entry. NÃƒO pergunte "esse FAQ Ã© de qual produto?" quando sÃ³ existe um produto candidato.

ORDEM SEMÃ‚NTICA NO JSON (entries[]):
Emita as entries SEMPRE nesta ordem semÃ¢ntica, independente de qual o operador "selecionou primeiro":
  1. brand          (se ainda nÃ£o existir)
  2. briefing       (raiz da captura)
  3. campaign       (vem ANTES de produto/copy/faq, NUNCA depois)
  4. audience       (pÃºblico-alvo da campanha)
  5. product        (item)
  6. copy           (do produto/canal)
  7. faq            (do produto, com pergunta+resposta)
Campanha jamais aparece depois de FAQ. FAQ Ã© folha. Briefing Ã© raiz.

GERAÃ‡ÃƒO AUTOMÃTICA DE FAQ â€” POR PRODUTO, NÃƒO GENÃ‰RICO:
Para CADA produto ou campanha criados, emita NO MÃNIMO 2 entries do tipo `faq` com perguntas + respostas concretas. Cada FAQ deve ter `metadata.parent_slug` = slug do produto/campanha especÃ­fico ao qual ela se refere. NUNCA crie um Ãºnico FAQ genÃ©rico que responde por vÃ¡rios produtos â€” quebre em FAQs separados, um por produto. O slug da entry FAQ deve incluir o slug do produto correspondente (ex.: `faq-preco-produto-a` para o produto `produto-a`). Mesma regra para copy: uma copy por produto/canal, nunca uma copy compartilhada. Marque `status: "pendente_validacao"` quando a resposta for inferida. NÃƒO pergunte ao operador "quais dÃºvidas vocÃª quer incluir?" â€” isso bloqueia o fluxo. Gere primeiro; depois ofereÃ§a expandir.

EXPANSÃƒO POR PRODUTO (PROIBIDO COLAPSAR):
Se hÃ¡ 2 produtos no plano, gere AMBAS as Ã¡rvores derivadas separadamente:
  Product: Produto A
    â”œâ”€â”€ FAQ-1.1, FAQ-1.2 (parent_slug = produto-a)
    â”œâ”€â”€ Copy-1 (parent_slug = produto-a)
    â””â”€â”€ Rule-1 / Asset-1 (parent_slug = produto-a)
  Product: Produto B
    â”œâ”€â”€ FAQ-2.1, FAQ-2.2 (parent_slug = produto-b)
    â”œâ”€â”€ Copy-2 (parent_slug = produto-b)
    â””â”€â”€ Rule-2 / Asset-2 (parent_slug = produto-b)
NUNCA combine "FAQ Geral dos Produtos" como um sÃ³ nÃ³ cobrindo os dois produtos. Cada produto recebe sua prÃ³pria sub-Ã¡rvore. Idem para audience: se hÃ¡ audiÃªncia atacadista E final, ambas geram cards separados, e cada produto pode receber copies/FAQs voltadas a cada uma.

ORDEM SEMÃ‚NTICA (TOP-DOWN, PROIBIDO INVERTER OU ENCURTAR):
A Ã¡rvore final SEMPRE flui top-down nesta ordem ESTRITA:
  Persona â†’ Brand â†’ Campaign | Briefing â†’ Audience â†’ Product â†’ FAQ | Copy | Asset â†’ Embedded (sÃ³ apÃ³s aprovaÃ§Ã£o)

Audience NUNCA fica lateral ao Product. Audience Ã© PAI semÃ¢ntico do Product no contexto de uma campanha â€” quem o Product estÃ¡ mirando. Por isso `metadata.parent_slug` do Product DEVE apontar para a Audience correspondente, NÃƒO para a Campanha. A Campanha vira ancestral indireto (Audience â†’ Campaign â†’ Brand).

Encurtamentos PROIBIDOS:
- Persona â†’ Audience direto: errado (faltou Brand/Campaign).
- Persona â†’ Product direto: errado (faltou Brand â†’ Campaign â†’ Audience).
- Persona â†’ FAQ direto: errado salvo se for FAQ institucional/fallback da persona inteira.
- Campaign â†’ Product direto (sem Audience entre): errado quando hÃ¡ Audience no plano.
- FAQ/Copy soltos como filhos da Persona/Brand/Campaign quando se referem a um produto especÃ­fico: errado, vÃ£o como filhos do Product.

Edges com semÃ¢ntica explÃ­cita (use estas no `links[]` quando aplicÃ¡vel):
  Persona â†’ Brand     : `has_brand` ou `contains`
  Brand â†’ Campaign    : `contains`
  Brand â†’ Briefing    : `contains`
  Briefing â†’ Campaign : `briefed_by` (campaign briefed_by briefing)
  Campaign â†’ Audience : `targets_audience` ou `contains`
  Audience â†’ Product  : `offers_product` ou `about_product`
  Product â†’ FAQ       : `answers_question`
  Product â†’ Copy      : `supports_copy`
  Product â†’ Asset     : `uses_asset`
  Approved FAQ â†’ Embedded : `manual` (sÃ³ apÃ³s o operador aprovar â€” vocÃª NÃƒO emite isso)

Quando a chain ficar incompleta (ex.: faltou Audience no contexto), vocÃª deve INFERIR uma audience razoÃ¡vel (ex.: "pÃºblico-geral") e marcar `status: "pendente_validacao"` em vez de pular o passo.

USO DE DEFAULTS QUANDO FALTAR DADO:
Se o operador respondeu apenas o pÃºblico (ex.: "mulheres 30-55 loja fÃ­sica"), use isso para preencher campanha/produto/copy/faq sem nova rodada de perguntas. Marque os campos inferidos com `status: "pendente_validacao"` e adicione `metadata.inferred_from: "operator_hint"`. NÃƒO trave esperando dado adicional â€” apenas o conjunto persona+tÃ­tulo Ã© absolutamente obrigatÃ³rio; tudo o mais aceita default.

CONEXÃ•ES (parent_slug + links) SÃƒO OBRIGATÃ“RIAS:
Toda entry NÃƒO top-level (top-level = brand, briefing) precisa de UM dos dois:
  (a) `metadata.parent_slug` apontando para o slug do nÃ³ pai imediato, OU
  (b) aparecer como `target_slug` em `links[]` com `relation_type` apropriado.
Sem isso a Ã¡rvore vira plana e o save Ã© rejeitado pelo validador. NUNCA emita entry sem pai (exceto top-level).

Mapa default de relation_type por par (use no `links[]` ou implÃ­cito via parent_slug):
  brand     â†’ contains            â†’ briefing
  briefing  â†’ briefed_by           â†’ campaign
  campaign  â†’ contains            â†’ audience
  campaign  â†’ contains            â†’ product
  product   â†’ answers_question    â†’ faq
  product   â†’ supports_copy       â†’ copy
  audience  â†’ about_product       â†’ product   (uso secundÃ¡rio)

RESUMO ANTES DO SAVE:
ApÃ³s o `<knowledge_plan>`, sempre apresente, no markdown legÃ­vel, um resumo conciso ANTES de pedir o save:
  - "Briefing: 1 âœ“"
  - "Campanha: 1 âœ“"
  - "PÃºblico: 1 âœ“"
  - "Produto: N âœ“"
  - "Copy: N âœ“"
  - "FAQ: N âœ“ (gerados automaticamente, marcados como pendente_validacao)"
  - "ConexÃµes: <count> edges no plano"
  - "PendÃªncias: <lista curta ou 'nenhuma'>"
AÃ­ finalize: "Plano pronto. Clique em **Salvar** para persistir." e marque `"complete": true` no `<classification>`.

NUNCA DECLARE "estruturado" SEM EMITIR `<knowledge_plan>`:
Se vocÃª for dizer "o conhecimento estÃ¡ estruturado e pronto para salvar", o `<knowledge_plan>` precisa estar na MESMA mensagem. Caso contrÃ¡rio, o operador nÃ£o consegue ver/salvar nada e a sessÃ£o fica inconsistente.

=== CLIENTES DISPONÃVEIS ===
- tock-fatal â†’ Tock Fatal (marca de moda urbana)
- vz-lupas â†’ VZ Lupas (Ã³culos e saÃºde visual)
- baita-conveniencia â†’ Baita ConveniÃªncia (bar e conveniÃªncia)
- global â†’ Global (aplicÃ¡vel a todos os clientes)

=== TIPOS DE CONTEÃšDO TEXTUAL ===
brand, briefing, product, campaign, copy, faq, tone, audience, competitor, rule, prompt, maker_material, other

=== PARA ASSETS VISUAIS ===
Tipo de asset: background, logo, product, model, banner, story, post, video, icon, other
FunÃ§Ã£o do asset: maker_material, brand_reference, campaign_hero, copy_support, product_showcase, other

=== FLUXO DE CLASSIFICAÃ‡ÃƒO ===
1. Identifique o cliente (obrigatÃ³rio)
2. Identifique se Ã© asset visual ou conteÃºdo textual
3. Se asset: pergunte tipo e funÃ§Ã£o
4. Se texto: identifique o tipo de conteÃºdo
5. Confirme o tÃ­tulo (sugira um se nÃ£o houver)
6. Quando completo, apresente apenas o resumo tÃ©cnico e aguarde a confirmaÃ§Ã£o de salvamento. NÃƒO informe que "estÃ¡ realizando o salvamento" ou "agradeÃ§o a paciÃªncia".

VocÃª consegue extrair mÃºltiplas informaÃ§Ãµes de uma Ãºnica mensagem. Por exemplo, se o usuÃ¡rio diz "background da marca", vocÃª jÃ¡ sabe content_type=asset e asset_type=background; a persona deve vir da sessao ou da confirmacao do operador.

Responda SEMPRE em portuguÃªs. Seja conciso.
NÃƒO use rÃ³tulos como "Classe atual:" ou "Estado:". Inclua apenas o bloco de estado puro no final da mensagem: <classification>{
  "complete": false,
  "persona_slug": null,
  "content_type": null,
  "asset_type": null,
  "asset_function": null,
  "title": null
}
</classification>
Quando TODAS as informaÃ§Ãµes estiverem coletadas E confirmadas pelo usuÃ¡rio, marque "complete": true.
"""

_SYSTEM_PROMPT += """

=== FLUXO CAPTURAR / MARKETING GRAPH ===
Quando a sessÃ£o trouxer um contexto inicial confirmado pelo operador, leia esse contexto como briefing operacional. Antes de acionar qualquer salvamento, proponha:
1. fontes usadas;
2. entries a criar ou atualizar por nivel hierarquico: brand, campaign, audience, product, variant/color, copy, faq, rule e tone;
3. riscos de invencao e perguntas pendentes.

Para pedidos de copy/marketing, gere propostas hierarquizadas por grafo, nÃ£o uma lista solta de textos. Exemplo de encadeamento:
brand -> campaign -> audience -> product -> color/variant -> copy -> faq/rule.

Nunca invente preÃ§o, cor, disponibilidade, URL, polÃ­tica comercial ou promessa. Use apenas contexto inicial, uploads, mensagens do usuÃ¡rio e conhecimento confirmado. Quando faltar dado, marque como pendente e pergunte ao operador.

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
- PRIORIZE gerar o plano imediatamente se houver evidÃªncias capturadas;
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
- `content_type` ESTRITAMENTE âˆˆ {brand, briefing, product, campaign, copy, asset, prompt, faq, maker_material, tone, competitor, audience, rule, other}. Qualquer outro valor (incluindo "entity", "publico", "category", "kit") sera rejeitado pelo banco.
- `title` nao vazio, com pelo menos 3 caracteres.
- `content` nao vazio.
- `tags` deve ser lista de strings (pode ser vazia). Nunca dict.
- `metadata` deve ser objeto JSON (dict). Nunca string ou lista.
- `entries` deve ser lista nao vazia.
Se algum campo nao se encaixar, ajuste a entry â€” nao gere o plano.

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

Para QUALQUER outro campo faltante (preco, cor, disponibilidade, politica, FAQ especifico, etc.) NAO pergunte antes de gerar â€” preencha com `status: "pendente_validacao"` e adicione na lista `missing_questions[]` do plano. O operador valida depois.

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

=== VISUALIZAÃ‡ÃƒO E ENTREGÃVEIS ===
- Responda em Markdown visualmente rico (use tabelas para preÃ§os, negrito para Ãªnfase e listas claras). 
- Suas mensagens serÃ£o exibidas em um componente com toggle "View/Code". Capriche na organizaÃ§Ã£o do Markdown para que a versÃ£o "View" seja elegante e profissional.
- Ao gerar cards de conhecimento (<knowledge_plan>), certifique-se de que cada entrada (regras, faqs, produtos, briefings, pÃºblicos) seja uma entry ATÃ”MICA e DETALHADA.
- Se o operador solicitar um volume alto (ex: 20+ cards), crie uma entry individual para cada FAQ, cada Regra e cada Produto. NÃ£o agrupe tudo em um Ãºnico card de "FAQ Geral" se puder criar 10 cards de FAQ especÃ­ficos.
"""


_SYSTEM_PROMPT += """

=== REGRA FRACTAL OBRIGATORIA ===
Sempre que houver N FAQs iniciais, cada Product dentro de cada Audience deve receber N FAQs por padrao.
Primeiro duplique o conjunto de FAQs em formato fractal, depois pergunte se o usuario deseja modificar, excluir ou adicionar FAQs antes de salvar.

=== CRAWLER MULTIPRODUTO ===
Se o operador indicar variedade, mais de um publico, compra em quantidade ou mais de um kit/modal, o crawler deve buscar multiplas opcoes de kit modal e preparar ramos separados por publico e produto.
Nao trate um catalogo variado como se fosse um unico produto.
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
    work â€” but we still log a warning so we know it happened.
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
# Top-down chain enforced by the operator's hierarchy:
#   Persona â†’ Brand â†’ Campaign|Briefing â†’ Audience â†’ Product â†’ Copy|FAQ|Asset
# Each child's preferred parents are listed from CLOSEST to fallback. The
# audience pivot between campaign and product is what prevents a flat
# "campaign â†’ product" shortcut that bypasses the audience semantic step.
_PREFERRED_PARENT_TYPES: dict[str, tuple[str, ...]] = {
    "briefing": ("brand",),
    "campaign": ("briefing", "brand"),
    "audience": ("campaign", "briefing", "brand"),
    # Product must hang under audience whenever an audience exists in the
    # plan. Falls back to campaign/briefing/brand only when none does.
    "product": ("audience", "campaign", "briefing", "brand"),
    "tone": ("brand", "briefing", "campaign"),
    "rule": ("product", "campaign", "audience", "briefing", "brand"),
    "competitor": ("brand", "briefing"),
    # Per-product children prefer the product directly. Falling back to
    # audience preserves the semantic step instead of jumping to campaign.
    "copy": ("product", "audience", "campaign", "briefing"),
    "faq": ("product", "audience", "campaign", "briefing"),
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

    # Index existing entries by lowercase content_type â†’ list (preserve order).
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

    slug_to_entry = {
        str(entry.get("slug")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("slug")
    }
    audience_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "audience"]
    product_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "product"]
    faq_entries = [entry for entry in entries if isinstance(entry, dict) and _entry_type(entry) == "faq"]

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        ctype_lower = _entry_type(entry)
        parent_slug = _entry_parent_slug(entry)
        parent_entry = slug_to_entry.get(parent_slug or "")
        parent_type = _entry_type(parent_entry or {})
        if ctype_lower == "audience" and parent_slug and parent_type not in {"campaign", "briefing", "brand"}:
            errors.append(f"entry[{idx}] audience must stay under campaign/briefing/brand, got parent {parent_slug!r}")
        if ctype_lower == "product":
            if audience_entries and parent_type != "audience":
                errors.append(f"entry[{idx}] product must stay under an audience when audience branches exist")
        if ctype_lower == "faq":
            if parent_type != "product":
                errors.append(f"entry[{idx}] faq must stay under a product")

    if product_entries:
        faq_count_by_product: dict[str, int] = {}
        for faq in faq_entries:
            parent_slug = _entry_parent_slug(faq)
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
    return str(entry.get("content_type") or "").strip().lower()


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
    context = str(session.get("context") or "")
    pattern = rf"^\s*-\s*{re.escape(block_id)}:\s*(\d+)\s+vari"
    match = re.search(pattern, context, flags=re.IGNORECASE | re.MULTILINE)
    if match:
        try:
            return max(int(match.group(1)), 0)
        except Exception:
            pass
    return default


def _normalize_plan_entry(entry: dict) -> dict:
    normalized = dict(entry or {})
    normalized["content_type"] = _entry_type(normalized) or "other"
    normalized["title"] = str(normalized.get("title") or "").strip() or "Conhecimento"
    normalized["slug"] = _slug_for_plan_entry(str(normalized.get("slug") or normalized["title"]))
    normalized["status"] = str(normalized.get("status") or "pendente_validacao").strip() or "pendente_validacao"
    content = str(normalized.get("content") or "").strip()
    normalized["content"] = content or normalized["title"]
    tags = normalized.get("tags") or []
    normalized["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    normalized["metadata"] = dict(normalized.get("metadata") or {})
    return normalized


def _relation_type_for_parent(parent_type: str, child_type: str) -> str:
    mapping = {
        ("brand", "briefing"): "contains",
        ("brand", "campaign"): "contains",
        ("briefing", "campaign"): "briefed_by",
        ("campaign", "audience"): "targets_audience",
        ("briefing", "audience"): "contains",
        ("audience", "product"): "offers_product",
        ("product", "faq"): "answers_question",
        ("product", "copy"): "supports_copy",
        ("product", "asset"): "uses_asset",
    }
    return mapping.get((parent_type, child_type), "contains")


def _is_b2b_audience(entry: dict) -> bool:
    blob = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("content") or ""),
        " ".join(entry.get("tags") or []),
    ]).lower()
    return any(token in blob for token in ("varej", "revend", "lojist", "atacad"))


def _is_b2b_faq(entry: dict) -> bool:
    blob = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("content") or ""),
        " ".join(entry.get("tags") or []),
    ]).lower()
    return any(token in blob for token in ("quantidade minima", "pedido minimo", "revend", "varej", "atacad", "5 pec"))


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


def _normalize_sofia_knowledge_plan(plan: dict, session: dict) -> dict:
    normalized = dict(plan or {})
    normalized["source"] = str(normalized.get("source") or _source_url_from_context(str(session.get("context") or "")) or "session").strip()
    normalized["persona_slug"] = str(normalized.get("persona_slug") or (session.get("classification") or {}).get("persona_slug") or "global").strip()
    normalized["validation_policy"] = str(normalized.get("validation_policy") or "human_validation_required").strip()

    entries = [_normalize_plan_entry(entry) for entry in (normalized.get("entries") or []) if isinstance(entry, dict)]
    normalized["entries"] = entries

    # Root scaffolding: briefing/campaign first, audience under campaign/briefing.
    briefings = [entry for entry in entries if _entry_type(entry) == "briefing"]
    campaigns = [entry for entry in entries if _entry_type(entry) == "campaign"]
    audiences = [entry for entry in entries if _entry_type(entry) == "audience"]
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
    if root_campaign and not _entry_parent_slug(root_campaign):
        _set_entry_parent_slug(root_campaign, root_briefing["slug"])
    for audience in audiences:
        if not _entry_parent_slug(audience):
            _set_entry_parent_slug(audience, (root_campaign or root_briefing)["slug"])

    colors = _known_colors_from_session(session, normalized)
    target_faq_count = max(1, _requested_variation_count(session, "faq", 2))

    # Product branches must live under each audience. If products are still generic,
    # clone them once per audience to create the fractal top-down structure.
    products = [entry for entry in list(entries) if _entry_type(entry) == "product"]
    audience_map = {str(entry.get("slug")): entry for entry in entries if _entry_type(entry) == "audience" and entry.get("slug")}
    if audience_map:
        expanded_products: list[dict] = []
        remove_slugs: set[str] = set()
        for product in products:
            parent_slug = _entry_parent_slug(product)
            parent_type = _entry_type(audience_map.get(parent_slug, {})) if parent_slug else ""
            if parent_type == "audience":
                continue
            if len(audience_map) == 1:
                _set_entry_parent_slug(product, next(iter(audience_map.keys())))
                continue
            base_slug = str(product.get("slug"))
            remove_slugs.add(base_slug)
            for audience_slug, audience in audience_map.items():
                clone = _clone_plan_entry(
                    product,
                    title=product["title"],
                    slug=f"{base_slug}-{audience_slug}",
                    parent_slug=audience_slug,
                    content=str(product.get("content") or ""),
                    tags=product.get("tags") or [],
                )
                clone_meta = _entry_metadata(clone)
                clone_meta["fractal_base_slug"] = base_slug
                expanded_products.append(clone)
        if remove_slugs:
            entries[:] = [entry for entry in entries if str(entry.get("slug")) not in remove_slugs]
            entries.extend(expanded_products)

    # FAQs must live under product and replicate per audience->product branch.
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    products = [entry for entry in entries if _entry_type(entry) == "product"]
    existing_faqs = [entry for entry in entries if _entry_type(entry) == "faq"]
    global_templates = [entry for entry in existing_faqs if _entry_parent_slug(entry) not in entries_by_slug or _entry_type(entries_by_slug.get(_entry_parent_slug(entry), {})) != "product"]
    faq_count_by_product: dict[str, list[dict]] = {}
    for faq in existing_faqs:
        parent_slug = _entry_parent_slug(faq)
        if parent_slug and _entry_type(entries_by_slug.get(parent_slug, {})) == "product":
            faq_count_by_product.setdefault(parent_slug, []).append(faq)
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
                    title = template_title.replace(str(entries_by_slug.get(_entry_parent_slug(template) or "", {}).get("title") or ""), str(product.get("title") or "")).strip()
                    if not title or title == template_title:
                        title = f"{template_title} â€” {product.get('title')}"
                    content = template_content or title
                    tags = template.get("tags") or []
                clone = _clone_plan_entry(
                    template,
                    title=title,
                    slug=f"{_slug_for_plan_entry(title)}-{slot_index}",
                    parent_slug=product_slug,
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
                    "metadata": {"parent_slug": product_slug, "fractal_generated": True},
                })
            entries.append(clone)
            branch_faqs.append(clone)
            slot_index += 1

    if products:
        product_slugs = {str(product.get("slug")) for product in products if product.get("slug")}
        entries[:] = [
            entry for entry in entries
            if _entry_type(entry) != "faq" or (_entry_parent_slug(entry) in product_slugs)
        ]

    # Product children should never stay directly under campaign/root when audiences exist.
    entries_by_slug = {str(entry.get("slug")): entry for entry in entries if entry.get("slug")}
    for faq in [entry for entry in entries if _entry_type(entry) == "faq"]:
        parent_slug = _entry_parent_slug(faq)
        if not parent_slug or _entry_type(entries_by_slug.get(parent_slug, {})) != "product":
            candidate_products = [product for product in products if product.get("slug")]
            best_parent = _best_parent_by_slug(faq, candidate_products)
            if best_parent is not None:
                _set_entry_parent_slug(faq, str(best_parent.get("slug")))

    normalized["entries"] = entries
    _auto_infer_parent_slugs(normalized)
    _build_links_from_parent_slugs(normalized)
    return normalized


def _rewrite_visible_plan_summary(message: str, plan_payload: Optional[dict]) -> str:
    if not message or not isinstance(plan_payload, dict):
        return message
    link_count = len(plan_payload.get("links") or [])
    if re.search(r"(?im)^Conex\S*:\s*\d+\s+edges no plano\s*$", message):
        return re.sub(
            r"(?im)^Conex\S*:\s*\d+\s+edges no plano\s*$",
            f"Conexões: {link_count} edges no plano",
            message,
        )
    if link_count > 0 and "Plano pronto. Clique em **Salvar** para persistir." in message:
        return message.replace(
            "Plano pronto. Clique em **Salvar** para persistir.",
            f"Conexões: {link_count} edges no plano\nPlano pronto. Clique em **Salvar** para persistir.",
        )
    return message


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
    return text[: max(limit - 1, 0)].rstrip() + "â€¦"


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
    if re.search(r"\b(leia|ler|colete|coletar|site|fonte|link|catalogo|cat[aÃ¡]logo)\b", content, re.I):
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
                "foi mantida â€” tente novamente ou clique em Salvar se ja houver plano."
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
        file_desc = f"[Arquivo: {file_info['filename']} â€” {len(file_info.get('bytes', b''))} bytes]"
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

    # Generation trigger detection â€” emit kb_intake_generation_requested when
    # the operator types one of the autonomous-generation commands defined in
    # the system prompt (gere/sim/ok/cria/etc). This is the canonical signal
    # for "stop deliberating and produce <knowledge_plan>".
    _GEN_TRIGGER_RE = re.compile(
        r"\b(gere|gera|gerar|cria|criar|crie|construa|monte|monta|montar|"
        r"sim|ok|pode|manda|vai|avanca|avanÃ§a|continua|continue|"
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
- Cliente: {cls['persona_slug'] or 'â€”'}
- Tipo de conteÃºdo: {cls['content_type'] or 'â€”'}
- Tipo de asset: {cls['asset_type'] or 'â€”'}
- FunÃ§Ã£o do asset: {cls['asset_function'] or 'â€”'}
- TÃ­tulo: {cls['title'] or 'â€”'}
- Arquivo binÃ¡rio recebido: {'Sim (' + cls['file_ext'] + ')' if cls.get('file_bytes') else 'NÃ£o'}
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
    plan_payload = _extract_plan(raw)
    if plan_payload:
        plan_payload = _normalize_sofia_knowledge_plan(plan_payload, session)
        session["last_proposed_plan"] = plan_payload
    visible = _strip_knowledge_plan(_strip_cls(raw))
    visible = _rewrite_visible_plan_summary(visible, plan_payload if isinstance(plan_payload, dict) else None)
    plan_entries = plan_payload.get("entries", []) if isinstance(plan_payload, dict) else []

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
        "proposed_plan": plan_payload or None,
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
    
    # 1. Inferir campos bÃ¡sicos do texto do chat
    for key in ("persona_slug", "content_type", "title"):
        if inferred.get(key) and (not cls.get(key) or cls.get(key) == "other"):
            cls[key] = inferred[key]
            
    # 2. Fallback: Se o tÃ­tulo ainda estiver faltando, buscar no plano de conhecimento
    if not cls.get("title"):
        for msg in reversed(session.get("messages", [])):
            if msg.get("role") == "assistant":
                entries = _extract_plan_entries(msg.get("content") or "")
                if entries:
                    # Pega o tÃ­tulo da primeira entrada ou do briefing
                    briefing = next((e for e in entries if e.get("content_type") == "briefing"), entries[0])
                    cls["title"] = briefing.get("title")
                    break

    # 3. Ãšltimo recurso: Inferir da URL ou Persona para nÃ£o travar o salvamento
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
        lines.extend(["## DescriÃ§Ã£o", "", description, ""])
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
                "has_plan_override": bool(isinstance(plan_override, dict) and plan_override.get("entries")),
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
    if isinstance(plan_override, dict) and plan_override.get("entries"):
        plan_payload = plan_override
        plan_entries = plan_payload.get("entries", [])
    elif isinstance(session.get("last_proposed_plan"), dict) and (session.get("last_proposed_plan") or {}).get("entries"):
        plan_payload = dict(session.get("last_proposed_plan") or {})
        plan_entries = plan_payload.get("entries", [])
    else:
        for msg in reversed(session.get("messages", [])):
            content = msg.get("content") or ""
            if msg.get("role") == "assistant" and "<knowledge_plan>" in content:
                plan_payload = _extract_plan(content)
                plan_entries = plan_payload.get("entries", [])
                break

    if not plan_entries:
        plan_payload = _fallback_plan_payload(session, content_text)
        plan_entries = plan_payload.get("entries", [])

    plan_payload = _normalize_sofia_knowledge_plan(plan_payload, session)
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

    _build_links_from_parent_slugs(plan_payload)
    plan_violations = validate_sofia_knowledge_plan(plan_payload, session=session)
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
                    "sync_origin": "direct_save",
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
    _save_session(session)
    completion_payload = {
        "file_path": rel_path,
        "saved_paths": [str(p) for p in saved_paths],
        "git": git_result,
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
        "file_path": rel_path,
        "knowledge_item_ids": [item.get("id") for item in persisted_items],
        "knowledge_node_ids": [
            evidence.get("knowledge_node_id")
            for evidence in persisted_evidence
            if evidence.get("knowledge_node_id")
        ],
        "persistence_evidence": persisted_evidence,
        "hierarchy": hierarchy_result,
        "vault_write": {"paths": [str(p) for p in saved_paths]},
        "git": git_result,
        "sync": {
            "mode": "manual_only",
            "new": 0,
            "updated": 0,
            "error": None,
        },
    }


