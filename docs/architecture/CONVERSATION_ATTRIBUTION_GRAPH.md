# Rastreamento operacional de conversas no grafo

## Objetivo

Toda interação deve ser rastreável sem transformar dados de clientes em
conhecimento público. O banco permanece como fonte de verdade e nenhuma tabela
nova é necessária.

## Identidades canônicas

- `leads.id` identifica a pessoa no CRM;
- `lead_audience_memberships` registra os públicos conhecidos ao longo do tempo;
- `messages.id` e o identificador externo do provedor correlacionam cada mensagem;
- `campaign_recipients` é a única evidência para atribuir uma conversa a uma campanha;
- `knowledge_nodes(node_type=conversation)` representa a thread privada da lead;
- `assets` e o node `asset` representam mídia efetivamente armazenada;
- `system_events` recebe eventos anônimos do site e IDs de correlação, sem PII.

## Cadeias permitidas

Com atribuição comprovada:

```text
campaign -> audience -> conversation -> asset -> Gallery
```

Sem campanha, mas com público conhecido:

```text
audience -> conversation -> asset -> Gallery
```

Sem público ainda identificado, a conversa continua como terminal privado
destacado. Ela preserva `lead_id`, referências da mensagem e origem em metadata.
Não se inventa campanha ou audiência. Assim que um membership é confirmado, a
mesma conversa recebe a conexão de audiência; o node não é duplicado.

## Ordem de resolução

1. Resolver persona e binding da mensagem.
2. Correlacionar lead e mensagem canônica.
3. Se houver `campaign_recipient_id`, resolver campanha/revisão/audiência.
4. Sem atribuição de campanha, usar o membership de audiência vigente da lead.
5. Sem audiência comprovada, manter a conversa destacada e marcar a atribuição
   como não resolvida.
6. Ligar mídia recebida por `conversation -> asset (uses_asset)` e
   `asset -> Gallery (gallery_asset)`.

## Pixel Meta e origem do site

Eventos do site usam sessão anônima e node IDs. `origin_ref`, `pixel_event_id`,
UTMs, checksum da publicação e o ID idempotente do evento ficam em
`system_events`/metadata. Quando uma conversa posterior puder ser correlacionada
de forma legítima, esses IDs são copiados para `tracking_refs`; telefone, nome,
texto da mensagem e outros dados pessoais nunca são enviados como parâmetros do
pixel.

## Fronteira pública

Nodes `conversation`, lead, mensagens e mídia recebida são privados:

- `rag_eligible=false`;
- `public_site_eligible=false`;
- nunca recebem `publishes_to` para a Gallery pública;
- nunca recebem `asset_function` ou slot de landing;
- não entram no payload `/api/menu/{persona_slug}`.

O GraphBundle pode conter uma conversa destacada para integridade operacional.
Isso não é autorização de publicação pública: o site projeta somente nodes com
concessão explícita `publishes_to` e assets aprovados no registry.

## Invariantes de auditoria

- uma lead tem uma única conversa por persona/thread canônica;
- um inbound canônico gera no máximo uma decisão e um outbound;
- campanha só é atribuída por `campaign_recipients`;
- troca de audiência preserva o histórico de memberships;
- mídia do cliente nunca entra no RAG ou em slots do site;
- referências de tracking são IDs técnicos, sem PII;
- retries reutilizam a identidade canônica e não criam nodes ou eventos duplicados.
