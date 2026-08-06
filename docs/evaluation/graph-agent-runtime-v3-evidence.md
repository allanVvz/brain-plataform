# Evidência Graph Agent Runtime v3

Status: `validated_production_2026-08-05`

## Publicações e projeção

| Persona | Publication ID | Versão | Checksum | Compiler | Estado |
|---|---|---:|---|---|---|
| Aurora | `a76f6830-656f-425b-90ee-47e27ce6d6b7` | 4 | `sha256:c0c16b617edb2e6725ecb2e7ea8b5422e1b0f40b8560cc39047a1c6fe8aceaf4` | `graph-compiler-v3.2.1` | ativa |
| VZ Lupas | — | — | — | — | sem publicação v3; `pending_validation` |

Aurora usa Graph JSON v9, checksum
`sha256:1eb291c065cce95264cc3a1b40e5949f5a80509ee50c7495a21711daa238bdac`.
A projeção tem 56 coordenadas, 170 memberships, 9 contratos, 47 entries,
456 chunks e 456 embeddings de dimensão 1536. O modelo efetivo é
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, gerado por
FastEmbed 0.8.0 local, sem vetores sintéticos.

A VZ não possui branch anchor publicável. A lacuna foi registrada sem conteúdo
fictício no item `347a9100-0a14-4630-9581-755d77c1ac41` e no node
`ef06ead7-e7d4-4127-9960-64caa0b72856`, com status `pending_validation`.

## Métricas de retrieval em produção

Dataset: `api/evaluation/graph_rag_v3_retrieval.json`.

| Métrica | Gate | Resultado |
|---|---:|---:|
| Recall@10 | >= 0,90 | 0,9231 |
| Branch contamination crítica | 0 | 0 |
| Next-question accuracy | 100% | 100% |
| Grounded commercial claims | 100% | 100% |
| p50 | informativo | 13,89 ms |
| p95 local | orçamento conversacional | 18,94 ms |
| Context tokens máximo | <= 6.000 | 441 |

Resultado do avaliador: `passed=true`, sem failures. Um caso de disponibilidade
usa evidência dirigida obrigatória do contrato, fora do top-10 semântico; a
claim permaneceu autorizada e grounded.

## Workflow canônico

Aurora e VZ usam a mesma estrutura de 17 nodes, checksum estrutural
`sha256:01a127b0e5a96846175cd0192ebf758a5a72d904eb7c89a2dec40fa2d5d29506`.
Aurora: workflow `k5JWkvpQyb8EB3Vw`, ativo, rendered checksum
`sha256:cad9aeb835ce648f0c60903a6f3e0358ee60428df3171fe63a8356827c4937fd`.
VZ: workflow `H8B0NNonIPhHeQsC`, inativo, rendered checksum
`sha256:e1da106073a1905aaf08ece72642a79faae56a737f829b9e906835b41a056392`.

## Prova E2E viva Aurora ↔ VZ Lupas

Mensagem enviada uma única vez pela VZ para Aurora:
`E2E GraphRAG 20260805-090321-4265: Quero fazer higienização interna no meu veículo.`

| Etapa | Persona | ID persistido | Direção | Timestamp UTC |
|---|---|---:|---|---|
| origem | VZ | 733 | outbound | 2026-08-05 12:03:45.988688 |
| destino | Aurora | 734 | inbound | 2026-08-05 12:03:49.826403 |
| resposta | Aurora | 735 | outbound | 2026-08-05 12:36:48.532768 |
| destino final | VZ | 736 | inbound | 2026-08-05 12:42:44.462281 |

Resposta persistida nos dois lados: `Perfeito, higienização interna! Para
darmos continuidade, qual é o seu nome?`

- correlation inbound Aurora:
  `evolution:c18834ee-566c-410c-9daa-34eff8a3ac56:F5777198BA5CB0697D`;
- inbound canônico: `d802b7df-de3a-406d-968d-0f58d17ccb9b`;
- proof único e válido: `b85902d8-a9ac-4257-a39b-80c3b6ea87fd`;
- ledger `aa36d002-f348-456b-b608-488f70c2a914`, revisão 1, branch
  `aurora-product-interior`, com fato `servico=known` e próxima pergunta
  `faq:qualification:aurora:nome_cliente`;
- outbound único: `79a469e0-ae09-4814-9eac-1b0e34dac1ea`;
- agent log único: `ddaaf734-7c22-46a5-bf56-4082779fb566`, classifier
  `graph_proof_checker_v3`, branch `aurora-product-interior`;
- n8n execution `150`: `success`, 10.636 ms, sem erro;
- contagens persistidas origem/inbound/reply/destino: `1/1/1/1`;
- VZ permaneceu pausada e seu inbound ficou `waiting_human`;
- Aurora só foi retomada após confirmar o transporte pausado;
- nenhuma confirmação indevida de preço, agenda ou disponibilidade;
- status do provider não foi usado como prova de destino.

A primeira tentativa de processar o mesmo inbound revelou conexões inválidas no
template e, depois, truncamento da resposta HTTP pós-commit. O procedimento
parou sem reenviar. As conexões/expressões e o limite de resposta foram
corrigidos; o mesmo inbound foi recuperado pelos guards 098–100, produzindo uma
única prova e um único outbound. O buffer final foi reconciliado para `sent`
sem chamar modelo ou transporte novamente.

Artefatos: `test-artifacts/graph-agent-e2e-live/live-evidence.json`,
`04-vz-source-and-destination-persisted.png` e
`05-aurora-inbound-and-single-reply.png`. O spec final
`dashboard/e2e/graph-agent/aurora-vz-live-proof.spec.ts` foi repetido após o
`final9` e passou em 35,2 s (37,3 s total), ainda com zero novo envio.

## Gates executados

- backend: `471 passed, 2 skipped`;
- `py_compile`: 119 arquivos de `main.py`, routes, services, core e workers;
- dashboard: `next build` concluído, TypeScript e 38 páginas;
- Playwright vivo: 1/1 passou;
- produção: migration 100 no ledger, API saudável e workers ativos;
- imagem ativa: `graphrag-v3-20260805-final9`;
- GHCR API digest:
  `sha256:cc97cc3ea759a0d95352f1914a7970cfd2245e9f8b515270c93e07fa32f51297`;
- GHCR migrate digest:
  `sha256:778c7b3d8433f93b7adaebdb50fbde689f22bdbb629ccb68a3e530254000acea`;
- backup pré-rollout:
  `/var/backups/brain-ai/releases/20260805T091149Z-pre-graphrag-v3-20260805`.

## Limitação deliberada

A VZ continua `human_only`, com workflow inativo e sem publicação GraphRAG v3,
pois faltam branch anchors e conteúdo comercial validado. A ativação exige
curadoria real; este rollout não inventou produto, preço, agenda ou FAQ.

O comando local `docker compose --env-file .env.compose up -d --build` foi
executado, mas o cold rebuild não concluiu porque o Docker Desktop deste host
não confia na CA do proxy ao baixar o modelo do Hugging Face. O override
previsto para pip não cobre o cliente HTTP do Hub; os containers locais
anteriores continuam saudáveis. A mesma imagem foi construída no VPS, migration
100 aplicada e `final9` validado em produção. Não foi desabilitada a validação
TLS no Dockerfile para mascarar a lacuna de infraestrutura local.

## Reteste 2026-08-05 (tarde) — isolamento de persona OK, qualificação completa bloqueada por canal desconectado

Status: `blocked_channel_disconnected` — não é `validated_production` para o fluxo
multi-turno; apenas o smoke test de isolamento passou.

### 1. Isolamento de persona (`aurora-vz-switch.spec.ts`)

Passou (`1 passed`, ~28s) contra `https://brain-plataform-plum.vercel.app`. Login
admin OK, troca Aurora↔VZ Lupas na UI sem vazamento de nodes/checksum entre
grafos, `routing` de ambas as personas OK, zero erro de console, zero mensagem
externa enviada. Evidência local em
`dashboard/test-artifacts/graph-agent-e2e/evidence.json`.

### 2. Bug de teste corrigido (sem impacto em produção)

`aurora-vz-full-qualification.spec.ts` falhava antes de qualquer envio com
`Published Aurora graph lacks a complete field_questions contract`. Causa: o
spec lia `graph?.document_json?.nodes`, mas a resposta real de
`/api-brain/graph-documents/current` traz o grafo em `graph_json` (confirmado
por consulta direta à API e pelo próprio `aurora-vz-switch.spec.ts`, que já usa
`graph_json` corretamente). O grafo publicado da Aurora **está** completo — os
6 `field_questions` obrigatórios (`nome_cliente`, `modelo_veiculo`,
`vehicle_year`, `objective`, `can_visit_in_person`, `condicao`) existem e têm
texto. Corrigido o path no spec para `graph_json.nodes`; nenhuma mensagem foi
enviada nessa correção.

### 3. Turno 1 (nome) tentado — sem entrega à Aurora

Estado pré-turno confirmado por API: lead 29 (Aurora) `ai_paused=false`, última
resposta (mensagem 735, 12:36:48Z) pedindo o nome; lead 41 (VZ) `ai_paused=true`.
Precondições do spec satisfeitas.

O spec enviou a resposta de teste `"Allan"` (valor padrão de `nome_cliente`
usado neste e no reteste anterior — não é o nome real da VZ Lupas, cujo agente
é "Sofia"; é só o dado fictício de cliente). Envio persistiu do lado VZ
(mensagem 738, outbound, `delivered`, 14:47:17Z), mas **nenhum inbound
correspondente jamais chegou à Aurora** (timeout de 150s no
`expect.poll`). Uma tentativa anterior, mensagem "OII" (737, 14:08:35Z), teve o
mesmo destino.

Causa raiz identificada via API (sem SSH, sem acesso a banco): nenhuma
execução de n8n ocorreu para a Aurora desde a execução `#150` (12:36–12:39Z,
a que gerou a pergunta do nome) — nem sucesso nem erro registrado para as
tentativas de 14:08 e 14:47. `GET /api-brain/portal/personas/aurora/channels/whatsapp`
retornou `{"provider":"evolution_baileys","status":"disconnected","last_connection_at":"2026-08-05T06:39:59Z"}`,
enquanto `vz-lupas` está `connected` (`meta_cloud`). Ou seja: a sessão
WhatsApp da Aurora caiu e o Evolution não tem como entregar o webhook de
entrada ao n8n — a mensagem sai da VZ mas não atravessa para a Aurora. O
outbound da VZ está funcional; o problema é exclusivamente na recepção do lado
Aurora.

Uma tentativa de reiniciar a instância
(`POST .../channels/whatsapp/evolution/restart`) foi bloqueada pelo
classificador de segurança do agente por alterar estado de um canal WhatsApp de
produção — requer ação humana (reconectar pelo painel, Aurora → Configurações →
Mensageria) ou autorização explícita antes de eu tentar de novo.

### Estado final e segurança

- Nenhuma mensagem duplicada; nenhum outbound espúrio da Aurora.
- VZ permaneceu pausada durante toda a tentativa.
- Nenhuma confirmação de preço/data/hora ocorreu (o turno nem chegou a gerar
  resposta da Aurora).
- Os 5 problemas do reteste de 05/08 00:xx (handoff por turno,
  `product_slug` oscilando, sinais antigos, política de `vehicle_color`
  desconhecida, informação comercial precoce) **continuam não verificados**
  para este novo runtime — o teste não avançou nenhum turno após o primeiro.

### Próximo passo seguro

1. Reconectar o canal WhatsApp da Aurora (painel ou `restart_instance`
   autorizado explicitamente).
2. Confirmar `status=connected` via
   `GET /api-brain/portal/personas/aurora/channels/whatsapp`.
3. Reexecutar `aurora-vz-full-qualification.spec.ts` a partir do mesmo estado
   pendente (pergunta do nome já feita em 735) — não reenviar a intenção
   inicial, para não duplicar branch.
4. Só então reavaliar os 5 problemas do reteste anterior e, se todos
   resolvidos, atualizar o status para `validated_production` cobrindo o fluxo
   completo — não apenas o primeiro turno.

## Reteste 2026-08-06 — canal reconectado (número novo), entrega segue falhando silenciosamente

Status: `blocked_transport_layer` — o passo 1 do "próximo passo seguro" acima
foi concluído (canal reconectado, `status=connected` confirmado com um
número WhatsApp diferente do reteste anterior), mas o passo 3 continua
bloqueado por um problema diferente do de 05/08: não é mais desconexão de
canal, é entrega silenciosamente perdida com `status=sent`.

### 1. Isolamento de persona (`aurora-vz-switch.spec.ts`)

Repassou (`1 passed`, 24.4s) contra `https://brain-plataform-plum.vercel.app`,
confirmando login, troca Aurora↔VZ Lupas, zero vazamento, zero mensagem
externa enviada.

### 2. Três tentativas consecutivas de entregar a resposta de `modelo_veiculo`, três falhas silenciosas

Estado pré-teste: canal Aurora `evolution_baileys` `status=connected`
(`last_connection_at=2026-08-06T01:53:10Z`, número diferente do usado em
05/08). Lead 29 (Aurora) `ai_paused=false`, última pergunta pendente
`"Qual é o modelo do veículo?"` (`735`→ sequência avançou até mensagem
interna id≈`758`, 2026-08-06T01:08:43Z). Lead 41 (VZ) `ai_paused=true`
confirmado nas três tentativas.

| # | Quando (UTC) | Texto enviado pela VZ | Status VZ | Chegou na Aurora? |
|---|---|---|---|---|
| 1 | 01:09:22 | `Chevrolet Onix` (enviado manualmente, resposta de teste anterior) | `sent` | Não |
| 2 | 02:05:04 | `Toyota Corolla` (via `aurora-vz-full-qualification.spec.ts`, Playwright) | `sent` | Não |
| 3 | 02:31:46 | `Bom dia! É um Toyota Corolla 2020, uso bastante no dia a dia` (frase humana, enviada manualmente como orquestrador) | `sent` | Não |

Nenhuma das três nunca passou de `sent` para `delivered` do lado VZ.
Confirmado via `GET /api-brain/logs/agents?lead_id=29`: a última decisão de
agente para a Aurora é de `2026-08-06T01:08:42Z` (a que gerou a pergunta do
modelo) — nenhuma nova entrada depois disso para nenhuma das três
tentativas. `GET /api-brain/logs/errors?persona_id=<aurora>` retornou vazio.
Ou seja: nenhum erro foi registrado porque a falha acontece antes do nosso
webhook ser sequer chamado — o inbound nunca atravessa da Evolution para o
n8n, apesar do provider ter aceitado o envio (`status=sent`).

Isso descarta duas hipóteses que pareciam plausíveis antes do teste:
- **Não é o texto.** A tentativa 3 usou frase natural e distinta das
  tentativas 1 e 2 (letra, pontuação e conteúdo diferentes) — mesmo
  resultado.
- **Não é o número novo em si.** O canal mostrou `connected` nas três
  tentativas, diferente do reteste de 05/08 onde a UI já acusava
  `disconnected`. A reconexão resolveu o sintoma de conexão, não o de
  entrega.

Confirma exatamente o risco já registrado na seção 4 deste documento: o bug
de correlação `@lid` do Evolution/Baileys, onde `status=sent` com um
`external_message_id` real não é prova de entrega. Não há mitigação de
código disponível neste repositório para esse bug — é uma falha na
biblioteca/protocolo externo.

### 3. Mitigação adicional aplicada nesta sessão (não relacionada à causa raiz)

Independente da causa raiz acima, esta sessão identificou e fechou um gap
real: reenvio manual de texto idêntico após entrega ambígua criava uma
**segunda linha** de outbound (nova `idempotency_key`), sem qualquer
deduplicação — dobrando o volume de envios reais por resposta ambígua
(padrão associado a banimento). Ver seção 6 (`_guard_against_duplicate_content`
em `api/services/whatsapp_outbox.py`, testes em
`tests/test_whatsapp_duplicate_content_guard.py`). Isso não resolve a
não-entrega documentada acima, mas evita que ela vire reenvio duplicado
automático da mesma resposta.

### Estado final e segurança

- VZ permaneceu pausada durante as três tentativas.
- Nenhuma confirmação de preço/data/hora ocorreu (nenhum turno avançou o
  suficiente para chegar perto disso).
- Nenhum duplicado, nenhuma cascata, nenhuma resposta com persona/histórico
  trocado.
- Aurora segue com `missing_fields = ["can_visit_in_person", "condicao",
  "modelo_veiculo", "objective", "vehicle_year"]` — qualificação incompleta,
  travada no mesmo campo desde 05/08.
- Parei novos envios para este par de leads após a 3ª falha consecutiva
  (condição de parada da skill: entrega seguidamente ambígua/perdida).

### Veredito sobre os 5 problemas do reteste de 05/08 00:xx

Continuam **não verificáveis** — o teste não avança turno algum além do
já alcançado em 05/08 (nome capturado), então handoff por turno,
`product_slug` oscilando, sinais antigos, política de `vehicle_color` e
informação comercial precoce seguem sem nova evidência, a favor ou contra,
nesta rodada.

### Correção 2026-08-06 (madrugada): causa raiz real era outra

O veredito acima ("bug `@lid` do Evolution/Baileys") **estava incompleto**.
Checando `GET /api-brain/leads/41` diretamente: o lead da VZ que representa
a Aurora tem `external_contact_id="555182608510"` e
`metadata.identities.meta_wa_id="555182608510"` — o número **antigo** da
Aurora. A Aurora reconectou em `2026-08-06` com um número diferente
(confirmado pelo usuário: `5551992623375`). As três tentativas desta seção
foram todas enviadas pela VZ para `555182608510`, que não é mais a Aurora —
por isso `status=sent` (o provider aceitou o envio) mas nunca virou
`delivered` e a Aurora nunca recebeu nada. Não há evidência de que o bug
`@lid` da seção 4 tenha causado especificamente essas três falhas; ele
continua sendo um risco real e documentado, só não é o que explica este
episódio.

Não existe rota administrativa para editar `external_contact_id`/
`metadata.identities` de um lead existente (só é populado a partir de
webhooks inbound reais, por design — ver `api/routes/evolution_webhook.py`,
`api/routes/whatsapp.py`). Criar um lead novo na VZ com
`telefone=5551992623375` (import CSV, lead `id=46`) e mandar a primeira
mensagem também falhou, mas com um motivo diferente e esperado: `status=failed`
imediato (rejeição HTTP do Graph API da Meta via `response.raise_for_status()`
em `MetaWhatsAppProvider.send_text`), consistente com a política do Meta
Cloud API de não permitir mensagem livre iniciada pela empresa para um
número sem janela de sessão aberta (exige template aprovado ou uma mensagem
inbound do cliente primeiro).

### Próximo passo real

Nenhuma ação de código ou de dashboard destrava isso. É preciso uma ação
física única: alguém com o aparelho do número novo da Aurora
(`5551992623375`) mandar uma mensagem para o WhatsApp Business da VZ Lupas
primeiro (inbound real, cliente iniciando). Isso abre a janela de 24h do
Meta Cloud API, cria/atualiza o lead da VZ com `external_contact_id`
correto automaticamente (mesmo mecanismo que criou o pareamento original
lead 29/41 em 04/08), e a partir daí o fluxo de qualificação por texto
livre volta a funcionar normalmente nos dois sentidos. Trocar o número da
Aurora ou reconectar a instância Evolution não resolve isso — o lado que
precisa de correção é o registro da VZ, e ele só se corrige com um inbound
real.
