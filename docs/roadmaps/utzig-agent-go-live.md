# Go-live controlado — Utzig Garage

## Escopo e guardrails

- Persona: `utzig-garage`; liberada para todos, sem allowlist.
- Transporte de validação: `internal_validator`; nunca WhatsApp real.
- Sem campanha, disparo proativo, reenvio, mudança de GraphBundle, site ou
  binding sem evidência operacional.
- Cada cenário encerra no primeiro sinal de duplicidade, persona/contexto
  incorreto, ausência de proof/commit ou confirmação comercial indevida.

## Estado inicial auditado — 2026-09-23

| Item | Evidência segura | Veredito |
| --- | --- | --- |
| Publicação | `df1bbf86-05be-4a5d-a507-256a4b2155c5` | presente |
| Binding | `6386bc58-ade9-44c4-9211-0f59f23ffca5`, ativo | presente |
| Sessão sintética | `d355b182-a940-48f3-8df1-a0cec388db3f` | falhou antes da decisão |
| Inbound canônico | `8eeaf304-3e1c-4c0d-8db6-9e839350dbf4` | `dead_letter` |
| Decisão / proof / commit / outbound | `0 / 0 / ausente / 0` | bloqueado |
| Conexão DeepSeek da Utzig | inexistente | causa prioritária confirmada |

O erro observado é técnico, não de grounding: o transport não recebeu um
resultado canônico do runtime. Não houve duplicidade nem outbound real.

## Configuração aplicada — 2026-09-23

- Uma conexão DeepSeek própria da Utzig foi criada e validada sem expor a
  credencial. A conexão Aurora permaneceu inalterada.
- O modelo legado `deepseek-v4-flash` não está no catálogo atual do provedor;
  a conexão Utzig usa `deepseek-flash`, a variante Flash disponível.
- A conexão e o binding usam `json_object`,
  `conversation_agentic_v1` e `graph_agent_runtime_v3`.
- O binding preserva referências n8n inertes somente para satisfazer uma
  constraint legada do banco. O transport despacha `n8n_agents` diretamente
  para o conversation runtime, não para n8n.
- A persona está liberada para todos por autorização operacional explícita;
  não há allowlist configurada.

## Pré-condições para a correção

1. Criar uma conexão `deepseek` própria da Utzig a partir da credencial Aurora
   somente em memória, sem alterar ou remover a conexão Aurora.
2. Persistir apenas o segredo cifrado e a configuração não secreta: modelo,
   endpoint HTTPS, `structured_output_mode`,
   `pipeline_contract=conversation_agentic_v1` e
   `runtime_version=graph_agent_runtime_v3`.
3. Validar a chave pelo runtime e registrar evento de auditoria sem segredo.
4. Reaplicar o modo agentic oficial da Utzig, verificando CAS do binding e
   alinhamento com o contrato agentic. Não provisionar n8n.

O perfil do WA Validator precisou de uma resposta sintética para o campo
publicado obrigatório `vazamento_oleo`. A alteração está em revisão local e
passou a suíte focada; ela exige uma release compatível apenas do
`conversation-runtime` antes de voltar a executar a jornada sem usar fonte
manual na VPS.

## Candidate e rollback — 2026-09-23

- Imagem candidata: `sha256:57805bfbed50fe37079ac21d1931d6e7fd9f359084bd501d1e38d1510505193f`.
- Preflight e candidate blue/green passaram; somente o
  `conversation-runtime` foi selecionado.
- O canário interno `sdr_qualificacao_carro` criou a sessão
  `dabfbfad-10b1-4dd5-91a7-cad9da9b0b02`, mas o inbound
  `42e9ee75-ce05-467d-b231-d4f52f13bd76` foi terminalizado sem decisão,
  proof, commit ou outbound.
- O workflow efetuou rollback automático para o digest anterior. Gateway,
  control-plane, transport e Tock Fatal permaneceram no slot original.
- Veredito: `technical_pass=false`, `quality_pass=false`. Não repetir deploy
  até que o estágio técnico entre transport e runtime seja diagnosticado e
  corrigido por uma única alteração de serviço.

## Candidato GraphBundle v5 — conhecimento completo aprovado

Classificação: `graph`. Não exige imagem, deploy de serviço, migration, n8n,
pausa de binding, pausa de persona ou reinício de worker.

- Fonte factual: publicação aprovada da Aurora
  `d5c7afd7-24ea-44d6-90e9-8532fd3fc303`, checksum
  `sha256:3f727095819f75836453af2e3bbee42c1138b50a6dc99a59f502b5a1917811ec`.
- Escopo aproveitado: todo FAQ aprovado aplicável aos 12 serviços equivalentes
  da Utzig. FAQs de mera disponibilidade já cobertas foram deduplicadas; uma
  negativa específica de subtipos da Aurora foi excluída por não provar um
  fato da Utzig.
- Acréscimo: 23 FAQs aprovadas e rastreáveis; 11 nodes de Copy receberam
  variações conversacionais de explicação, expectativa e próximo passo.
- Segurança comercial preservada: preço, prazo, agenda, disponibilidade e
  resultado final continuam dependentes de confirmação humana; não há preço
  numérico importado.
- Topologia: cada FAQ possui um pai factual de serviço, uma relação
  `answers_question` e exatamente uma projeção no `Embedded`.
- Dry-run: 23 nodes e 69 edges adicionados, 11 Copys alteradas, zero remoção,
  23 chunks novos, 128 reutilizados e zero erro de validação.
- Checksums aprovados: draft
  `sha256:e806506f07057eeb8127b247515c15621a29258dfae14ee5e6ec5ddb3dbc7a5e`
  e runtime
  `sha256:af58d99ac5f3a9ba9afcf3918c18e22b7791ab71021662f442b9c82385c93a33`.
- Aprovação: operador autorizou o conhecimento completo deste candidato. A
  ativação usou stage + CAS; a publicação v4 permaneceu ativa durante o stage.

### Publicação e validação v5

- Stage concluído na publicação `ab38794a-0580-4bd0-afe7-df6fcb7a0e58`,
  versão 5; durante o stage, a v4 permaneceu ativa.
- Uma sessão interna foi executada contra a publicação staged com uma abertura
  sobre polimento comercial, diferente das perguntas FAQ adicionadas: sessão
  `6dffd957-6e67-417a-97ef-d6db931b0892`, buffer
  `83b55a8e-3867-4fcb-bf83-1678e0b7644b`.
- Resultado conversacional: `technical_pass=false`, `quality_pass=false`, um
  inbound, zero decisão, zero proof, zero commit e zero outbound. O buffer foi
  terminalizado em `dead_letter`; nenhum WhatsApp real foi usado.
- A falha ocorreu antes de recuperar ou avaliar as novas FAQs e, portanto, não
  invalida os gates de estrutura, proveniência, segurança e publicação do
  GraphBundle. Ela continua sendo o débito essencial do runtime descrito
  abaixo.
- Por orientação explícita do operador para publicar o grafo mesmo com a falha
  técnica persistente, a v5 foi ativada por CAS. Auditoria pós-ativação:
  publicação ativa `ab38794a-0580-4bd0-afe7-df6fcb7a0e58`, versão 5, checksum
  `sha256:af58d99ac5f3a9ba9afcf3918c18e22b7791ab71021662f442b9c82385c93a33`.
- Veredito separado: `graph/content pass`; `go-live conversacional não
  aprovado` até um turno interno produzir decisão, proof e commit canônicos.

## Débitos de backend fora do escopo GraphBundle

O último candidate do `conversation-runtime` aguardou 150 segundos e terminou
sem decisão, proof, commit ou outbound. Isso não é lacuna do grafo: o inbound
chegou ao caminho agentic, mas o resultado canônico não voltou ao transport.
O rollback automático preservou o slot anterior.

Esse achado fica no roadmap do runtime, sem nova adaptação do backend para a
Utzig. A correção futura deve ser genérica e limitada ao estágio comprovado por
telemetria (chamada de modelo, validação estruturada, proof ou retorno ao
transport). Observabilidade insuficiente, timeout excessivo e diagnóstico do
estágio terminal são débitos; nenhum deles autoriza hardcode por persona.

Auditoria read-only de 2026-09-23: gateway, control-plane e transport estão no
slot blue e alinhados; claims não estão pausados. O runtime blue continua no
digest restaurado pelo rollback, enquanto o manifesto ainda aponta para o
candidate reprovado. Esse drift deve ser corrigido no pipeline/manifesto antes
de uma futura release do runtime; ele não será “resolvido” por novo deploy no
escopo desta publicação de grafo.

## Causa raiz confirmada e auditoria de corrida — 2026-09-23

A leitura do evento canônico da sessão
`6dffd957-6e67-417a-97ef-d6db931b0892` corrigiu o diagnóstico anterior. O
transport persistiu e reivindicou o inbound
`83b55a8e-3867-4fcb-bf83-1678e0b7644b`; o runtime construiu o contexto e falhou
na primeira chamada ao modelo, no estágio `understanding_model`. A API do
provedor respondeu `HTTP 402`, código `invalid_request_error`, com saldo
insuficiente. Por isso não poderiam existir decisão, proof, commit ou outbound.

Não foi encontrada race condition nesse turno:

- houve uma única tentativa e um único inbound canônico;
- não houve claim concorrente, lock remanescente, replay ou outbound duplicado;
- o buffer foi terminalizado em `dead_letter` e a falha técnica foi auditada;
- a identidade idempotente do inbound, o claim atômico, `SKIP LOCKED`, o claim
  de commit e o commit proof/outbox continuam sendo as proteções genéricas do
  caminho de produção.

O texto “Transport worker did not persist the canonical turn result” era um
sintoma externo impreciso do WA Validator: ele só observava a ausência de
commit e aguardava o limite inteiro, mesmo quando o evento terminal já existia.

### Correlação Aurora / Tock / Utzig

- Utzig e Aurora usam a mesma credencial DeepSeek. A inferência mínima dessa
  credencial retorna `HTTP 402`; a Aurora não possui binding ativo atualmente e
  sua configuração armazenada ainda usa um modelo legado fora do catálogo e
  não declara `structured_output_mode`.
- Tock Fatal possui outra credencial e binding ativo. O modelo e o contrato
  estão atuais, mas uma inferência mínima dessa credencial também retorna
  `HTTP 402` agora.
- Os passes históricos de Aurora/Tock não provam a disponibilidade faturável
  atual. O validador da integração consultava apenas `/models`, que retorna 200
  para essas chaves mesmo quando `/chat/completions` rejeita por falta de saldo.

### Correção genérica preparada

Classificação: duas mudanças `service` independentes, sem migration e sem
mudança de grafo, binding ou regras de persona.

1. `control-plane`: validar cada integração DeepSeek com uma inferência JSON
   mínima usando exatamente modelo, endpoint e modo estruturado configurados;
   `/models` deixa de ser prova suficiente. O default passa a ser o modelo
   atual `deepseek-flash`.
2. `conversation-runtime`: preservar no evento técnico somente status HTTP,
   tipo/código/mensagem do provedor em allowlist, sem chave, headers, prompt ou
   conteúdo da conversa. O WA Validator reconhece esse evento e falha cedo com
   o estágio real, sem esperar 150 segundos e sem atribuir a falha ao transport.

Testes locais focados: 4 casos de integração, 17 casos do turno
agentic/Validator/falha técnica, 34 contratos do transport, 28 contratos de
exactly-once/stale claim e 25 contratos de arquitetura/cópias — todos aprovados.

O código evita novos falsos “connected” e torna a falha acionável, mas não cria
saldo. Para o go-live, ainda é necessário adicionar saldo a uma credencial ou
informar uma credencial faturável, revalidá-la pela prova de inferência e então
executar um único canário no WA Validator interno. O drift do manifesto deve
ser resolvido antes de qualquer release; não fazer novo deploy corretivo sobre
o candidate já revertido.

### Saldo revalidado e primeiro candidate — 2026-09-23

A mesma conexão da Utzig passou novamente pela API de saldo e por uma
inferência JSON real com o modelo `deepseek-flash`. O saldo deixou de ser o
bloqueio. O candidate imutável do runtime foi promovido em blue/green sem pausa
global, mas o canário interno `c5904342-db5e-4d36-b1b8-8c78d5b67a44` reprovou
no quarto inbound e acionou rollback automático para o slot azul anterior.

Os três primeiros turnos do canário produziram exatamente um inbound, uma
decisão, um proof válido, um commit completo e um outbound interno cada. No
quarto, o DeepSeek interpretou a pergunta “Como pedir uma avaliação?”, mas a
resposta foi terminalizada em `reply_validation`, antes de proof e commit. Não
houve duplicidade, lock órfão nem disputa de claim.

Causa raiz: o GraphBundle publicado autoriza a FAQ com
`claim_type=public_information`; o contrato exposto ao modelo passou a mostrar
corretamente essa autorização, porém o schema `conversation_reply_v1` ainda
restringia a saída a uma enumeração que não continha `public_information`. A
saída semanticamente correta era, portanto, inválida para o próprio runtime.

Correção genérica preparada no `conversation-runtime`:

- alinhar `CommercialClaim`, JSON Schema e o validador do grafo para aceitar
  `public_information`;
- manter o proof estrito: a claim somente passa com o mesmo tipo e os IDs de
  evidência autorizados pelo grafo;
- registrar apenas caminho/tipo dos erros de validação, sem prompt, mensagem ou
  segredo, e fazer o WA Validator encerrar cedo quando o evento terminal já
  existe.

Validação local focada: 65 testes aprovados cobrindo schema, duas etapas do
modelo, proof, runtime e WA Validator. O rollback do primeiro candidate foi
confirmado; claims e workers permaneceram ativos e nenhum outro serviço sofreu
cutover.

## Matriz mínima do WA Validator

| Jornada | Resultado seguro exigido |
| --- | --- |
| Pedido de avaliação | intenção e campos extraídos; uma pergunta útil ou handoff |
| Troca explícita de serviço | serviço anterior substituído e campos recalculados |
| Foto sem diagnóstico | nenhuma conclusão técnica inventada; encaminhamento humano |
| Preço ou agenda | nenhum preço, disponibilidade, data ou horário confirmado automaticamente |
| Confirmação final | um handoff humano, com proof e commit atômico |

Para cada sessão, registrar somente sessão/lead mascarado, publicação e
checksum, intenção, serviço, campos extraídos e pendentes, estágio, IDs
técnicos, proof, commit, handoff, latência e os vereditos `technical_pass` e
`quality_pass`.

Classificação do achado: `erro técnico`. Lacunas de conteúdo, grounding ou
tom/pergunta devem ser registradas separadamente; comportamento seguro de
handoff não é erro.

## Critério de promoção

Cada jornada crítica deve ter exatamente um inbound canônico, uma decisão, um
proof válido, um commit concluído e no máximo um outbound interno; ambos os
vereditos precisam ser verdadeiros. Qualquer falha nova mantém o piloto
restrito e interrompe novos envios automáticos.
