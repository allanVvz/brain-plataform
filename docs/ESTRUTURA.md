# Estrutura — leia antes de mudar fila, agente, canal ou grafo

Atualizado em 2026-10-07. **Tudo vale para todos os agentes de todas as personas**
(nada é exclusivo de uma persona; a persona é sempre parâmetro). Regra geral: **um caminho por coisa**. Não crie fila,
estado, store ou workflow paralelo; simplifique o existente.

## Onde cada coisa roda

| Peça | Repositório | Publicação |
|---|---|---|
| gateway, control-plane, conversation-runtime, transport | `brain-plataform` (`apps/*`) | blue/green por `ops/microservices/release-manifest.json` (digests da `main`) + aprovação de ambiente |
| Telas admin vivas (Agentes, Disparos, Mensagens) | `brain-plataform/dashboard` | Vercel, a cada merge na `main` |
| Portal do cliente e North (`*.pages.dev`), gateway CRM | `akia` (`apps/portal-web`, `apps/gateway`) | Cloudflare Pages por portal |
| Chatwoot (app iPhone) | VPS `chat.vzforeal.com` | ponte no transport (`/webhooks/chatwoot`, worker `chatwoot_bridge`), config por env |

**Uma linhagem**: publique só a partir da `main` (a branch `feat/utzig-commercial-v15`
foi unida a ela no PR #226). O manifest registra o que está no ar; confira em
`/health/ready` do gateway antes de publicar. Próximos passos: [handoff de 2026-10-07](handoffs/CODEX_HANDOFF_2026-10-07.md).

`akia/apps/{control-plane,transport,conversation-runtime}` e `akia/dashboard` são
cópias: não vão para produção. Banco: leitura com `akia-db` (somente leitura);
escrita só por workflow com dry-run/apply.

## Uma fila (todas as mensagens, Meta e Evolution)

`lead_buffer` → dispatcher (`apps/transport/api/workers/whatsapp_dispatch_worker.py`).

- **Na saída**, uma regra (`services/outbound_gate.py`): canal pausado → mensagem
  retida; lead pausada → mensagem do agente retida (ou superada se uma pessoa já
  respondeu); **pessoa nunca é retida**. Retida aparece como *Pausada* e volta
  sozinha quando o motivo some. Ritmo por canal: Meta 20/s, Evolution 1/s
  (`binding.metadata.send_rate_per_second` muda).
- **Horário liga/desliga o agente na entrada** (`services/agent_schedule.py`):
  fora do horário a mensagem do cliente espera a abertura; conversa em andamento
  (resposta há menos de 10 min) continua até pausar. Só campanha, proativa e
  preview carregam janela na saída.
- **Fora da janela de 24h da Meta** (erro 131047): a mensagem livre falha na hora (`failed`,
  "Fora da janela de 24h da Meta — envie um template"), sem retry nem pausa da lead; o motivo
  aparece na conversa e no Chatwoot. Reabrir exige template (o envio não é automático).
- Mídia: Meta e Evolution enviam imagem, áudio, vídeo e documento. Imagem recebida
  é lida por visão (`OPENAI_API_KEY` no transport); áudio é transcrito (Whisper).
- Chatwoot: resposta do atendente (texto e anexos) entra na mesma fila; nota
  privada `/ligar-agente` e `/desligar-agente`.
- **Tela**: quatro palavras — *Pausada, Agendada, Gerar preview, Enviar*. Mapeamento
  único: `dashboard/components/disparos/queueSimple.ts`.

## Horário do agente

Padrão no bundle (`persona.data.conversation_policy.business_hours`). Ajuste salvo
na tela Agentes vai para `personas.config.business_hours` (PATCH de routing).
Fonte única: `apps/control-plane/api/services/business_hours.py`.

## Grafo

- O agente lê **`graph_publications`** (GraphBundle v3). O store v2.1 (eventos,
  `graph_document_publisher`, `appointment-policy`, `context_cards`) não chega ao
  agente v3: não crie funcionalidade nele.
- Publicar = **1 dispatch** de `publish-graphbundle.yml` (bundle + persona); os
  checksums vêm do próprio plano. Bundles do repositório podem estar atrás do
  publicado: parta sempre do publicado.

## Como trabalhar

- Teste comportamento, pouco. Não teste colunas, ids ou textos de layout; não crie
  e2e que repita o vitest.
- Produção: leitura → PR → merge (humano) → release do manifest → aprovação.
- Tela do cliente: só o que o cliente entende.

## Roadmap (não fazer agora)

- Sync Obsidian ⇄ bundle: puxar o publicado para notas, editar, gerar bundle e
  publicar em 1 dispatch.
- Unificar o store v2.1 no v3; levar retenção/liberação da fila para SQL e reduzir
  estados a *na fila, retida, enviando, enviada, falhou*.
- Chatwoot para todas as personas (hoje uma binding por env); avisos automáticos de
  fechamento/fora do horário (textos já existem no grafo da Tock) pela fila.
- Imagens de produto em todas as personas de catálogo (a Tock tem 64 de 73 sem imagem).
