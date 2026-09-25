# Checkpoint 2026-09-25 - branch switch corrigido, candidate barrado por nome

O usuario confirmou que o agente pode mudar de branch quando o cliente pede
outro servico. O runtime agora interpreta `SELECT` sobre branch ativo como
`SWITCH` para um branch diferente ou `KEEP` para o mesmo branch; a prova do
grafo continua exigindo evidencia literal, branch publicado e checksum.
Codigo `57f9b5493f2bbd1a17f6b91e832099da00c8fe26`: 81 testes focados,
compilacao da API, build do dashboard, CI e build da imagem passaram. O teste
integrado com o grafo Tock provou `drop`+`add` na troca e `keep` na reescolha.
Manifesto `ops/microservices/release-manifest.runtime-57f9b54.json`, commit
`f0ba06e5462211eced04c685851d38c458f1da61`, digest candidato
`sha256:07094ec06439817bb2ebbea56e2f434a51eedfce02ae91925a3644088f12b9b2`.
O dry-run `36197982020` passou. O deploy `36198105704` iniciou o candidate
isolado: a excecao anterior de branch nao ocorreu, mas a fixture
`utzig-doubt-interrupting-name` foi barrada porque a resposta perguntou
`nome_cliente` imediatamente apos responder a duvida da Utzig. O erro do gate
foi `candidate repeated the interrupted qualification field`. O candidate
verde foi parado antes do cutover. Nao empilhar outro deploy corretivo nesta
operacao. Auditado depois: runtime azul anterior e transport anterior ativos,
claims nao pausados, zero buffer critico, zero outbound sem proof e zero
divergencia de checksum. A correcao de branch ainda nao esta em producao.

# Checkpoint 2026-09-25 - runtime candidate de84bfa barrado

O usuario retomou o deploy e os testes dos agentes. A mudanca foi classificada
como `service` compativel, limitada ao `conversation-runtime`. O manifesto
incremental `ops/microservices/release-manifest.runtime-de84bfa.json` foi
publicado no commit `14429752f4604983ab091a26a99429719b23461f`;
somente a entrada do runtime mudou para a fonte
`de84bfafb8aed6a37d68b411b3917d24b08cebbc` e o digest
`sha256:e2540322979f4e67e6248ce042575efde59f3e95e93d1e4a2c21b7ca097c49f7`.
O dry-run `36194896547` passou. O release `36195273718` iniciou o candidate
verde isolado, mas a fixture `human-conversation-2026-09-25` falhou na etapa
real do modelo com `RuntimeError: understanding cannot select over an active
branch` em `graph_agent_runtime_v3.resolve_understanding`. Nao houve cutover;
o workflow parou o candidate. Nao fazer segundo deploy corretivo nesta
operacao. Investigar por que o modelo emite `SELECT` para um branch ja ativo e
adicionar cobertura do candidate para esse estado antes de novo release.

Auditoria posterior: runtime azul antigo ainda ativo, digest
`sha256:392e138720deeda5db5159e3ca35ad01eb7505023eb700fbcb6608b774a23523`;
claims nao pausados, zero buffers criticos, zero outbound sem proof e zero
divergencia de checksum. Dry-runs do WA Validator interno passaram para Utzig e
Tock. Na sessao Utzig `1272f869-a65e-4616-88c7-c138026fe652`, houve um
inbound, uma decisao, proof valido, commit e outbound interno, mas
`quality_pass=false` por `service_value_not_reused_as_field`. Na sessao Tock
`54dbdd24-0d20-425e-94bd-2b2b500aa731`, os mesmos invariantes tecnicos
passaram e o primeiro turno semantico passou, mas a sessao marcou `done` com
`quality_scope=null` apos um turno; o runner retornou erro. As jornadas
completas e a terminalizacao do transport continuam pendentes. Nenhum teste
usou WhatsApp real.

# Prioridade da LP Utzig (2026-09-25)

A correção do runtime conversacional ficou adiada durante o trabalho da LP.
O checkpoint anterior, as jornadas Utzig/Tock e a terminalização do transport
foram preservados como pendências. A tentativa posterior consta acima.
O trabalho corrente é de frontend público: destacar a Avaliação já publicada
no primeiro cartão do catálogo, mantendo seu item na linktree. O grafo ativo
permanece v12 (`46925297-f966-42cc-a33a-bd031fa1ded5`,
`sha256:a5bfac4a813f9c7c357910371d70a8e8a2df14e86d93c4374aa4e2f322b1c553`).
O frontend `Card-pio` foi publicado no commit `3c7a989`, promovendo o
Preview `dpl_93jnXz7G7nn28MWvBNieXuPwQ2bk` para Production
`dpl_FK4GdxXWmVU4gbKQM9prS9gQJPuU`. A descrição e o CTA de
`product:evaluation` ficam sempre visíveis no primeiro cartão do catálogo;
os outros 17 serviços seguem expansíveis. Linktree e catálogo passaram em
produção a 1440 e 390 px, sem overflow horizontal ou erro de página.
Screenshots: `.codex-run/utzig-review/production/`. O grafo não foi republicado.

# Checkpoint 2026-09-25 - candidate barrado

O dry-run `36185642472` passou para o runtime `9f21691`, digest
`sha256:02fe8052888301031edae5485b5742ec2132373a6ae7cdcf11d336418bb545ad`.
O candidate da release `36185750075` falhou antes do cutover: o modelo repetiu
`nome_cliente` no turno da dúvida da Utzig. Slot azul e transport anterior
permaneceram ativos; claims não pausados, candidate verde parado. Não repetir
o deploy nesta operação. Ajuste posterior em código explicita o campo adiado
no brief e retira sua guia elegível naquele turno; ainda sem candidate real.
Jornadas Utzig/Tock e terminalização nova do transport continuam pendentes.
Evidência: `docs/research/conversation-candidate-gate-2026-09-25.md`.

# Checkpoint 2026-09-25 - conversa humana

Implementacao: duas chamadas, prompts em portugues, ultima mensagem real nas duas
etapas, question_kind e resolucao unica. Perguntas consultivas sao permitidas.
Confirmacao usa interpretacao, evidencia e referencia pendente. Validator distingue
amostra incompleta de falha. Sem migration ou republicacao de grafo.
Release publicada: runtime 2834149, digest sha256:392e138720deeda5db5159e3ca35ad01eb7505023eb700fbcb6608b774a23523,
slot blue. 84 testes e build do dashboard passaram. Dez turnos internos sem
duplicidade ou outbound real. Tock confirmou handoff; Utzig parou por repetir nome.
Qualidade pendente: anuncio prematuro de handoff, correcao natural de fatos e
metadata ausente no RPC de contexto. Buffer sintetico final da Tock ficou processing
apos commit; transport nao terminaliza inbound com handoff no sink interno.
Nao houve segundo deploy ou correcao manual. Evidencias e proximo trabalho:
docs/research/conversation-human-contract-2026-09-25.md.

# Brain Platform Memory

Updated: 2026-09-14

> Checkpoint mais recente — auditoria pré-disparo da campanha de reativação
> Tock Fatal (2026-09-14), read-only contra produção via `psql`. Binding Meta
> ativo/conectado (`ead9dbcd-...`, `whatsapp_phone_number_id=1274565599076808`).
> Publicação GraphRAG ativa é a **v33** (`graph_publications`, ativada
> 2026-09-11) — mais nova que qualquer versão citada nos checkpoints abaixo;
> contém um bloco de reengajamento (`idle_return`, `stale_reengagement`,
> `journey_completed`, `journey_cancelled`) para quando o próprio bot demorou
> pra responder, que **não é o mesmo mecanismo** de reabrir contato via
> campanha de marketing depois de dias parado — não presumir que a campanha
> puxa essas falas automaticamente. Das 56 leads da persona, **0 têm linha em
> `contact_consents`** — qualquer campanha `campaign_kind="promotional"`
> bloqueia 100% delas com `consent_not_granted`.
> **Atualização no mesmo dia:** o operador autorizou backfill de consentimento
> com base em contato orgânico real (lead que mandou mensagem primeiro conta
> como evidência de relacionamento/interesse) em vez de exigir opt-in formal.
> Rodado via `record_contact_consent_v1` (RPC auditada, não INSERT direto):
> as 56 leads agora têm `contact_consents.status='granted'`,
> `channel='whatsapp'`, `purpose='ofertas_e_novidades'`,
> `source='organic_whatsapp_contact'`, `evidence` apontando pra primeira
> mensagem real da lead. Campanhas `promotional` para essas leads não devem
> mais bloquear por `consent_not_granted`. `leads.updated_at`
> não é fonte confiável de "há quanto tempo a lead não conversa" (contaminado
> por qualquer rebind de binding); a fonte real é `max(messages.created_at)
> group by lead_id` — por essa conta, 52 das 56 leads não têm mensagem há mais
> de 2 dias. O vazamento de marca varejo/atacado documentado abaixo
> (2026-09-05) tem correção **e** cobertura de teste desde o mesmo dia
> (`test_neutral_branch_scope.py`, 9 testes, todos passando em 2026-09-14) —
> o texto do roadmap que dizia o contrário estava desatualizado, já corrigido
> em `docs/roadmaps/AGENT_ROADMAP.md`. "Tricot" não existe como produto no
> grafo (nenhum bundle real tem esse node); os 4 templates de reativação
> criados nesta sessão não o mencionam, então não é bloqueante agora.

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

## Decisão de produto — Utzig Garage (2026-09-22)

Foi criado um candidato graph-only para `utzig-garage`, sem publicação e sem
estado produtivo. Ele usa UUID determinístico de rascunho e permanece com
`publication_allowed=false` até confirmação do UUID produtivo e de um registry
ou CDN aprovado para derivados web. O bundle contém marca, Alemão como
`founder_specialist`, páginas, localização, audiências públicas, 12 serviços,
políticas de agendamento e assets em allowlist. Não contém preço, horário,
garantia ou promessa de resultado.

As faixas comerciais estimadas são privadas e existem somente em
`product.data.metadata.internal_commercial_value_band`; não entram no site,
RAG nem contratos conversacionais. Audiências no site são links telemetrados,
sem popular silenciosamente o CRM e sem vínculos serviço -> audiência.

Próxima evolução de memória/atribuição:

- tratar o grupo semântico de `/leads/import` como audiência canônica;
- correlacionar futuramente site -> WhatsApp -> lead e escrever
  `lead_audience_memberships` de forma idempotente, somente com identidade e
  consentimento suficientes;
- usar audiência como escopo de listas, disparos e templates Meta aprovados;
- manter uma `audience_of_journey` por jornada e iniciar
  `global_lead_audience` pela maior faixa observada entre jornadas;
- permitir que classificador paralelo por média ponderada reclassifique a
  audiência global, preservando notas comerciais e histórico;
- suportar múltiplas jornadas por campanha e propostas Sofia de vínculos
  serviço -> audiência com aprovação humana;
- direcionar campanhas de maior valor a regiões maiores apenas com fonte e
  aprovação;
- manter Meta Pixel condicionado a consentimento, e distinguir evento anônimo
  entregue de atribuição CRM ainda pendente;
- manter depoimentos, certificações e design system Figma como pendências, não
  como fatos publicados.


## Estado conversacional e Utzig (2026-09-24)

- A ordem das perguntas da qualificação agentic não é um roteiro hardcoded: `appointment_policy.field_questions` e dependências dos campos pertencem à publicação ativa do grafo; `missing_fields` mede completude. O modelo escolhe um campo ainda perguntável. Apenas o motor `deterministic`, se explicitamente selecionado, usa `field_questions[missing_fields[0]]`. O WA Validator possui respostas de teste por campo e confirmação sintética; isso não é a ordem produtiva.
- O runtime e Validator publicados na release `a57bc8e` passaram no gate técnico. O E2E interno de 24/09 encontrou qualidade pendente: Utzig repetiu o nome e não concluiu o handoff; Tock aceitou `Sim` como nome e voltou a perguntar. O commit local `cabfded` corrige a aceitação de confirmações como nomes no Validator, mas precisa de release e novo canário antes de ser considerado produtivo.
- Para a Utzig, a instrução atual é trocar somente as capas representativas: Preservação recebe `asset:headlight-before` e Revitalização recebe `asset:process`. As imagens continuam representativas de grupo, sem virar prova direta de serviço. Qualquer publicação nova deve partir de export autenticado da publicação ativa e passar por plan, stage e ativação CAS; os arquivos editoriais v11 baseados na v10 são históricos se a v11 já estiver ativa.
- O linktree da Utzig destaca `product:evaluation` a partir do bloco `home-featured-evaluation` no grafo, sem chamar o serviço de “produto de entrada”. O card mantém a descrição completa visível e ocupa melhor a coluna do desktop. O botão humano usa a copy do grafo: “Fale com o Wilian” / “Deixe sua mensagem para o Wilian. Ele responde pessoalmente assim que puder.” O frontend não substitui mais o rótulo do grafo por string fixa.
- A v12 da Utzig foi ativada por CAS em 24/09/2026: publicação `46925297-f966-42cc-a33a-bd031fa1ded5`, checksum `sha256:a5bfac4a813f9c7c357910371d70a8e8a2df14e86d93c4374aa4e2f322b1c553`. O site `utzig.vercel.app` foi promovido do Preview `dpl_5knZzTPyNY74gGWEKgfraJya6NeB` para Production `dpl_7CRTHGaRwEq2JV2sZ3ySUgAH7uTf`. E2E visual em produção passou em 1440 e 390 px, sem overflow/erros; o canário WA Validator interno `d5c3ea73-3328-4643-bf5c-91d6eadf0401` passou tecnicamente com 1 inbound, decisão, proof, commit e outbound interno. A qualidade completa da jornada Utzig/Tock ainda não foi demonstrada pelo canário de um turno.

## Histórico removido

A seção antiga sobre o WA Validator de 2026-08-12 foi removida porque descrevia
um estado operacional que já não vale. O estado corrente deve ser obtido pelas
auditorias oficiais e pelos handoffs indicados no roadmap.

## Release conversacional de 2026-09-25

- Runtime publicado: fonte `557188fe7aab6664329ced9df33717dda052cbe5`, digest `sha256:25aca0b8495a31b03e64320e845d71eb21076d356f93505ebd3bffd949e05705`, slot blue. Dry-run `36085744592` e deploy blue/green `36085848962` passaram. A apresentação como IA no primeiro reply é padrão para todas as personas; o nome pode ser retomado mais tarde conforme o limite do grafo. A confirmação final agora usa a referência pendente da jornada e conclui o handoff no mesmo commit.
- WA Validator interno Utzig `dde43e69-2cc5-43b1-a536-4e3aae9fcd48`: 7 inbounds, 7 decisões/proofs/commits/outbounds internos, handoff final para humano, `technical_pass=true`, `quality_pass=false`. O modelo ainda repetiu a pergunta do nome imediatamente após responder uma dúvida, apesar da instrução no prompt.
- WA Validator interno Tock `390d46b9-ee4a-4957-a41d-3ae973ae0eda`: 6 inbounds, 6 decisões/proofs/commits/outbounds internos, apresentação como IA e handoff final, `technical_pass=true`, `quality_pass=false`. O critério `required_reply_content` falhou na primeira resposta; no handoff o modelo ainda perguntou como chamar a cliente.
- Auditoria final: zero outbound sem proof e zero divergência de checksum; claims ativos. As falhas de qualidade são pendências de condução para uma próxima mudança, sem segundo redeploy corretivo nesta operação.

## Ajuste do prompt de 2026-09-25

- Release `15576229784d8dd65ffec5ff98f3a1afa238e3aa`, digest `sha256:261e0f6bbebe3f300e59c9846343a857bd11f1266a825ac753290b4578a60781`, slot green; dry-run `36109142196` e deploy blue/green `36109227854` passaram. O prompt passou a receber a identidade de abertura publicada, a instrução de não repetir a pergunta interrompida e a conclusão de handoff sem nova pergunta. O brief não oferece campo opcional depois do handoff. O Validator deixou de fixar `Vitória` no código e lê a identidade da publicação.
- WA Validator interno Utzig `b9673984-89b7-47ce-b8ec-bb38f8c6bb7b`: 6 inbounds, 6 decisões/proofs/commits/outbounds, handoff final, `technical_pass=true`, `quality_pass=false`. A pergunta do nome ainda reapareceu imediatamente depois da dúvida sobre avaliação; o prompt mais claro não bastou.
- WA Validator interno Tock `7de841e7-bdfd-4ed6-9e58-25ff18df53f5`: apresentação correta como Vitória; 3 inbounds, 3 decisões/proofs/commits/outbounds, `technical_pass=true`, `quality_pass=false`. A terceira resposta perguntou sobre categorias sem `asked_field_key` enquanto havia campo de qualificação pendente; o fluxo parou antes do handoff.
- Auditoria final: zero conflito CAS, buffer crítico, outbound sem proof e divergência de checksum. Não houve segundo redeploy corretivo. Próxima hipótese: simplificar o brief para declarar a ação esperada do turno ao modelo a partir do estado já calculado, sem adicionar estado persistido ou bloqueio editorial ao proof.

## Runtime e proof publicados em 2026-09-24

### Ajuste de condução preparado após o E2E

Repetir o nome ainda pendente em um turno posterior é aceitável dentro do limite do grafo; a repetição imediatamente após uma dúvida torna o diálogo circular. A apresentação como agente de IA deve ocorrer no primeiro reply de cada jornada para todas as personas, usando nome e marca publicados. O código local passa `first_reply_in_journey` ao modelo, registra ausência de apresentação como aviso de qualidade e faz o Validator distinguir retomada tardia de repetição consecutiva. Essa mudança ainda não está no digest ativo.

- O usuário confirmou a fronteira: prompt e condução pertencem ao modelo; a chamada ao modelo continua no `conversation-runtime`. O n8n fica em automações auxiliares e transporte, sem modelo, proof, repair ou commit no caminho síncrono. `n8n_agents` é apenas um valor legado de binding; o template em `apps/conversation-runtime/n8n/` é fixture de auditoria, não é provisionável.
- Release compatível do runtime: fonte `5d4af4d51e3eeaf6d73f4fd743b12617e4269f2a`, digest `sha256:d0a8ea096cfc65b25f5dc86883e8e9b6d9d91ea5e690df6ef9172b73452adad5`, workflow `36070246557`, slot green. Dry-run `36070094854`, candidate, cutover e canário WA interno passaram. Sem migration, pausa de claims, WhatsApp real ou deploy de outro serviço.
- O prompt agora aponta explicitamente para fatos conhecidos, pergunta anterior, mensagens recentes, interrupção por dúvida e confirmação final. O checker removeu acúmulo de repair inalcançável; publicação errada continua bloqueante e divergências editoriais seguem em `quality_warnings`.
- WA Validator completo após release: Utzig `b1ee258b-2659-4955-b257-513bde54c698` teve 6 inbounds, 6 decisões/proofs/commits/outbounds, `technical_pass=true`, `quality_pass=false`: repetiu o nome após uma dúvida e não fez handoff após “Sim” para confirmação final. Tock `81b5cdd6-cf49-43ac-8793-ac25897ff581` teve 4 inbounds e 4 decisões/proofs/commits/outbounds, `technical_pass=true`, `quality_pass=false`: interrompeu a qualificação com `forma_recebimento` pendente e fez pergunta consultiva sem `asked_field_key`. Nenhum dos dois teve repair ou handoff.
- O workflow oficial confirmou digest ativo, checksums e zero outbound sem proof. O primeiro sinal de necessidade de outro redeploy corretivo encerra esta operação de release; as falhas de qualidade devem ser corrigidas e validadas como nova mudança, sem empilhar deploys.
