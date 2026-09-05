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

> **Correção 2026-09-05 (fim do dia).** Esta frase está certa sobre a origem do
> vocabulário e **errada sobre o que ele garante**. Expor os aliases ao modelo é
> bom; o defeito é a instrução que veio junto — "normalize it with that field
> validation aliases" — somada a `validation.mode = "enum"` com lista fechada.
> Uma cliente que responde "Proprio" fica fora da lista, o modelo não emite o
> fato, e sem fato não há galho. Foi assim que o vazamento de marca da seção 10
> aconteceu. Alias é exemplo de fraseado, não o filtro que decide se o fato
> existe — ver a invariante 4 do `AGENT_ROADMAP.md`.

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

~~**Produção segue na v12.** O agente ainda responde com o defeito.~~

> **Correção 2026-09-05 (fim do dia).** Superado: o conteúdo foi publicado como
> **v13** e está ativo. O seletor duplicado da seção 2 está corrigido em
> produção — nenhum lead novo é qualificado por dentro do galho de atacado por
> acidente alfabético. O que apareceu depois é um defeito diferente, no caminho
> em que **nenhum** galho é selecionado: seção 10.

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
4. ~~Rodar o cenário `sdr_sales_branch_switch` do WA Validator como prova.~~
   **Corrigido 2026-09-05:** ele foi rodado, **passou**, e a publicação vazou
   marca mesmo assim. Aquele cenário não é prova de isolamento — ele exercita só
   a direção fácil. Ver 10.5 para os cenários que faltam.
5. Item 4 do `AGENT_ROADMAP.md` está desatualizado: diz que a v12 está sem
   autorização de publicação; ela está ativa desde 2026-09-01. **Atualizado no roadmap em
   2026-09-05, junto com a publicação da v13.**

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

## 10. Depois da v13: vazamento de marca quando nenhum galho é selecionado

A publicação da v13 (conteúdo do bundle `sdr-qualification-v16-voice-reachable.json`)
fechou o defeito das seções 1 e 2. Este é outro, e é pior: não é o galho errado,
é galho **nenhum**. A `tock-fatal` vende o mesmo catálogo sob duas marcas a
preços diferentes — varejo e atacado, 30% de desconto, mínimo de 3 peças —, e o
isolamento entre elas é a garantia comercial mais importante do produto.

### 10.1 Os dois atendimentos

**lead 208 — sem perfil declarado, recebeu preço de atacado.**

```
preço citado       R$ 69,93     <- offer:...-atacado
preço de varejo    R$ 99,90
mínimo             3 peças
reply              "Você está comprando para revenda, certo?"
card citado        atacado
```

O cliente nunca disse nada que o colocasse no atacado. Este é o vazamento puro:
sem galho ativo, o RAG entregou as duas marcas e o modelo falou pela que
apareceu.

**lead 209 — respondeu ao perfil e o fato não existiu.**

```
[in ] Proprio
[out] "Perfeito! Então você quer para uso próprio"
      facts: []            branch_selections: []
[out, turno seguinte] "você está começando a revender agora ou já tem loja?"
```

O reply afirma o perfil; o envelope não. É a assinatura do defeito, e é
detectável por máquina — ver 10.5, cenário A.

### 10.2 A cadeia verificada elo a elo

Tudo abaixo foi **confirmado em produção**. Nenhum item é hipótese.

| # | Elo | Estado observado |
|---|---|---|
| 1 | contrato publicado | `purchase_profile`, `owner_node_id: persona:tock-fatal`, `scope: persona` |
| 2 | `contract.questions` | `faq:tock-purchase-profile` -> `purchase_profile` |
| 3 | projeção `cart` (de `lead.metadata.conversation_state`) | `asked_question_node_ids: ["faq:tock-purchase-profile"]` |
| 4 | prompt | `expected_answer_field_key: purchase_profile` |
| 5 | proof checker | `valid: true`, `errors: []`, `gating_errors: []`, `accepted_facts: []` |
| 6 | validação do campo | `mode: "enum"`, aliases fechados — "Proprio" fora da lista |
| 7 | retrieval | galho nulo, `context_cards` não escopados, as duas marcas |

O elo 1 merece nota: o bundle declara `purchase_profile` **por galho**
(`owner_node_id: audience:tock-retail` e `audience:tock-reseller`,
`scope: branch`); quem o promove a `persona` é o compilador, em
`_selector_shared_field` (`graph_compiler_v3`). Ler só o bundle leva à conclusão
errada sobre quem é o dono do campo.

O elo 5 é o que importa: **o checker não rejeitou nada. Não havia o que
aceitar.** O elo 6 é a causa: os aliases publicados são

```
uso-proprio-varejo   uso próprio · pra mim · varejo · comprar para mim
atacado-revenda      revenda · revender · atacado · minha loja · empreender
```

e o prompt instrui "When expected_answer_field_key is set and the customer
answers that question, emit the fact under that exact field key and **normalize
it with that field validation aliases**". O modelo entendeu a resposta — o reply
prova — e, não conseguindo normalizar para um valor canônico, não emitiu. Sem
fato, `branch_selections` vazio; sem galho, o elo 7.

Não existe correção por alias. Sempre haverá uma palavra fora da lista. É o que
a **invariante 4** do `AGENT_ROADMAP.md` passa a proibir: o isolamento é
determinístico, o vocabulário do cliente não.

### 10.3 Defeitos mecânicos no template n8n encontrados no caminho

Em `apps/conversation-runtime/n8n/persona-conversation-template.json`, nós
`Validate agent response` e `Validate repaired agent response`:

1. **`next_question_node_id: null` fixado** na montagem de `legacyProposal`. O
   `asked_field_key` que o modelo devolve no envelope não entra ali.
   **É esta a causa do `semantic_turn_failed:question_semantically_askable` do
   WA Validator, e não o modelo improvisando pergunta.** O critério lê
   `proof.next_question_node_id` e, no modo `n8n_agents`, exige que ele pertença
   a `askable_question_ids` (`wa_validator_service`). Com `null`, só passa o
   turno que não tem campo faltando.

   Ressalva verificada no repositório: desde `a9b3bb2` o runtime tem um resgate
   parcial — `interpretation.asked_field_key` vira `next_question_node_id`
   **quando** a chave nomeia um campo do contrato com `question_node_id`
   publicado (`graph_agent_runtime_v3`). Por isso o critério não reprova sempre;
   ele reprova toda vez que o modelo pergunta algo que não é campo pendente do
   contrato — que é justamente o comportamento consultivo que o roadmap pede.

2. **`interaction_observation` fixado** em `{kind: 'unclear', evidence_span: '',
   confidence: 0}`, nos mesmos dois nós, independentemente do que o modelo
   observou.

3. **Terceiro defeito relatado que não se reproduz — conflito registrado, não
   fato.** A leitura de que `const approvedChunks = [];` faz o nó
   `Build graph grounded agent request` descartar os `rag_chunks` **não se
   confirma** no repositório: três linhas abaixo, `for (const chunk of
   (context.rag_chunks || []))` preenche a lista, que vai ao prompt como
   `approved_chunks`, e o manifesto reporta `retained_chunk_count`. Antes de
   tratar como defeito é preciso comparar com o JSON **vivo** dentro do n8n — a
   seção 8 registra que o prompt reescrito já estava provisionado sem que
   ninguém tivesse confirmado, e o workflow no n8n é outro artefato. Governança
   regra 3: reportado, não escolhido em silêncio.

### 10.4 Dois diagnósticos errados, e o que os derrubou

O registro dos erros vale mais que o do acerto: os dois têm o mesmo vício.

**Erro 1 — "os aliases de varejo são assimétricos; o casamento literal falhou".**
Concluído a partir de um `evidence_span: "revenda"` visto num turno
bem-sucedido, do qual se inferiu que a extração era casamento de string feito
pelo runtime. **Falso.** A extração é do modelo, e aquele `evidence_span` era o
próprio modelo citando a evidência dele. O mecanismo foi inferido de um artefato
de saída em vez de lido na proposta do modelo. A correção que decorreria daí —
mexer nos aliases — teria sido inócua: o problema não é "casou errado", é "não
propôs".

**Erro 2 — "incluir `meta` em `_workflow_checksum` para o gate do n8n fechar".**
**Falso.** `n8n_client.update_workflow` envia somente
`name/nodes/connections/settings`, e a API pública v1 do n8n não aceita `meta`.
`would_change` viraria permanentemente `true`, e a mesma fase `after` **também**
assere `would_change is False` — duas asserções impossíveis no lugar de uma. A
proposta foi feita antes de verificar se a API aceitava o campo. A correção que
de fato fechou o gate está no `AGENT_ROADMAP.md`, dívida operacional, item 8.

**O que destravou os dois foi o operador questionar a premissa** — "porque
alias? o prompt e o rag nao esta totalmente pronto para isso?" — e não mais
evidência.

**A regra que sai daqui**, fixada como governança 9 do `AGENT_ROADMAP.md`:

> Quando o sintoma for "campo estruturado vazio no turno", a primeira leitura é
> `conversation_turn_proofs.model_proposal` comparada com
> `proof_result.accepted_facts`. Isso separa em um passo **"o modelo não
> propôs"** de **"algo rejeitou"** — e as duas causas levam a correções opostas.
> Inferir o mecanismo a partir de um campo de saída é o que produziu os dois
> erros acima.

### 10.5 O que teria pego isso antes de chegar no cliente

Nada do que existe hoje pegaria. E há uma razão estrutural, não um descuido:

**o WA Validator só sabe falar o vocabulário publicado.** As falas do cliente
sintético saem de `api/evaluation/wa_validator_customer_profiles.json`, e as
aberturas de `sales` usam alias exato:

```
sdr_sales_retail         "Oi! Quero algumas peças para uso próprio."   <- alias
sdr_sales_reseller       "Oi! Quero conhecer opções para revenda."     <- alias
sdr_sales_branch_switch  "Oi! Quero conhecer opções para revenda."     <- alias
branch_switch_text       "Na verdade, é para uso próprio."             <- alias
```

E `_semantic_sales_script` escolhe o galho alvo casando
`preferred_terms = ("revenda", "atacado")` ou `("varejo", "uso-proprio", "uso
próprio")` contra o texto do anchor. Ou seja: o gerador do cenário **é ele
próprio** um casador de alias. Por construção ele nunca produziu um cliente fora
da lista — e por isso `sdr_sales_branch_switch` passou
(`active_branch_node_id: audience:tock-reseller`,
`deterministic_branch_match: true`) enquanto o cliente real vazava.

O único critério vermelho da rodada foi `question_semantically_askable`, lido
como "o modelo improvisa". Era o bug de 10.3.1. **Um sinal verdadeiro atribuído
à causa errada custa mais que sinal nenhum**: ele consumiu a atenção que o
vazamento não recebeu.

Os cenários abaixo estão especificados para implementação, mas **não foram
implementados aqui** — eles vivem em `wa_validator_service` e no JSON de perfis,
que estão sob edição de outro agente e são cópias duplicadas (`api/`,
`apps/conversation-runtime/`, `apps/control-plane/`, `apps/transport/`; ver
seção 8, a divergência entre cópias). Quem implementar precisa tocar todas as
cópias vivas, ou o cenário existe só no monolito, que não é deployado.

---

**Cenário A — `sdr_sales_retail_colloquial`: varejo respondendo fora da lista.**

*O caso do lead 209.* Registrar em `_FLOWS` e mapear
`_FLOW_BUSINESS_MODELS["sdr_sales_retail_colloquial"] = {"sales"}`.

- Abertura sem alias e sem origem: `"Oi, vi as roupas de vocês e queria dar uma
  olhada"`. Nenhum `origin_ref`.
- Resposta à pergunta de perfil tirada de um **corpus de fraseado**, não de uma
  string única — a mesma forma que `_sdr_flow_corpus()` já usa. Mínimo:
  `"Proprio"` (literalmente o do lead 209), `"é pra mim mesmo"`, `"pra usar"`,
  `"só uma pecinha pra mim"`, `"nao é pra revender"`. Nenhum deles pode estar
  entre os aliases publicados — a asserção de que estão fora é parte do teste, e
  deve falhar se alguém adicionar o alias em vez de corrigir a classificação.
- Asserções: `purchase_profile = uso-proprio-varejo` em `accepted_facts`;
  `branch_selections` com `action=select` e
  `branch_anchor_node_id: audience:tock-retail`; `active_branch_node_id ==
  audience:tock-retail`; nenhum `cited_node_ids`/`cited_chunk_ids` no fecho de
  `audience:tock-reseller`.
- **Critério novo, o mais valioso — `reply_claims_no_unextracted_field`:**
  reprovar quando o `reply` afirma o valor de um campo pendente (casando com os
  valores canônicos **ou** com seus aliases) e `accepted_facts` não contém
  aquele campo. É exatamente a assinatura de 10.1 — "Perfeito! Então você quer
  para uso próprio" com `facts: []` — e pega a família inteira do defeito sem
  depender de saber qual palavra o cliente usou.

**Cenário B — `sdr_sales_price_before_profile`: o vazamento puro.**

*O caso do lead 208.* É o mais importante dos quatro, porque não depende de o
cliente responder nada.

- Abertura: `"Oi, quanto custa?"` — sem perfil, sem `origin_ref`, sem qualquer
  termo de galho. Máximo de 2 turnos.
- Estado esperado no turno 1: `active_branch_node_ids == []`.
- **Critério novo — `no_branch_scoped_claim_without_branch`:** com
  `active_branch_node_ids` vazio, reprovar qualquer `claim`, `cited_node_ids` ou
  `cited_chunk_ids` cujo nó pertença ao fecho de um `branch_anchor`. Sem galho,
  só conteúdo de `global_context` é citável. Este critério é a tradução direta
  da garantia comercial, e o lugar definitivo dele é o proof checker — mas ele
  precisa existir primeiro como critério de validador, onde não bloqueia
  atendimento enquanto está sendo calibrado.
- Asserções de texto como rede secundária: proibir `R\$\s*\d`, `mínimo de 3`,
  `revenda` e `atacado` no reply. Rede, não garantia — a garantia é a citação.
- O reply correto aqui é responder o que dá para responder sem galho e fazer a
  pergunta de perfil.

**Cenário C — `sdr_sales_brand_asymmetry`: os dois sentidos, e o gatilho.**

Quatro trechos, rodados contra os dois galhos, provando que a assimetria
varejo/atacado é respeitada nas duas direções e que a troca só acontece por
gatilho declarado.

1. *Varejo por fraseado livre* (reusa o corpus do cenário A), depois pergunta de
   preço. Esperado: **R$ 99,90**, sem `30%`, sem `mínimo de 3`, e sem citar
   `rule:tock-desconto-atacado-30` — citá-la de uma FAQ de varejo já é recusado
   como `commercial_claim_evidence_outside_scope`, e o cenário prova que a
   recusa acontece.
2. *Atacado por fraseado livre* — `"tenho uma lojinha"`, `"quero pra vender"` —
   depois pergunta de preço. Esperado: **R$ 69,93** e o mínimo de 3 peças, e
   **nunca** o preço de varejo apresentado como o dele.
3. *Gatilho legítimo de troca*, a partir do galho de varejo: `"na verdade quero
   5 peças"`. O bundle declara em `stability.switch_triggers`
   `customer_requests_more_pieces` e `order_reaches_wholesale_minimum`
   (`min_total_quantity: 3`). Esperado: troca para `audience:tock-reseller`, com
   `evidence_span` apontando a frase, e os fatos compatíveis preservados.
4. *Menção casual que NÃO é gatilho*: `"uma amiga minha revende"`. O bundle é
   explícito — "Nenhuma outra evidência troca o galho. Menção casual a revenda,
   atacado ou preço não é gatilho." Esperado: galho **inalterado** e nenhum card
   de atacado citado. Este trecho é o teste da regra de estabilidade da v14, que
   hoje nada exercita.

**Cenário D — `sdr_sales_origin_binding`: a origem decide antes do turno 1.**

Cobre a regra `origin_binding` introduzida na v14, hoje sem nenhuma cobertura.

- Inbound com `origin_ref: cabecalho:tock-fatal` e mensagem neutra
  (`"Oi, vi no site"`).
- Esperado: `purchase_profile = uso-proprio-varejo` e
  `active_branch_node_id = audience:tock-retail` **já no turno 1**, com a
  pergunta de perfil **não** feita (`faq:tock-purchase-profile` fora de
  `asked_question_node_ids`).
- Variante negativa: `origin_ref` desconhecido — a pergunta de perfil **é**
  feita e o galho continua nulo.

---

**Correção transversal necessária antes que qualquer cenário acima signifique
alguma coisa:** desfixar `next_question_node_id` no template (10.3.1). Enquanto
ele for `null`, `question_semantically_askable` reprova por um motivo que não é
o do cenário, e um vermelho falso volta a consumir a atenção — foi exatamente o
que aconteceu nesta rodada.

### 10.6 O que fica para depois

1. **Substituir o enum fechado por classificação do modelo** em
   `purchase_profile`: valores canônicos como alvo, aliases rebaixados a
   exemplos ilustrativos no prompt, e a instrução "normalize it with that field
   validation aliases" reescrita. Muda bundle e prompt; é mudança conversacional
   e exige o teste-canário do `CLAUDE.md`.
2. **Desfixar `next_question_node_id` e `interaction_observation`** no template
   n8n e reprovisionar — depende de pausar claims, portanto do item 1 da dívida
   operacional.
3. **Conferir o `approved_chunks` do workflow vivo** contra o do repositório
   (10.3.3) antes de tratar aquilo como defeito.
4. **Implementar os quatro cenários e os dois critérios novos** de 10.5, em
   todas as cópias vivas do `wa_validator_service`.
5. **Levar `no_branch_scoped_claim_without_branch` ao proof checker** depois de
   calibrado no validador. Enquanto ele não existir lá, o isolamento comercial
   depende de o modelo se comportar — que é precisamente o que falhou aqui.
