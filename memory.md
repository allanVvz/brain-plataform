# Brain Platform Memory

Updated: 2026-08-24

> Checkpoint positivo atual: Aurora e Tock Fatal passaram a preservar a fala
> natural do modelo depois do proof. A Aurora demonstrou boa compreensão de
> necessidade, memória de nome/veículo e múltiplos serviços em conversa real.
> A pendência observada na Tock não foi falta de inteligência do modelo: uma
> consulta de catálogo acionou a enumeração completa do grafo, gerou HTTP 414 e
> pressão de memória no worker, enquanto o RAG não possuía FAQs autossuficientes
> por grupo. A release de 2026-08-24 remove esse scan do caminho conversacional,
> preserva perguntas embutidas em confirmações e adiciona navegação consultiva
> por ProductGroup sem misturar varejo/atacado. Evidência corrente:
> `docs/handoffs/CHECKPOINT_SDR_PRODUCAO_2026-08-24.md`.

> Fechamento produtivo do checkpoint: release `2d160a54f930ac3261b3c80b1c98805ff36829a8`,
> Tock Fatal v11 (`sha256:e139c137…a9a5dc65`) e Aurora v75
> (`sha256:3f727095…917811ec`) ativas. Smokes diretos Tock
> `f4c93948-9385-420c-9c41-b9a676a62ffd` e Aurora
> `8db699d9-6e29-4337-a14c-1a49b08bc602` passaram o envelope técnico em todos
> os sete turnos. Depois da prova, leads/mensagens foram zerados e API/workers
> ficaram ativos na mesma imagem. A consulta ampla da Tock já lista produtos
> reais, mas ainda deve priorizar ProductGroup por meio de projeção por canal no
> GraphBundle; não reintroduzir seleção determinística no runtime para isso.

> As informações abaixo permanecem como histórico operacional. Quando houver
> conflito de versão, checksum, lead ou estado de worker, prevalece o checkpoint
> mais recente acima e a auditoria read-only da produção.

> Estado corrente: hotfix de áudio (PR #50) foi deployado, testado ao vivo
> via WA Validator e **revertido** — `quality_pass=false` nas duas sessões,
> rollback aplicado (`ops/vps/rollback.sh`, run `32428992506`, voltou pra
> `d3ef93f2…`). **Aurora e Tock Fatal seguem `safety_paused`, workers
> parados.** Registro técnico completo, com evidência de deploy/rollback:
> `docs/reports/AUDIO_HOTFIX_AURORA_TOCK_2026-08-20.md`. Não religar nenhuma
> das duas sem completar o checklist "Critério para novo rollout" desse
> relatório (item 1, fix do WA Validator, já mesclado em `main` via PR #52,
> commit `2e8e2fe`; itens 2-4 — gate de identidade do rollback, repetir
> auditoria/deploy/ressync, exigir technical+quality pass — seguem abertos).

## Handoff atual — conversas reais, memória e próximo hotfix (2026-08-20)

Este é o ponto de retomada depois da limpeza de contexto. A tarefa executada
nesta rodada foi somente leitura de produção e documentação. Não houve correção
de código, republicação de grafo, envio de mensagem ou retomada de IA/transporte.

### Estado que deve ser preservado ao retomar

- `main` avançou desde esta auditoria: hotfix de áudio deployado/testado/
  revertido (PR #50, rollback), fix do WA Validator (PR #52), e item 7a/7b
  do roadmap (pontuação de qualificação + rótulo `sdr`/`closer`/`cs`, commit
  `0c55a67` — já commitado e no ar, não é mais "alteração local").
- Aurora: publicação GraphRAG v3 ativa versão 66, checksum
  `sha256:f2010106aec0788c3610c8b3be643a31c6a7d9bb3c7f1cd1633b9e175535dcc0`.
- Tock Fatal: publicação GraphRAG v3 ativa versão 6, checksum
  `sha256:ad330d4897a2a77a7a99b5c506b35e68de82b35f14932ee3e5489c800675d49d`.
- Os dois bindings continuam ativos como cadastro e apontam para
  `n8n_agents`, mas estão em `safety_paused=true`; o worker está parado. Isso
  impede novos atendimentos enquanto se corrige o comportamento.
  > **Superado em 2026-09-04 (operador):** a tock-fatal atende no binding
  > **Meta**, telefone público `51992623375`, correto e respondendo; o binding
  > Evolution dela está fora. A pausa acima é o retrato de 2026-08-24 e não
  > descreve mais o estado. Binding é estado de banco e não é versionado —
  > confira em `workflow_bindings` antes de usar qualquer número, e nunca
  > confunda `whatsapp_phone` (CTA público) com `whatsapp_phone_number_id`
  > (roteamento Meta) ou `channel_binding_id`.
- Leads auditados (IDs internos, sem telefone): Allan/Tock Fatal = `33`;
  Allan Rodrigues/Aurora = `34`; Luiza Camargo/Aurora = `32`.
- Não usar WhatsApp real na correção. Primeiro reproduzir no WA Validator
  interno com o mesmo evento canônico, provar uma decisão/uma resposta e só
  então pedir autorização separada para retomar.

### Julgamento geral

O sistema está seguro contra invenção em alguns pontos, mas conversa como um
formulário. Ele confunde “não inventar” com “não conversar”: pergunta campos,
repete resumos e transfere dúvidas que o próprio conhecimento deveria responder.
Os nodes de tom e voz ajudam apenas quando a resposta passa pelo modelo. Vários
turnos importantes são decididos sem modelo (`model_calls=0`), portanto o texto
continua rígido mesmo com tom de voz publicado.

O problema não se resolve colocando frases específicas no código. A regra deve
ser geral: compreender o ato do usuário, recuperar memória e conhecimento
permitidos, reconhecer o que ele disse, responder o assunto quando houver base
e fazer no máximo uma próxima pergunta útil. O grafo fornece diretrizes,
conhecimento, voz e limites; o atendimento compõe a frase para aquele contexto.

### Allan em Tock Fatal — sequência e erros estruturais

Fonte: mensagens reais do lead `33`, publicação Tock v6.

1. `e ae` + `ooi` geraram uma resposta empilhada:
   `Olá! Vou te ajudar por aqui. / Oi! / Você procura para uso próprio ou para
   revender?`. Três saudações recuperadas viraram uma única fala. O sistema deve
   escolher uma saudação coerente, não concatenar opções de FAQ.
2. Allan respondeu `uso proprio`; Vitória repetiu exatamente
   `Você procura para uso próprio ou para revender?`. A evidência já apontava
   para o público de uso próprio, mas a pergunta não avançou para a necessidade.
3. Ao repetir `uso proprio`, a resposta foi só `Entendi, uso próprio!`. Isso é
   um silêncio conversacional: existe uma mensagem de saída, mas ela não responde
   nem conduz o próximo passo.
4. Allan então disse `sim`, sem haver uma pergunta aberta clara. O sistema
   interpretou o “sim” no caminho oposto e perguntou
   `você já revende ou está começando agora?`. Houve contaminação de público:
   uso próprio virou revenda.
5. `comecando agora?` foi tratado como dúvida de preço/estoque/prazo/política ou
   pedido mínimo. A resposta transferiu para a equipe e ainda afirmou que faltava
   `tipo de compra`, embora Allan já tivesse informado uso próprio. A classificação
   da intenção e a memória do campo divergiram.
6. Um novo `oii` recebeu apenas `Oi! Que bom ter você por aqui.` e não retomou
   a conversa. Novamente houve saída sem continuidade.
7. `ahahaa simm`, `gosto muito` e `quero uma roupa` não receberam resposta.
   Esses três inbounds estão em `dead_letter`; não são silêncio criativo do
   modelo, porque nenhum atendimento foi concluído. Mesmo assim, o produto não
   pode deixar esse tipo de falha invisível na tela.
8. Dois `ola` antigos e o primeiro `e ae` ficaram `ignored` durante janelas de
   pausa. Isso é silêncio operacional, diferente dos erros de resposta acima.

Causa estrutural do vazio comercial da Tock: o bundle publicado contém Persona,
Campanha, Públicos, Tom, FAQs de saudação/qualificação e Regra, mas não contém
produto, oferta ou FAQ de produto validado. Portanto Vitória só consegue escolher
entre varejo/revenda, perguntar campos e transferir. Ela não precisa informar
preço sem fonte, mas precisa falar do produto. Para isso o grafo deve receber
conteúdo aprovado sobre produtos, características, materiais, usos, diferenças,
benefícios demonstráveis e perguntas frequentes. Até existir fonte aprovada,
preço, estoque, prazo e pedido mínimo continuam como lacuna — sem impedir uma
conversa útil sobre o que já estiver validado.

### Allan Rodrigues em Aurora — sequência e erros estruturais

Fonte: mensagens reais do lead `34`, publicação Aurora v66.

1. Lia apresentou uma lista de oito serviços, mas não explicou nenhum. Quando
   Allan perguntou `chapeacao como fuciona?`, respondeu que o atendente explicaria
   depois e voltou a perguntar se queria seguir. É silêncio semântico: o usuário
   pediu conhecimento de produto/serviço e recebeu um desvio de formulário.
2. Allan acrescentou lavagem técnica e o sistema anotou, mas seguiu imediatamente
   para perguntas de qualificação. Não explicou o serviço, o resultado esperado
   ou a diferença entre lavagem e o reparo citado.
3. Após o resumo completo, `ok` não foi reconhecido como confirmação. Lia repetiu
   o mesmo resumo e a mesma pergunta. O estado de confirmação e a interpretação
   de concordância estão desalinhados.
4. `quero pintura po` e `nao ta certo` chegaram em momentos separados. O primeiro
   foi ignorado no buffer; o segundo só foi processado horas depois, quando o
   sistema devolveu outro resumo. A correção do cliente foi convertida em uma
   lista de serviços, não em uma conversa sobre o que estava errado.
5. Depois de `ooi`, Lia repetiu novamente o resumo inteiro em vez de reconhecer
   a saudação e retomar a pendência. Esse é um exemplo de estado antigo dominando
   a intenção atual.
6. Em uma nova necessidade (`to querendo lavar meu carro`), Lia reconheceu
   Lavagem detalhada, mas só perguntou se queria seguir. De novo não falou do
   serviço ou de como ele ajuda.
7. Depois da confirmação, Lia perguntou outra vez se Allan pretendia vender o
   carro ou continuar com ele, apesar de a conversa anterior já registrar
   `continuar com o veículo e cuidar bem dele`. A pergunta soou como falta de
   memória.
8. Quando Allan mudou a resposta para `vender`, Lia lembrou corretamente do
   Ford Ka, mas perguntou de novo se ele poderia levar o carro, apesar da resposta
   histórica `não`. No resumo seguinte, modelo, ano e condição sobreviveram, mas
   a cor branca desapareceu. A memória fica desigual conforme o campo e o novo
   caminho escolhido.
9. Há respostas de saudação como `Oi de novo! Aqui é a Lia.` que terminam ali.
   Uma saudação ou brincadeira deve receber uma reação curta e natural e, quando
   houver conversa pendente, uma continuação útil. Não deve haver turno vazio.

### Como a memória deve funcionar sem frase fixa

A correção antiga escolheu não carregar `objective` e `can_visit_in_person`
automaticamente para uma nova jornada, porque esses valores podem mudar. Essa
decisão evita tratar intenção antiga como verdade atual, mas hoje o efeito é o
oposto: o histórico some da conversa e a IA pergunta como se nunca tivesse visto
o cliente.

O comportamento desejado tem três estados, usando as tabelas de fatos e jornadas
já existentes (não criar tabela nova):

- fato atual confirmado: pode ser usado diretamente;
- lembrança histórica relevante: deve aparecer como hipótese contextual e ser
  confirmada de forma natural;
- desconhecido: perguntar do zero.

Exemplo aprovado apenas como resultado esperado, nunca como texto fixo:
`Vi que no atendimento anterior você não pretendia vender o carro e queria
investir em cuidado e proteção. Continua sendo isso?` O conteúdo deve ser montado
a partir do último fato, sua origem, sua idade e o assunto atual. Se o cliente
disser `vender`, o valor atual substitui a hipótese histórica. A mesma regra vale
para disponibilidade presencial e qualquer campo que o grafo marque como
“lembrar, mas confirmar em uma nova necessidade”.

O grafo/contrato deve declarar a política de memória de cada campo, sem nomes de
cliente ou frases comerciais no código: estável e reutilizável; histórico que
precisa confirmação; ou exclusivo daquela jornada. Os dados continuam em
`conversation_facts`/`conversation_journeys` e em metadata existente.

### Regras de conversa a implementar e validar depois

- Cada inbound efetivamente assumido deve terminar em uma resposta persistida ou
  em transferência explícita e visível. Duplicata, pausa e falha podem não enviar,
  mas precisam de estado claro; nunca parecer que o agente “escolheu ficar mudo”.
- Responder primeiro ao que foi dito. Só depois avançar a qualificação, com no
  máximo uma pergunta relevante.
- Um `sim`, `não`, `ok` ou brincadeira só pode alterar um fato se houver uma
  pergunta aberta inequívoca. Sem isso, pedir esclarecimento de modo natural.
- A escolha de um público nunca pode ativar perguntas do público oposto sem nova
  evidência explícita.
- Saudações em FAQ são alternativas, não blocos concatenáveis.
- Tom e voz também devem alcançar respostas sem chamada ao modelo; hoje caminhos
  determinísticos ignoram boa parte dessas diretrizes.
- O SDR pode omitir preço não validado, mas deve apresentar produto/serviço com
  base no grafo: o que é, para quem serve, benefício aprovado e uma pergunta de
  descoberta. Transferir somente a lacuna específica.
- Correção do usuário tem prioridade sobre resumo pendente. Não repetir o resumo
  até incorporar e reconhecer a correção.
- Resumo deve usar apenas fatos atuais do caminho e indicar claramente qualquer
  lembrança ainda não confirmada.
- Testar humor, saudação repetida, mensagens em rajada, mudança de intenção,
  pergunta de produto, concordância curta, correção e retorno após jornada.

### Hotfix de áudio — executado, testado, revertido (atualização 2026-08-20)

O item acima (mensagem `635`/lead `32`, `polimendo os vidros`, `dead_letter` com
`workflow_step_failed:unknown`) motivou o hotfix implementado no PR #50:
compactar o prompt do template n8n (remoção preventiva de memória opcional
até 22 mil tokens, `agent_activity`→`journey_outcomes`→`recent_messages`→
`historical_facts`, nessa ordem) sem alterar o Whisper nem inventar
correção de palavra/frase fixa — exatamente como orientado abaixo.

Deployado, ressincronizado (Aurora `k5JWkvpQyb8EB3Vw`, Tock
`WDUxL74OUctQHWwG`) e testado com 2 sessões WA Validator reais (áudio
transcrito, nunca WhatsApp real). Resultado: `technical_pass=true` nas duas,
mas `quality_pass=false` — o driver semântico do Validator ainda não trata
confirmação de galho graph-driven como estado válido (exige
`active_branch_node_id` prematuro; a pergunta determinística de confirmação
não tem `question_node_id` mapeável). **Rollback aplicado** de volta pra
`d3ef93f2…`. Detalhe técnico completo, com todos os checksums/runs:
`docs/reports/AUDIO_HOTFIX_AURORA_TOCK_2026-08-20.md`.

**Achado real que bloqueia qualquer retomada, não só deste hotfix**:
`ops/vps/rollback.sh` delega pra `deploy.sh` mas nunca escreve
`.deploy/release-source-sha`/`.deploy/release-directory` (só
`install-release-artifact.sh` faz isso, e o caminho de rollback nunca chama
esse script) — então o validador de produção falha fechado em
`release_source_identity` depois de qualquer rollback, mesmo com a imagem
certa rodando. Esse é o item 2 do "Critério para novo rollout" do relatório.

**Checklist restante antes de religar Aurora/Tock** (relatório, seção
"Critério para novo rollout"):
1. ~~Corrigir o WA Validator pra aceitar confirmação de galho graph-driven~~
   — feito, PR #52, commit `2e8e2fe`.
2. Corrigir o gate de identidade do rollback (`release-source-sha`/
   `release-directory` não atualizados) — **aberto**.
3. Repetir auditoria quieta, deploy, ressincronização e as duas sessões de
   validação (Aurora + Tock).
4. Exigir `technical_pass=true` **e** `quality_pass=true` nas duas antes de
   qualquer retomada — uma autorização (deploy) não implica as demais
   (migração, retomada de binding/workers).

## Correção de multi-serviço e perda de memória entre ciclos (2026-08-18)

Dois bugs reportados ao vivo (lead "Allan Rodrigues", produção) na mesma
sessão de teste, corrigidos juntos porque o segundo apareceu investigando o
primeiro.

### Bug 1 — confirmação/header tratavam o 2º serviço como apêndice

Sintoma: ao pedir dois serviços (Chapeação + PPF), a confirmação final saía
como duas cláusulas `serviço:` separadas mais um parágrafo redundante
"Também no seu pedido: ...", e o header do dashboard mostrava `chapeacao`
(slug cru) e `Chapeação · servico` duplicando o próprio título do grupo.

**Causa raiz real (não é o que parecia):** investigação direta em
`conversation_turn_proofs` de produção provou que o modelo e a camada de
galhos (`service_operations`, ativação de galho) já funcionavam
corretamente — os dois serviços eram ativados como galhos concorrentes
válidos, com fatos distintos persistidos (`proof["valid"]=True`,
`service_operation_proof["valid"]=True`). O bug estava inteiramente na
camada de renderização determinística:

1. `_collected_field_facts` (`api/services/graph_agent_runtime_v3.py`)
   iterava cada galho ativo e gerava uma tupla `("Serviço", valor)` por
   galho, porque o campo seletor (`servico`) é declarado propositalmente
   uma vez por galho, dono = o próprio galho. Corrigido com um parâmetro
   opcional `merge_selector` que funde os títulos de todos os galhos ativos
   numa única cláusula, reusando `active_offering_titles` (já existente).
2. `_active_service_summary` (função inteira removida, junto com sua
   chamada em `_decide`) sempre acrescentava o parágrafo "Também no seu
   pedido" quando havia ≥2 ofertas — em *todo* turno pós-qualificação, não
   só na confirmação — e seu guard de duplicata só pegava repetição
   literal, então era sempre redundante depois do fix acima.
3. `_commercial_note_projection` escrevia o fato do seletor com o slug cru
   (`"chapeacao"`) em vez do título humanizado, e a condição que separa
   fato comum de fato por-serviço exigia que **todo** galho ativo
   redeclarasse o mesmo campo antes de tratá-lo como comum — por isso
   `vehicle_color` (persona-scoped) ficou preso só ao galho de Chapeação
   quando o contrato do galho PPF simplesmente não declarava esse campo
   (gap de catálogo, não de código). Corrigido excluindo o fato do seletor
   dos "facts" normais (mantido só como fallback humanizado se for o único
   fato do galho) e simplificando a condição para `owner not in active`.

**Pontos de rigidez avaliados** (4 itens que o usuário pediu para checar
contra este bug específico): dos quatro, dois eram causa raiz real e
relevante e foram corrigidos junto — a validação de `extracted_facts` em
`check()` era escopada a um único contrato de galho por turno (um fato do
2º serviço na mesma mensagem virava `undeclared_field`/
`field_owner_mismatch` mesmo com a ativação do galho aceita), e um erro de
fato isolado em qualquer lugar derrubava `proof["valid"]` pro turno
inteiro, forçando o caminho 100% determinístico mesmo com o resto da
proposta correto. Corrigido com `additional_fields` em `check()` (união
dedupada por `(key, owner_node_id)` de todo galho ativo, não só o focado)
e particionamento de erros em `_decide` (erro de fato de um galho
não-focado não gateia mais o turno; erro do galho focado continua
gateando, sem afrouxar a validação de claims). Os outros dois pontos (um
mecanismo de "terceiro estado"/`needs_confirmation` ainda hardcoded por
`kind` em vez de genérico, e um caminho de fallback residual —
`_invalid_proposal_fallback`, disparado só quando o JSON do modelo falha
schema — que ainda não reabre confirmação pendente por galho) eram reais
mas não causalmente ligados a este bug específico (afetam tipos de campo
hipotéticos futuros / um gatilho raro); ficaram só anotados, não corrigidos
nesta rodada.

### Bug 2 — novo ciclo/appointment perdia o veículo, só lembrava o nome

Sintoma: depois que um atendimento fecha (evento comercial `delivered`/
`service_completed`/`cancelled`) e o cliente escreve de novo, a Aurora abre
uma jornada nova e repergunta modelo/cor do veículo do zero — só o nome
sobrevive.

**Causa raiz:** `carry_over` (o que semeia a jornada nova a partir da
anterior, `_seed_carried_facts`/`_carry_over_field_keys` em
`graph_agent_runtime_v3.py`) era calculado em
`api/scripts/publish_aurora_graph.py` como
`field_key == appointment_policy.get("identity_field")` — só
`nome_cliente`, um único campo literal — mesmo com os campos de veículo já
corretamente marcados `scope: "persona"` (deveriam sobreviver a troca de
galho *dentro* de uma jornada; carry_over decide sobrevivência *entre*
jornadas, os dois mecanismos estavam desconectados). O compilador genérico
em `graph_conversation_contract.py` já usa `scope=="persona"` como default
de `carry_over` para campos de persona-qualification — só o script de
publish da Aurora não seguia essa convenção (já documentada em
`docs/architecture/SDR_JOURNEY_STATE_MACHINE.md`).

**Correção:** `carry_over` passou a ser `scope=="persona" and field_key not
in {"objective", "can_visit_in_person"}` — híbrido escolhido com o usuário:
qualquer campo persona-scoped futuro carrega automaticamente sem precisar
de outra mudança de código, com `objective`/`can_visit_in_person` como
exceções explícitas (intenção daquele atendimento específico, não
identidade estável do cliente/veículo). **Só faz efeito depois de
republicar o grafo em produção** (`api/scripts/publish_aurora_graph.py`
contra o Supabase de produção) — deploy de código sozinho não resolve.
Publicado ainda em 2026-08-18 (publicação v3 → versão 62).

Sem cobertura ainda para a persona de roupas (`vzlupas_catalog.json` não
tem `appointment_policy`/qualificação estruturada) — quando essa persona
ganhar um grafo próprio, precisa do mesmo tratamento de `carry_over` para
o campo de tamanho de roupa.

## Memória durável entre jornadas + silêncio no reparo de dúvida (2026-08-18, rodada 2)

Duas horas depois do deploy da correção acima, dois testes ao vivo novos
(mesmo dia) reproduziram bugs mais fundos que a primeira rodada não cobriu
— o `carry_over` genérico funciona, mas só sobrevive a **um** fechamento
de jornada; e um caminho de "reparo" separado (dúvida do cliente antes de
escolher serviço) não tinha nenhum piso contra silêncio total.

**Memória não sobrevivia a dois fechamentos de jornada seguidos.**
`_seed_carried_facts` só emprestava o fato herdado pro turno atual em
memória — nunca gravava isso como fato real da jornada nova
(`accepted_facts`, a única coisa que `commit_graph_turn_v3` persiste). Ao
vivo, você mesmo fechou duas jornadas em sequência pelo dashboard
(confirmado no `metadata` da própria `conversation_journeys`,
`"source": "dashboard"` — fluxo normal de operação, não bug de
auto-fechamento). Na segunda troca, a busca por `get_latest_conversation_-
journey` (só a jornada imediatamente anterior) não achava nada, porque
essa jornada intermediária nunca teve o nome persistido de verdade.
Corrigido em duas frentes:
1. `graph_agent_runtime_v3.decide()` agora grava o fato herdado em
   `accepted_facts` sempre que `context.journey_id is None` (o turno exato
   em que a jornada nova está sendo criada) — persistência durável a cada
   troca, não só empréstimo de um turno.
2. Nova função `conversation_carry_over_facts_by_lead_v1` (migration 129)
   busca o valor `known` mais recente de cada campo `carry_over` em
   **qualquer** jornada do lead, não só a anterior imediata — jornadas já
   registradas viram a fonte de verdade completa, por pedido explícito do
   usuário ("temos uma tabela compras, jornadas, tudo deve estar
   registrado e deve ser a fonte de verdade"). Precisa da migration 129
   aplicada em produção pra valer (passo `migrate` do deploy, separado do
   deploy de código e da republicação de grafo).

**Aurora ficava muda mesmo já sabendo a resposta certa.** Cliente
perguntou "como funciona o polimento de vidros?" antes de escolher
serviço. O grafo já tinha resolvido a dúvida deterministicamente
(`doubt_resolution: "answered"`, zero chamadas ao modelo) mas só
autorizava aquela FAQ pra `claim_type: "availability"`, não
`service_detail` — mesmo a resposta aprovada sendo uma explicação de como
funciona. Isso caía no bloco de reparo por dúvida/claim em `_decide`
(`graph_agent_runtime_v3.py`), que — só na primeira tentativa — devolvia
`reply_text=None` esperando uma segunda chamada ao modelo orquestrada
fora do Python, pelo n8n. Essa segunda chamada não completou: silêncio
total, mesmo com o texto certo já calculado. Corrigido em três frentes:
1. Conteúdo do grafo: 7 FAQs da família de polimento (`aurora-faq-glass-
   polish` e mais 6 `aurora-faq-polish-*`) ganharam um segundo claim
   `service_detail` além do `availability` já existente — mesmo padrão de
   `aurora-faq-ppf`, que já tinha os dois. Gap era editorial (`claim_type`
   é digitado à mão por FAQ, sem validação de conteúdo), não de código;
   provavelmente existem outros gaps do tipo em FAQs futuras — vale
   auditoria manual quando surgir sintoma parecido.
2. `_decide` (bloco de dúvida/claim, ~linha 4979): já que
   `repair_requirements` é sempre vazio nesse ramo (nunca há nada de fato
   pra buscar), removida a distinção `correction_attempt < 1` vs `>= 1` —
   resolve imediatamente com o texto aprovado do grafo desde a primeira
   tentativa, sem esperar o round-trip do n8n.
3. Rede de segurança em Python (`conversation_runtime._ensure_reply_text_-
   or_log`, chamada no início de `commit()`): se `reply_text` sair vazio e
   `proof["text"]` tiver conteúdo aprovado pelo grafo, usa isso como
   última instância; se nem isso existir, loga erro em vez de completar
   como sucesso silencioso. **Não cobre o workflow n8n** (`Align reply
   with qualification state` continua sem checar `reply_text` vazio) — só
   o lado Python; editar o workflow n8n é um tipo de risco à parte, fica
   como pendência conhecida pra próxima rodada.

## Histórico arquivado

A seção "Handoff atual — WA Validator em produção" (fase de 2026-08-12, Aurora
pausada) foi movida em 2026-08-19 para
`docs/archive/DEPRECATED_2026-08-19/memory-wa-validator-handoff-2026-08-12.md`.
Ela descrevia um estado que já não vale e era lida por agentes como se fosse o
estado corrente.
