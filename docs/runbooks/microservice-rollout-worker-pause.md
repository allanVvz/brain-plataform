# Pausa de workers no rollout de microsserviços

> Isto descreve o fluxo **atual** (`ops/vps/rollout-microservices.sh`), quatro
> imagens blue/green: `gateway`, `control-plane`, `conversation-runtime`,
> `transport`. Os docs `docs/VPS_PRODUCTION_RUNBOOK.md` e
> `docs/runbooks/PRODUCTION_RELEASE_GATES.md` descrevem o fluxo antigo do
> monolito `/opt/brain-ai` (`KEEP_WORKERS_PAUSED`, pausa de tudo de uma vez) e
> **não se aplicam** a este processo.
>
> **Correção de 2026-09-11:** a primeira versão deste doc afirmava que um
> rollout de `control-plane` nunca para `runtime-conversation`/
> `runtime-validator`. **Isso está errado e foi provado errado ao vivo em
> produção.** `finish` recria os workers ativos de **todos os quatro
> serviços de uma vez**, sempre — não só do serviço que acabou de ser
> implantado. Ver seção abaixo.

## A flag de pausa não para nenhum agente sozinha

`claims-paused.json` é um marcador único, global, sem escopo por serviço ou
persona (`ops/vps/pause-worker-claims.sh '<motivo>' --safety-pause`). Nenhum
runtime lê essa flag — nem `conversation-runtime`, nem `control-plane`. Ela é
só a autorização que `rollout-microservices.sh` exige antes de aceitar
derrubar containers. Setar a flag, por si só, não interrompe tráfego nenhum.

## `prepare` é seletivo; `finish` NÃO é

`SERVICE_WORKERS` (definida em `ops/vps/rollout-microservices.sh`) lista os
workers de cada serviço:

| Serviço                 | Workers                                                              |
|--------------------------|-----------------------------------------------------------------------|
| `conversation-runtime`  | `runtime-conversation`, `runtime-validator` — **os agentes de conversa (Vitória/Tock Fatal, Lia/Aurora)** |
| `control-plane`         | `control-plane-knowledge`, `control-plane-integrations`, `control-plane-validator` |
| `transport`             | `transport-dispatch`, `transport-media`                               |
| `gateway`               | (nenhum)                                                               |

- **`prepare`** só para os workers cujo digest já está desatualizado em
  relação ao manifesto **no momento em que roda**. Se você rodar `prepare`
  antes do workflow de deploy sincronizar o manifesto novo pra VPS, ele não
  encontra nada desatualizado ainda e não para nada — mesmo que o deploy que
  vem a seguir seja só de um serviço.
- **`finish`** recria **os workers ativos dos quatro serviços de uma vez**,
  sempre, independente de qual serviço você acabou de implantar. Confirmado
  ao vivo em 2026-09-11: um deploy só de `control-plane` (fix de categorias
  do menu) fez o `finish` recriar `control-plane-knowledge/integrations/
  validator` **e também** `runtime-conversation-green-1` e
  `runtime-validator-green-1` (Tock Fatal/Aurora) e `transport-dispatch/
  media`. Ficaram fora do ar por alguns segundos (pull + recreate + start),
  não horas — mas ficaram.

**Conclusão prática: qualquer rollout de qualquer serviço, ao chegar no
`finish`, reinicia brevemente TODOS os workers, inclusive o runtime de
conversa.** Não existe hoje um jeito de rodar só `finish` do control-plane
sem também reiniciar `runtime-conversation`/`runtime-validator`. Se isso for
inaceitável para uma janela específica, a alternativa é editar o script para
aceitar um argumento de serviço em `finish` (ainda não implementado) — não
assumir que já é seguro.

## Ordem completa (de `AGENTS.md`)

1. **operador** autoriza a pausa — `bash ops/vps/pause-worker-claims.sh '<motivo>' --safety-pause`
2. `bash ops/vps/rollout-microservices.sh prepare`
3. `gh workflow run "Deploy <servico>" --ref main -f manifest_sha=<sha> -f action=deploy`
4. `bash ops/vps/rollout-microservices.sh finish` (reinicia os workers ativos **dos quatro serviços**, limpa a pausa)
5. `bash ops/vps/rollout-microservices.sh status` de novo para confirmar

O passo 1 é deliberadamente exclusivo de operador humano — o script recusa
`prepare` sem a pausa em vez de assumi-la (`CLAUDE.md`, seção "Rollout de
microsserviços"). Um agente nunca deve executar o passo 1. Na prática, o
Claude Code também bloqueia sozinho (classificador de auto-mode, categoria
"Modify Shared Resources"/"Blocked by classifier") a execução direta de
`prepare`/`finish` e de escrita em `release_lifecycle.py` — essas ações
precisam ser rodadas pelo operador mesmo com acesso SSH liberado.

## `pause-worker-claims.sh` exige um release lifecycle já preparado

`pause-worker-claims.sh` é uma casca fina para
`release_lifecycle.py pause-claims`, que falha com `release lifecycle is not
prepared` se `.deploy/lifecycle.json` não existir ou se o release anterior
não estiver com `stage: verified`. Rode primeiro (também só escreve estado,
não mexe em container):

```bash
python3 ops/vps/release_lifecycle.py prepare \
  --candidate-sha <sha completo do commit implantado> \
  --previous-sha <sha completo do manifesto atual> \
  --impact-class compatible
```

Se um release antigo ficou "preso" num stage intermediário (ex.:
`claims_paused`) mesmo já tendo sido retomado de verdade — confirme via
`rollout-microservices.sh status` (`claims: NOT paused`) antes de concluir
que está preso — feche-o com
`release_lifecycle.py advance --stage verified` antes de preparar o novo.

**Cuidado com quebra de linha ao colar comandos longos**: SHAs completos (40
caracteres) fazem a linha passar de ~150 caracteres, e alguns terminais
inserem quebra real de linha ao colar, corrompendo o argumento. Prefira um
heredoc com linhas curtas (`ssh ... bash -s <<'EOF' ... EOF`) para comandos
longos.

## Antes do passo 1, vale checar

Os 7 workers ficam fora do ar por poucos segundos durante o `finish`. Não há
como isolar isso hoje. Se quiser reduzir ainda mais o risco: rode `status`
primeiro (somente leitura) e evite iniciar a pausa em cima de uma ingestão de
conhecimento, sync de integração ou conversa sabidamente longa em andamento.
