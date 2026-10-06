# Checkpoint: integração Brain/WhatsApp com Chatwoot

Atualizado em 2026-10-06. Este arquivo registra o estado de trabalho do clone
isolado `/tmp/brain-chatwoot-bridge`; não contém tokens, senhas ou chaves.

## Estado comprovado

- A VPS correta é `179.197.233.12`, hostname `srv1846215`. O Chatwoot Community
  é `v4.18.0-ce`, com web, worker, PostgreSQL e Redis ativos. O acesso SSH está
  restaurado temporariamente; a chave deve ser removida ao encerrar o trabalho.
- O webhook atual da Meta continua apontando para
  `https://lpapi.vzforeal.com/webhooks/whatsapp`. Não foi modificado.
- O binding identificado para Tock Fatal usa `meta_cloud`, Phone Number ID
  `1274565599076808`, WABA `1846969632685202` e UUID de binding
  `ead9dbcd-8133-4fbf-b73c-248d0c4e9d08`. A persona vinculada tem UUID
  `4acb2739-127e-4143-acf5-f5c3ea1aaa98`.
- A consulta somente leitura atual encontrou 159 leads e 560 mensagens com o
  binding associado, entre 2026-09-14 e 2026-10-05 UTC. A projeção considera
  inbound e outbound enviados/entregues/lidos e exclui ecos Chatwoot e tráfego do
  Validator.
- A implementação usa a API de conta do Chatwoot 4.18 para criar mensagens com
  direção correta. Ela não troca o callback da Meta nem usa um webhook direto
  Meta → Chatwoot.
- A migration aditiva `supabase/migrations/164_chatwoot_api_bridge.sql` mantém
  mapeamentos e operações idempotentes; autorização para essa migration foi
  dada pelo usuário. Ela ainda não foi aplicada.
- Os testes focados passaram: 23 testes em `test_chatwoot_bridge.py` e
  `test_service_surface.py`; `py_compile`, `git diff --check`, validador de
  grants e validador de atomicidade da migration também passaram. Não foi feito
  E2E real com WhatsApp, por segurança e porque a ponte ainda não está ativa.

## Implementado no clone, ainda não publicado

- Endpoint receptor de eventos Chatwoot com validação HMAC e deduplicação.
- Worker do transport para importar o ledger canônico, criar/atribuir contatos e
  conversas, refletir a resposta da Vitória e encaminhar resposta humana pela
  outbox já existente.
- Resposta humana pausa a IA antes do envio. Nota privada `/assumir-ia` pausa;
  nota privada `/retomar-ia` retoma explicitamente. Marcadores impedem ciclos e
  duplicação dos ecos projetados.
- Configuração do worker/env bootstrap, migration, testes e instruções em
  `apps/transport/docs/chatwoot-api-bridge.md`.
- Mensagens com anexos ficam em dead letter nesta primeira versão; o bridge
  cobre mensagens de texto.
- O gateway e o route map receberam a rota específica `/webhooks/chatwoot*`,
  mantendo a rota Meta existente. A projeção envia `external_created_at` para
  preservar a data/hora canônica do histórico.
- O push relay oficial está habilitado (`ENABLE_PUSH_RELAY_SERVER=true`). A
  inbox API `Tock Fatal WhatsApp` (account 1, inbox 1) está associada ao usuário
  1 (`contato@vzforeal.com`, administrador); o callback permanece vazio. O
  usuário `allanulisses@hotmail.com` não consta na instalação atual.
- Os nove campos esperados pelo bridge estão presentes no `.env.compose` modo
  `600`. Uma comparação segura confirmou que account/inbox/agent, identifier e
  segredo de assinatura correspondem à inbox; o token da API retornou HTTP 200.
  `CHATWOOT_BRIDGE_ENABLED=false` e não foi alterado.
- O HTTPS público testado a partir da VPS respondeu HTTP 200 com TLS válido.
  O status operacional informa serviços atualizados, sem rollout e sem pausa
  global. O ledger de produção está na versão 163; a migration aditiva do bridge
  foi renumerada para 164 e ainda não foi aplicada.
- O PR 196 continua aberto. Os builds de gateway e transport passaram, mas o CI
  falha em `Checar backend e anti-hardcode` por um URL literal em
  `.github/workflows/akia-vps-bridge.yml`, arquivo inalterado neste PR e igual à
  base. O check de Preview Vercel também está vermelho. Nenhuma release foi
  iniciada.

## O que falta para uso efetivo no app do iPhone

1. Aplicar migration 164 pelo fluxo de schema aprovado, após backup data-only e
   verificação isolada; depois publicar gateway e transport seletivamente por
   seus fluxos blue/green. A rota Chatwoot foi adicionada sem alterar a rota Meta.
2. Habilitar a ponte no `.env.compose` somente para o release do transport. O
   callback da inbox API fica vazio até o endpoint novo estar pronto.
3. Reconciliar as mensagens elegíveis e executar o canário interno no WA
   Validator. Para provar entrega real ao cliente, aguardar uma conversa iniciada
   pelo proprietário usando seu próprio número de teste; não enviar mensagens
   de teste a terceiros.
4. No iPhone, abrir `https://chat.vzforeal.com` no app oficial, entrar na mesma
   conta, habilitar notificações do app/iOS e confirmar uma notificação real.
   O push relay pode ser validado no servidor; recebimento no aparelho depende
   desse teste do usuário.
5. Ao concluir, remover a chave pública temporária de
   `/root/.ssh/authorized_keys` e apagar a chave privada temporária local se
   não for mais necessária.

## Recuperação

- A Meta continua recebendo no webhook atual durante a implantação; o Chatwoot
  é uma projeção e o envio humano usa a outbox existente.
- Para desligar a ponte, definir `CHATWOOT_BRIDGE_ENABLED=false` no ambiente
  protegido e fazer rollout somente do `transport`. Isso preserva mensagens e
  mapeamentos.
- Não remover objetos da migration em rollback. Se a migration precisar ser
  recuperada, restaurar o backup em ambiente isolado, verificar e reaplicar pelo
  fluxo aprovado antes de recolocar o transport compatível.
- Guia operacional completo: `apps/transport/docs/chatwoot-api-bridge.md`.
