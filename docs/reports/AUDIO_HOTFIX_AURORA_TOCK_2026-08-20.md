# Hotfix de áudio — Aurora e Tock Fatal

Data: 2026-08-20  
Resultado: **safety stop, rollback aplicado, retomada bloqueada**

## Escopo

O hotfix compacta o prompt do template canônico
`api/n8n-workflows/persona-conversation-template.json` sem elevar o limite
duro de 24 mil tokens. Não houve migration, publicação de grafo, mudança de
provedor, uso de WhatsApp real ou limpeza de dados.

PR: `#50`  
Commit do hotfix: `3fffd7fdad61d15e1c8067efca0ea8854e6d8ca4`  
Merge em `main`: `ef439d3b3eaca5b78fded54515a8303c1b43cb95`

## Implementação

- `prompt_layers.persona_policy` passou a referenciar
  `graph_contract.conversation_policy`.
- `common_contract` passou a referenciar o `graph_contract` quando campos,
  perguntas e claims comuns já estão incorporados nele.
- Memória opcional é removida preventivamente até 22 mil tokens na ordem:
  `agent_activity`, `journey_outcomes`, `recent_messages`,
  `historical_facts`.
- Mensagem atual, `profile_facts`, jornada atual, pendências, contratos,
  campos, cards, chunks e evidências não são removidos.
- O marcador `[audio do cliente]: ...` e o `source_message_id` permanecem no
  mesmo payload usado para texto digitado.

## Evidências locais

- Regressão do template: 9 testes passaram. O cenário equivalente à Aurora
  prova o formato antigo acima de 24 mil tokens e o novo em até 22 mil; o
  cenário menor da Tock preserva toda a memória opcional e a transcrição.
- Matriz focada de mídia, Meta/Evolution, transcrição, buffer atômico,
  exactly-once, Graph Runtime v3 e proof: `333 passed`.
- Suíte backend completa: `1023 passed`, 3 warnings preexistentes.
- Sintaxe: 317 arquivos; anti-hardcode: 311 arquivos e 4 workflows;
  `py_compile`: 118 arquivos.
- Dashboard: build Next.js aprovado, `132` testes Vitest, `8` testes seguros
  do WA Validator e `1` corpus Playwright.
- CI oficial do PR e CI de push do merge: aprovados.
- Preview Vercel falhou por configuração externa: ausência de
  `API_INTERNAL_BASE_URL` no ambiente Preview. O build local com
  `API_INTERNAL_BASE_URL=https://api.example.com` e
  `NEXT_PUBLIC_API_BASE_URL=/api-brain` passou.

## Auditoria pré-release

Release instalada antes do hotfix:
`d3ef93f2f16bd8c8b1ed05ef2e61b97b90919174`.

- Aurora Meta: binding `6386bc58…`, ativo e `safety_paused`.
- Tock Meta: binding `680422f3…`, ativo e `safety_paused`.
- Tock Evolution: binding `c18834ee…`, inativo e `safety_paused`.
- Workers de conversa/dispatch não estavam em execução.
- Janela quieta: 0 CAS, 0 buffers críticos, 0 outbound em 15 minutos.
- Migrations 112–130, grants/RLS, checksums, backup e restore: aprovados.
- Disco: 34%; DB em repouso abaixo do limite.

## Deploy e sincronização

Deploy do merge: GitHub Actions run `32428264565`, concluído com sucesso e
`KEEP_WORKERS_PAUSED=true`.

Após o deploy, health/readiness e o validador oficial passaram com identidade
exata de `ef439d3b…`. Antes da sincronização foi salvo snapshot dos dois
workflows em:

`.deploy/workflow-snapshots/ef439d3b3eaca5b78fded54515a8303c1b43cb95/pre-resync.json`

Ressincronização limitada a Aurora e Tock:

| Persona | Workflow | checksum sincronizado | Grafo preservado |
|---|---|---|---|
| Aurora | `k5JWkvpQyb8EB3Vw` | `sha256:2d0e4a74…` | v66, `sha256:f2010106…` |
| Tock Fatal | `WDUxL74OUctQHWwG` | `sha256:2c5a4749…` | v6, `sha256:ad330d48…` |

Existência, ativação, nodes obrigatórios, webhook, referência de credencial,
checksum, binding, runtime e pipeline passaram. Os bindings permaneceram em
`safety_paused`.

## WA Validator direto/interno

Nenhum WhatsApp real foi usado. Os workers continuaram parados e cada
inbound sintético foi processado diretamente pelo workflow n8n, com outbound
apenas persistido.

### Aurora — primeira sessão

Session: `eb66c4c4-f762-46fd-8785-24b6e6541002`, lead sintético `62`.

- Mensagem: `[audio do cliente]: Tenho interesse em polimento de vidros.
  Quantos carros vocês atendem por dia?`
- Resposta graph-backed: informou o limite publicado e pediu confirmação do
  serviço.
- Técnico: 1 inbound, 1 decisão, 1 proof válido, 1 outbound, commit completo,
  prompt estimado em 13.469 tokens.
- Semântico: `quality_pass=false` porque o serviço foi corretamente salvo
  como `needs_confirmation`, enquanto o roteiro esperava seleção definitiva.

### Aurora — sessão limpa com intenção explícita

Session: `e5060327-7fa7-4bf0-a777-6c1546b7b076`, lead sintético `63`.

- Mensagem: `[audio do cliente]: Quero contratar o polimento de vidros e
  tenho uma dúvida: Quantos carros vocês atendem por dia?`
- Resposta graph-backed: respondeu a dúvida antes de pedir confirmação do
  serviço.
- Técnico: 1 inbound, 1 decisão, 1 proof válido, 1 outbound `sent`, commit
  completo, prompt estimado em 13.482 tokens.
- Semântico: `quality_pass=false` pelos critérios
  `all_intended_facts_extracted` e `expected_branch_persisted`.
- Diagnóstico: a política publicada exige confirmação do ramo antes de fixar
  `active_branch_node_id`; a pergunta determinística de confirmação não tem
  `question_node_id`, então o driver atual não consegue mapeá-la a um campo
  publicado.

A Tock não foi iniciada após o primeiro gate semântico falso. Nenhum inbound
foi repetido e nenhuma mensagem ambígua foi reenviada.

## Rollback e estado final

Rollback de imagem: GitHub Actions run `32428992506`, para
`d3ef93f2f16bd8c8b1ed05ef2e61b97b90919174`.

Workflows restaurados do snapshot:

| Persona | checksum restaurado |
|---|---|
| Aurora | `sha256:a8daafb4…` |
| Tock Fatal | `sha256:4565ffbe…` |

Estado final comprovado:

- imagem API em execução: `d3ef93f2…`, healthy;
- Aurora/Tock Meta: `safety_paused`;
- Tock Evolution inativo: preservado e `safety_paused`;
- workers: parados;
- filas `processing`, `awaiting_proof`, `buffered` e `pending_send`: zero;
- workflows antigos ativos e com checksums restaurados;
- grafos Aurora v66 e Tock v6 inalterados;
- nenhum dead letter reprocessado e nenhum dado removido.

### Hard gate remanescente

O workflow oficial de rollback troca a imagem, mas `ops/vps/rollback.sh` não
reinstala o artefato nem atualiza `.deploy/release-source-sha` e
`.deploy/release-directory`. Assim, os marcadores ainda apontam para
`ef439d3b…`, embora a imagem em execução seja `d3ef93f…`.

O validador pós-rollback falha fechado em `release_source_identity`. Por esse
motivo a retomada de bindings e workers não foi executada.

## Critério para novo rollout

1. Corrigir/alinhar o WA Validator para tratar a confirmação graph-driven de
   ramo como estado válido sem exigir `active_branch_node_id` prematuro.
2. Corrigir o contrato de identidade do rollback para que artefato instalado
   e imagem em execução tenham uma identidade auditável única.
3. Repetir auditoria quieta, deploy, ressincronização e as duas sessões.
4. Exigir `technical_pass=true` e `quality_pass=true` em Aurora e Tock antes
   de qualquer retomada.
