# Pausa de workers no rollout de microsserviços

> Isto descreve o fluxo **atual** (`ops/vps/rollout-microservices.sh`), quatro
> imagens blue/green: `gateway`, `control-plane`, `conversation-runtime`,
> `transport`. Os docs `docs/VPS_PRODUCTION_RUNBOOK.md` e
> `docs/runbooks/PRODUCTION_RELEASE_GATES.md` descrevem o fluxo antigo do
> monolito `/opt/brain-ai` (`KEEP_WORKERS_PAUSED`, pausa de tudo de uma vez) e
> **não se aplicam** a este processo.

## A flag de pausa não para nenhum agente sozinha

`claims-paused.json` é um marcador único, global, sem escopo por serviço ou
persona (`ops/vps/pause-worker-claims.sh '<motivo>' --safety-pause`). Mas
**nenhum runtime lê essa flag** — nem `conversation-runtime`, nem
`control-plane`. Ela é só a autorização que `rollout-microservices.sh` exige
antes de aceitar derrubar containers. Setar a flag, por si só, não interrompe
tráfego nenhum.

## Quem de fato para é a lista `SERVICE_WORKERS` do serviço em deploy

Definida em `ops/vps/rollout-microservices.sh`:

| Serviço em deploy      | Workers que param/reiniciam                                          |
|-------------------------|-----------------------------------------------------------------------|
| `conversation-runtime`  | `runtime-conversation`, `runtime-validator` — **é aqui que vivem os agentes de conversa (ex.: Vitória/Tock Fatal, Lia/Aurora)** |
| `control-plane`         | `control-plane-knowledge`, `control-plane-integrations`, `control-plane-validator` |
| `transport`             | `transport-dispatch`, `transport-media`                               |
| `gateway`               | (nenhum)                                                               |

**Regra prática: um deploy de `control-plane` nunca para `runtime-conversation`
nem `runtime-validator`.** Os agentes de WhatsApp continuam respondendo
normalmente durante um rollout que não seja de `conversation-runtime`.

## Ordem completa (de `AGENTS.md`)

1. **operador** autoriza a pausa — `bash ops/vps/pause-worker-claims.sh '<motivo>' --safety-pause`
2. `bash ops/vps/rollout-microservices.sh prepare` (para os workers estritos do serviço)
3. `gh workflow run "Deploy <servico>" --ref main -f manifest_sha=<sha> -f action=deploy`
4. `bash ops/vps/rollout-microservices.sh finish` (sobe os workers, limpa a pausa)
5. `bash ops/vps/rollout-microservices.sh status` de novo para confirmar

O passo 1 é deliberadamente exclusivo de operador humano — o script recusa
`prepare` sem a pausa em vez de assumi-la (`CLAUDE.md`, seção "Rollout de
microsserviços"). Um agente nunca deve executar o passo 1.

## Antes do passo 1, vale checar

Mesmo sabendo que `runtime-conversation` não vai parar num deploy de
`control-plane`, os três workers do control-plane (knowledge/integrations/
validator) podem estar no meio de um claim. Não há um custo alto de esperar
alguns segundos, mas se quiser zero risco: rode `status` primeiro (somente
leitura) e evite iniciar a pausa em cima de uma ingestão de conhecimento ou
sync de integração sabidamente longa em andamento.
