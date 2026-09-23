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
  ativação deve usar stage + CAS; a publicação v4 permanece ativa diante de
  qualquer falha.

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
