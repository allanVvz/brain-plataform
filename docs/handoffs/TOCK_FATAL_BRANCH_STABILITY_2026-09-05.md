# Tock Fatal — estabilidade de galho, voz e publicação

Handoff de modelo. Sessão de 2026-09-04/05.

## 1. O defeito

A Vitória misturava as duas marcas com o mesmo cliente. Duas evidências reais,
ambas com o galho comercial nunca fechando.

**2026-09-04 21:16 — lead 181, chegando pela landing page de varejo:**

```
[in ] Oi! Vim pelo site da Tock Fatal e quero ver as peças. [cabecalho:tock-fatal]
[out] ... Você quer ver pra uso próprio ou pra revenda?
[in ] uso proprio
[out] Perfeito, uso próprio! ... me conta: você está começando agora ou já tem
      loja ou revenda?          ← pergunta de ATACADO para cliente de VAREJO
```

**2026-09-03 07:12 — mesmo lead, antes de qualquer qualificação:**

> "Aqui na Tock Fatal trabalhamos com moda feminina **em atacado**"

Estado do lead depois de responder "uso proprio":

```
facts: {}                       facts_by_key: {}
active_branch_node_id: null     active_branch_node_ids: []
asked_question_node_ids: ["faq:tock-reseller-profile", "faq:tock-reseller-profile"]
```

Os sete turnos passaram no proof checker: `mode=discovery`,
`repetition_action=allowed`, **zero** `model_proposal_errors`. Os defeitos
passaram pelos guards sem serem notados — o checker valida claim e evidência,
não consistência de marca.

## 2. Causa raiz

Um acidente alfabético, não dois defeitos.

`purchase_profile` é o seletor de galho declarado
(`persona.conversation_policy.branch_selection.field_key`). O compiler **exige**
que ele seja declarado em pelo menos dois galhos, cada um dono da sua declaração
(`graph_compiler_v3.branch_selection_field_key`). Isso está correto. O erro é que
cada declaração apontava para a **própria cópia da pergunta**, com texto
idêntico:

| nó | dono |
|---|---|
| `faq:tock-retail-profile` | `audience:tock-retail` |
| `faq:tock-reseller-profile` | `audience:tock-reseller` |

`_common_persona_contract` monta o contrato comum a partir de `anchors[0]`, e os
anchors são ordenados: `res` < `ret`, então **o revendedor ganha no alfabeto**.
Confirmado na publicação v12 ativa:

```
common_contract.purchase_profile.question_node_id = faq:tock-reseller-profile
```

Todo cliente, inclusive de varejo, era qualificado por dentro do galho de
atacado. Daí o discurso de atacado antes de qualificar, e daí a pergunta de
estágio de revenda depois de "uso proprio".

**Não confundir com o v13.** Apesar do nome `brand-identity`, ele só adiciona 8
assets visuais (logos e fontes). Não toca em conversa.

## 3. O que foi corrigido

### v14 — seletor neutro (`sdr-qualification-v14-branch-stability.json`)

Um nó neutro `faq:tock-purchase-profile`, para o qual as duas declarações
apontam. O campo continua declarado por galho — colapsar em um só faria
`branch_selection_field_key` devolver `None` e desligar a seleção de galho
inteira, pior que o defeito. O nó usa `capabilities.global_context` para
alcançar os dois fechos sem descender de nenhum, mecanismo que tone e rule já
usam.

Declara também, a pedido do operador:

- **jornada única** — o galho escolhido é imutável;
- **dois gatilhos** de troca: cliente pedir mais peças, ou pedido atingir 3 peças;
- **origem → galho**: `cabecalho:tock-fatal` → `audience:tock-retail`, para quem
  chega de um site de marca não ser perguntado de novo.

Os nós antigos ficam **superseded, não archived**: `archived` não é status
publicável, e o publisher não tem caminho de remoção — um nó tirado do bundle
para de ser tocado e continua ativo no grafo, que é a falha de órfão já
conhecida aqui.

### v15 — FAQ que direcionam (`sdr-qualification-v15-flow-faqs.json`)

Cobertura antes: **zero** para chegada pelo site, **zero** para "quero mais
peças" (o gatilho), **zero** para item fora do catálogo. Os 292 acertos sobre
desconto eram todos por produto e todos dentro do atacado — o galho dono do
gatilho não sabia falar dele.

Cinco FAQ novas: entrada por site em cada marca, mínimo no atacado, item
inexistente como contexto global, e a **porta de entrada no varejo**.

A porta nomeia a quantidade que a abre e **não quota valor de atacado**. Isso
não é cautela, é contrato: citar `rule:tock-desconto-atacado-30` de uma FAQ de
varejo é recusado como `commercial_claim_evidence_outside_scope`.

Também reescreve a cauda das 7 FAQ de navegação. *"A recomendação pode ser
refinada pelo estilo, ocasião ou objetivo que o cliente informar"* descreve a
capacidade do agente para quem lê o grafo; dito à cliente, mata o turno.

### v16 — voz alcançável (`sdr-qualification-v16-voice-reachable.json`)

`build_system_prompt` lê cada nó de tom e regra como `data.markdown or
data.summary`. As 7 diretrizes concretas da Vitória viviam em
`data.voice.guidelines`, e os fatos da regra de desconto em `data.facts` —
nenhum dos dois era lido. O modelo recebia *"conversa de forma acolhedora,
simples e direta"* e nunca o que isso significa.

Renderizado para `data.markdown`, que o builder já prefere. Sem mudar código.

### n8n — prompt reescrito

Seis defeitos:

1. **Faltava instrução de selecionar galho.** A lista só ensinava a *manter*.
   Com `active_branch_node_id: null`, nada dizia que escolher era tarefa do
   modelo — é isso que produz `branch_action: none`.
2. Duas instruções **duplicadas literalmente**.
3. Vocabulário preso em **"service"**, para uma persona que vende marca e canal.
4. **Nada sobre isolamento de marca**, embora o briefing exija.
5. **Nada proibindo prometer** o que o backend não faz — origem do
   *"vou te enviar as fotos dela agora"* que nunca chegou.
6. A **origem chegava inline** no texto; o modelo podia citá-la num
   `evidence_span`. Agora é extraída como `origin.ref`.

Vocabulário publicado passou a ser exposto: os aliases de enum de cada campo são
literalmente como a cliente fraseia a resposta, e eram usados só para validação.
Lidos do grafo, então o template continua agnóstico de persona.

**Duas coisas revertidas de propósito:**

- Orçamento de chunks: quatro testes de contrato fixam `provider_managed`.
  Cortar ali remove evidência sem ninguém ver; limitar recuperação é o P0 e tem
  dono.
- Reagrupar o prompt: cinco testes fixam as chaves no topo, e um exige
  `policy.rules` igual à política compilada **inteira** — meu agrupamento
  descartava `intents` e `qualification` em silêncio.

## 4. Estado da publicação

```
draft_checksum      sha256:838bf4a0b7aade2f26be480864a327474b649739a27cce6dae80e2df34360ff5
runtime_checksum    sha256:a10338332031b0b67c3d12b1bea56322186d3b32a511c2b6d42148269eaae091
branches_affected   audience:tock-retail, audience:tock-reseller
breaking_changes    []
validation_errors   []
disposition         awaiting_approval
chunks_to_embed     1427
```

Validado pelo workflow **Publish GraphBundle** (run 33933699806, ambos os jobs
verdes). O workflow **só planeja** — ele mesmo imprime que staging e ativação
exigem autorização separada.

**Produção segue na v12.** O agente ainda responde com o defeito.

## 5. Bloqueios operacionais encontrados

Nenhum é causado por esta mudança. Os quatro estavam no caminho.

**5.1 — Lifecycle de deploy travado desde 2026-08-29.**

```
stage           queue_drained
candidate_sha   b6e871cc8e3356ef5ea96f08b67988efce062396
current-tag     20e834cdfa5208f8e8e9c4aed285bb44fce3a324   ← não bate
pause_reason    "runtime worker digest mismatch after resume"
resume_authorization  {}                                    ← vazio
```

`resume-claims` exige `resume_authorization.authorized == True`;
`authorize-resume` só é aceito em `awaiting_resume_authorization`. De
`queue_drained` seria preciso avançar por `migration_complete` e
`candidate_healthy`. **Pausar hoje deixa o agente mudo sem volta pelo caminho
sancionado.**

**5.2 — Dois arquivos de estado discordam.**
`.deploy/microservices/resume-state.json` diz `workers_resumed`;
`.deploy/lifecycle.json` diz `queue_drained`. Trilhas diferentes, não
reconciliadas.

**5.3 — Checkout da VPS derivou.** `/opt/brain-ai` está em `main` no commit
`f4872d7`, **576 commits atrás** de `origin/main`, com **137 alterações locais**
(35 modificados, incluindo `api/Dockerfile`, `api/requirements.txt`,
`api/routes/conversations.py`; 102 novos, muitos deles lixo de redirecionamento
de shell como `runtime_version`, `repetition_audit`, `pipeline_contract`).

Produção **não roda desse checkout** — roda de imagens Docker. O checkout serve
aos scripts de ops, que por isso divergem do repositório (foi o caso do
`run-microservice-wa-validator.sh`).

**5.4 — Resync do n8n exige claims pausados.**
`manage-production-conversation-workflow.yml` falha no preflight:
`assert value.get("paused") is True`. O gate está certo: reprovisionar o
workflow de conversa com tráfego vivo pode perder ou duplicar um turno.

## 6. Caminho seguro identificado

O publisher **existe dentro do container** `brain-ai-control-plane-green-1`
(`services.graph_bundle_publisher`, com `stage_bundle` e
`activate_staged_bundle`). Isso permite publicar **sem tocar no checkout
derivado**: basta o JSON do bundle chegar ao container.

Ordem obrigatória: **grafo antes do n8n**. O prompt novo aponta para
`policy.rules.branch_selection.origin_binding`, que só existe a partir da v14 —
reprovisionar antes deixa as instruções sem efeito.

## 7. O que falta

1. Publicar e ativar a v16 pelo container do control-plane.
2. Reprovisionar o workflow n8n (exige pausar claims, que exige 5.1 resolvido).
3. Reconciliar o lifecycle e o checkout da VPS.
4. Rodar o cenário `sdr_sales_branch_switch` do WA Validator como prova.
5. Item 4 do `AGENT_ROADMAP.md` está desatualizado: diz que a v12 está sem
   autorização de publicação; ela está ativa desde 2026-09-01.

## 8. Bloqueio novo: as cópias de serviço divergiram, e produção roda a velha

Achado ao investigar por que o publisher recusa a v16 mesmo com o checksum
aprovado. Não é causado por esta mudança — estava lá desde o carve-out do
monorepo — mas é ele quem impede a publicação agora.

**O monorepo duplica módulo de serviço**: existe `api/services/<nome>.py` (o
monolito) e `apps/<serviço>/api/services/<nome>.py` (o microsserviço
deployável). **Produção roda a cópia do microsserviço. O monolito não é
deployado.** Qualquer leitura de `api/services/` como fonte de comportamento em
produção está lendo o código errado.

As duas cópias de `graph_compiler_v3.py` provam o ponto:

```
api/services/graph_compiler_v3.py                       COMPILER_VERSION = "graph-compiler-v3.6.4"
apps/control-plane/api/services/graph_compiler_v3.py     COMPILER_VERSION = "graph-compiler-v3.6.2"
```

A divergência nasceu no carve-out, não é deriva posterior. O commit
`252cac8 feat: consolidate microservices and contracts in monorepo` criou
`apps/control-plane/api/services/graph_compiler_v3.py` a partir de um snapshot
já desatualizado do monolito — em `graph-compiler-v3.6.2`, enquanto
`api/services/graph_compiler_v3.py` já estava em `v3.6.4`. Desde esse commit a
cópia do control-plane **não recebeu nenhum commit seguinte**. O salto de
versão que falta é exatamente `72dceca fix(tock): canonicalize approved FAQ
projections` — uma correção de projeção de FAQ do Tock Fatal que, por estar só
do lado do monolito, **nunca chegou a produção**.

Escopo medido hoje entre `api/services/` e `apps/control-plane/api/services/`:
**57 arquivos duplicados, 23 divergentes, 34 idênticos.** Entre os divergentes:
`graph_compiler_v3.py`, `graph_bundle.py`, `graph_bundle_publisher.py`,
`kb_intake_service.py`, `sofia_orchestrator.py`, `knowledge_graph.py`.

> **Correção 2026-09-05.** A primeira medição desta seção dizia "23 divergentes"
> para o control-plane. Estava errada: comparava byte a byte e contava 12
> arquivos que diferem **apenas em fim de linha** (CRLF deste checkout Windows
> contra LF), não em conteúdo. Normalizando a quebra de linha, a divergência
> real é:
>
> | app | divergentes de verdade |
> |---|---|
> | `control-plane` | **11** |
> | `conversation-runtime` | **13** |
> | `transport` | **5** |
>
> O `graph_compiler_v3.py` continua entre eles em control-plane e
> conversation-runtime, então o bloqueio da v16 não muda. Mas `graph_bundle.py`,
> que eu havia citado como divergente, é só fim de linha — está idêntico.
> `tests/test_service_copy_divergence.py` usa a comparação normalizada, que é a
> correta.


`tests/test_monorepo_boundaries.py` é o teste que governa dono de serviço e
fronteira de import entre monolito e microsserviços. Ele não verifica se as
duas cópias de um mesmo módulo continuam iguais — por isso a divergência ficou
sem detecção desde 31/08.

**Consequência concreta, hoje:** a publicação do bundle Tock Fatal v16 está
bloqueada. Os checksums aprovados na seção 4 acima
(`draft sha256:838bf4a0…34360ff5`, `runtime sha256:a1033833…9eaae091`) foram
computados pelo compilador `3.6.4`. O control-plane deployado roda `3.6.2`,
rejeita as seis FAQ de saudação como `factual_faq_without_claim`, e computa um
draft checksum diferente (`sha256:3dcd510d…429864bc`). O invariante 3 do
roadmap exige que o checksum aprovado seja o ativado — com compiladores
diferentes nas duas pontas, isso não é possível.

**Antes de portar `3.6.2` → `3.6.4` no control-plane**, uma pergunta em aberto
exige humano: se o `3.6.2` foi escolhido de propósito no carve-out ou copiado
por acidente — a mensagem do commit `252cac8` não diz. E, sendo o compilador
parte do runtime de conversa, portar essa mudança é uma **mudança
conversacional** e precisa do teste-canário exigido pelo `CLAUDE.md` ("Toda
mudança conversacional deve executar o teste-canário que prova a fronteira
entre os dois motores e a preservação byte a byte da reply agentic") antes de
ir para produção.

## 9. A causa real: o control-plane lia o grafo sem arestas

Encontrada em 2026-09-05, depois que o `persona:self` foi removido e o staging
**continuou** abortando com `materialized_runtime_checksum_mismatch`. As seções
6 e 8 descrevem obstáculos reais no caminho, mas nenhum deles era o bloqueio.

`list_all_knowledge_graph` filtrava arestas assim:

```python
eq_in_source = client.table("knowledge_edges").select("*") \
    .in_("source_node_id", node_ids).limit(5000).execute().data or []
```

`in_` renderiza **todos** os ids na query string. Com os 1015 nós da Tock a URL
passa do que o gateway aceita, e o `except Exception: eq_in_source = []` logo
abaixo transformava a recusa em lista vazia. Medido dentro do container:

```
db nodes: 1015   db edges: 0
bundle nodes: 1015   bundle edges: 1924
```

`stage_bundle` grava nós e arestas, relê o grafo pela mesma função e recompila
para conferir o checksum contra o plano. Relendo sem arestas, o documento
recompilado nunca podia bater — **publicar um bundle a partir da produção era
impossível**, para qualquer persona grande. É a explicação de uma anomalia que
esta investigação vinha carregando sem resposta: a v12 ativa foi compilada
**fora** da produção porque de dentro dela não dava.

A segunda consequência é pior e ainda não tinha aparecido: o
`_preflight_source_scope` compara o bundle com as arestas **existentes**. Com o
conjunto vazio, ele aprova em silêncio um bundle que orfana todas as arestas
vivas.

O monólito já tinha a correção — lotes de 100 ids (`_EDGE_LOOKUP_BATCH`) e falha
de leitura que **levanta** em vez de parecer vazia — com um comentário que
descreve exatamente este cenário, inclusive o efeito sobre o preflight. As duas
cópias que rodam em produção carregavam a versão original: mais um caso da seção
8, e o mais caro dela, porque o sintoma não se parecia com um bug de leitura.

### Como diagnosticar isso de novo

O erro `materialized_runtime_checksum_mismatch` não diz o que difere. O que
resolve é comparar `plan["candidate_document"]` com o documento recompilado do
banco, campo a campo, dentro do container. Foi assim que `edges: len db=0
cand=1924` apareceu. Um primeiro diagnóstico chamou
`list_all_knowledge_graph(persona_id=None)` e leu **todas** as personas (2589
nós, com a Baita junto) — o plano não expõe `persona_id`; ele vem de
`graph_bundle.normalize_bundle(bundle)["persona"]["id"]`.

### Correção

`b33d628` porta a leitura em lotes para `apps/control-plane/api/repositories/`
`control_plane.py` e `apps/conversation-runtime/api/repositories/runtime.py`, com
o teste de regressão em cada serviço dimensionado nos 1015 nós que quebraram.
Canário de fecho de galho, fronteira de monorepo e divergência de cópias
seguem verdes.

`9381bfa` corrige um segundo obstáculo, descoberto no dry-run do deploy: o
`prepare` do `rollout-microservices.sh` parava os workers dos serviços marcados
como *behind*, mas o preflight julga **cada worker pelo seu próprio digest**, sem
a tolerância de digest pendente que o serviço tem. O control-plane aparecia como
`up to date` e seus três workers não — o deploy falharia depois da pausa já estar
em vigor. Agora `status` nomeia todos os workers que reprovariam e `prepare` para
exatamente esse conjunto.
