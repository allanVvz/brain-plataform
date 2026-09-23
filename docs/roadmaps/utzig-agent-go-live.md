# Go-live controlado — Utzig Garage

## Escopo e guardrails

- Persona: `utzig-garage`; somente testadores que já estejam na allowlist.
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
