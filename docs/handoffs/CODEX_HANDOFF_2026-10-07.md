# Handoff para o Codex — fila, Evolution, Chatwoot (2026-10-07)

Autor: Claude Opus 5.5. Leia antes: [docs/ESTRUTURA.md](../ESTRUTURA.md).
Objetivo do usuário: **operar a Tock Fatal já**, com envio simples (portal, Chatwoot,
agente), uma fila só, Evolution e Meta iguais, publicação de grafo em 1 etapa e
telas mínimas. Tudo que for rígido ou duplicado deve ser removido.

## 1. Verdade de produção (lida em `/health/ready` do gateway)

| Serviço | SHA no ar | Linhagem |
|---|---|---|
| gateway | `7c8fa8f` | `main` |
| control-plane | `e42e7c4` | `feat/utzig-commercial-v15` |
| conversation-runtime | `5ad1678` | `feat/utzig-commercial-v15` |
| transport | `9d9f542` | `main` |

Schema aplicado: 165 (161–163 da linhagem Utzig, 164–165 da `main`). Nunca publique
serviço a partir de uma linhagem só: o PR #226 já une as duas (`90aaa72`).

## 2. PRs e branches

| Item | Estado | Observação |
|---|---|---|
| #224 envio humano imediato, horário = agente, cards de canal | **merged, não publicado** | transport + control-plane |
| #225 manifest só de transport/control-plane | **fechado** | publicaria control-plane errado |
| #226 linhagem única + fila + tela + publicação 1 etapa | **aberto, CI pendente** | merge é humano |
| akia worktree `agent-work/client-composer-bindings-20261006` | commits locais | portal do cliente, gateway CRM (ver §6) |
| `scripts/verification/tock-south-grant-edit.mjs` (akia) | pronto, **não executado** | libera envio do login `tockfatal@south.com` |

## 3. Ordem de execução (cada passo tem critério de pronto)

1. **Merge do #226** (humano). Pronto: CI `check` verde (o Vercel de preview já falhava antes).
2. **Imagens**: o push na `main` gera os quatro digests (`build-monorepo-images`).
   Pronto: artefatos `image-digest-*` do commit de merge.
3. **Manifest**: um PR que só troca `sha`/`digest` dos quatro serviços pelo commit de
   merge; `schema_version` 166; `contracts_checksum` de cada serviço = o do pacote
   (`sha256:b905…`). Validar com `ops/microservices/validate-release-manifest.py`.
4. **Schema 166** por `deploy-schema.yml` (backup data-only e ensaio no restore,
   como o fluxo exige). Pronto: `_compose_migrations` contém `166_…`.
5. **Release** `integrated-release.yml`: `services=gateway,control-plane,conversation-runtime,transport`,
   primeiro `dry-run`, depois `deploy` (aprovação de ambiente). Pronto: `/health/ready`
   mostra o mesmo SHA nos quatro.
6. **Horário da Tock**: o usuário pediu "desligue para a Tock". Rode
   `set-persona-business-hours.yml` (`tock-fatal`, `enabled=false`): dry-run, depois apply.
   Religar = mesmo workflow com `true`, ou a tela Agentes.
7. **Portal do cliente** (akia, §6): publicar gateway CRM + South Pages, rodar o script
   de liberação de envio (dry-run → apply).
8. **Prova ponta a ponta** (número de teste do dono, lead 231, nunca terceiros):
   - portal: enviar texto → chega no WhatsApp na hora (também de madrugada);
   - Chatwoot (iPhone): texto e foto → chegam no WhatsApp; nota `/ligar-agente` religa;
   - agente: cliente escreve fora do horário com conversa parada há >10 min → espera a
     abertura (com o horário ligado); conversa em andamento → responde;
   - fila (Disparos): item pausado mostra *Pausada*; *Retomar* volta para a fila;
   - mídia: foto do cliente chega ao agente descrita (não "OCR ainda não habilitado").

## 4. Regras do usuário (não reabrir)

- Horário vale **só para o agente**; pessoas (portal, Chatwoot) enviam sempre na hora.
- Fora do horário o agente fica desligado para todas as leads (pílula **vermelha** em
  Mensagens); conversa em andamento continua até pausar (10 min).
- Toda mensagem passa pela fila e obedece ao estado de quem envia; pausou, segura;
  a fila segue para a próxima lead.
- Tela da fila: *Pausada, Agendada, Gerar preview, Enviar*. Nada de ids de proof.
- Falha técnica é registrada; **nunca pausa a lead** (SDR sem guardas).
- Grafo é a fonte de verdade; publicar em 1 etapa. Sync com Obsidian é roadmap.
- Chatwoot por persona: não agora. Três perfis de produto: adm AKIA, adm agência, adm cliente.
- Simplicidade: apagar teste rígido (texto de layout, texto de código-fonte, e2e que
  repete vitest); não duplicar código.

## 5. Onde está cada peça nova (brain-plataform)

- `apps/transport/api/services/outbound_gate.py` — regra única de saída + ritmo por canal.
- `apps/transport/api/services/agent_schedule.py` — horário na entrada, carência de 10 min.
- `apps/transport/api/workers/whatsapp_dispatch_worker.py` — usa os dois; varredura de retidas a cada 30 s.
- `apps/control-plane/api/services/business_hours.py` — horário efetivo (bundle + tela).
- `apps/control-plane/api/routes/portal.py` — `/portal/channels`, `/portal/channels/evolution/qr`, `/portal/business-hours`.
- `apps/transport/api/workers/chatwoot_bridge_worker.py` — anexos, Evolution, comandos.
- `dashboard/components/disparos/{ReleaseQueuePanel.tsx,queueSimple.ts}` — tela da fila.
- `.github/workflows/{publish-graphbundle.yml,set-persona-business-hours.yml}`.

## 6. Pendências no akia (portal do cliente)

Branch local `claude/client-composer-bindings-20261006` (worktree compartilhado com
outro agente; ele tem mudanças próprias não commitadas em `dashboard/` e `portal-web/package.json`):
- `MessagesLayout.tsx`: faixa "Somente leitura" quando sem permissão; pílula vermelha
  fora do horário (`lib/agent-hours.ts`, mesma regra do transport).
- `configuracoes/page.tsx`: três cartões (Evolution com QR, Meta, Chatwoot sem segredos).
- `apps/gateway/main.py`: `_crm_contract` libera `/portal/channels`, `/portal/business-hours` (view)
  e `/portal/channels/evolution/qr` (manage).
- `akia/apps/{control-plane,transport}` e `akia/dashboard` são cópias não publicadas:
  não corrija bug lá; corrija no `brain-plataform`.

## 7. Próximas tarefas (por prioridade)

1. **Avisos ao cliente** de fechamento e fora do horário: os textos já estão no grafo
   da Tock (`copy:tock-closing-notice`, `copy:tock-after-hours-notice`). Envio autônomo
   hoje exige prova + preview do operador. Perguntar ao usuário: enviar direto ou pela fila.
2. **Imagens de produto**: Tock tem 64 de 73 produtos sem asset de imagem no bundle
   publicado (v38). Fonte das fotos: pedir ao usuário; inserir via bundle (asset `primary_product_media`
   + arestas `contains` produto→asset e `gallery_asset` asset→gallery) e publicar em 1 etapa.
3. **Janela de 24 h da Meta**: texto livre fora da janela falha (131047); oferecer template no composer.
4. **SQL da fila**: levar retenção/liberação e o "retomar sem janela" para
   `claim_whatsapp_buffer`/`control_message_queue_v2`; reduzir estados a
   *na fila, retida, enviando, enviada, falhou*.
5. **Dois stores de grafo**: o runtime v3 lê `graph_publications`; `appointment-policy`
   e `context_cards` usam o store v2.1 (eventos). Unificar no v3; o editor de grafo da
   linhagem Utzig (`graph_editor_*`, "single-step save") é o caminho.
6. **Telas admin no AKIA**: Disparos e Agentes aparecem como "TELA AINDA NÃO MIGRADA"
   no portal-web; o operador usa o dashboard do Vercel. Decidir: migrar ou apagar a cópia `akia/dashboard`.
7. **Roadmap**: sync Obsidian ⇄ bundle (provado viável: nós publicados têm o formato do
   bundle e arestas mantêm `relation_type`); Chatwoot por persona com segredos no `secret_store`.

## 8. Cuidados

- Não use `git add -A` no checkout compartilhado do akia; commite só seus caminhos.
- Mutação em produção só por workflow com dry-run, depois apply; leitura com `akia-db`.
- O merge do PR e as aprovações de ambiente são do usuário.
