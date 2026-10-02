# Claude Project Contract

## Ordem de precedência (resolve qualquer contradição)

```
1. docs/roadmaps/AGENT_ROADMAP.md   autoridade máxima
2. AGENTS.md                        regras operacionais de produção
3. PROJECT_REQUIREMENTS.md          contrato de produto
4. memory.md                        estado corrente (não é contrato)
5. docs/**                          referência
   docs/archive/**                  NUNCA ler; histórico morto
```

Quando dois arquivos se contradizem, vence o de menor número. Reporte o conflito
em vez de escolher em silêncio.

## Core Rules

- Graph JSON v2 é o contrato canônico publicado do grafo para a Graph UI.
- Acesso a persona deve ser validado em toda leitura e mutação escopada por
  persona.
- API keys de usuário ficam encriptadas no servidor e nunca vão para o browser.
- O output de site público é configurado em `personas.config.public_site` e
  renderizado a partir da memória/grafo da persona via `/api/menu/{persona_slug}`.
- Os formatos de site público são fixos por `public_site_formats`; as chaves
  iniciais são `cardapio`, `landing_page` e `catalogo_roupas`.
- O CTA público de WhatsApp usa `whatsapp_phone` e `whatsapp_message_template`.
  Não usar nem expor o `whatsapp_phone_number_id` do Meta/n8n para esse link.

## Runtime de conversa

- Runtime de conversa: `apps/conversation-runtime` e a unica fonte produtiva.
  Nao copiar implementacoes congeladas de `api/services` ou repositorios
  legados de volta para o microsservico.
- O dashboard/binding escolhe explicitamente `deterministic` ou `n8n_agents`.
  Alteracoes agentic nao podem compor FAQ, pergunta, resumo ou fallback
  deterministico; proof valida evidencia, isolamento, seguranca e exactly-once.
- Toda mudanca conversacional deve executar o teste-canario que prova a
  fronteira entre os dois motores e a preservacao byte a byte da reply agentic.
- A recuperacao especifica de Allan pode adiar o canario WA interno ate depois
  da entrega real se o candidate passar probe sem commit; o release usa
  `canary_persona_slug=utzig-garage` e `canary_flow_id=defer_allan_real_8510`.
- Para a lead de teste Allan da Utzig, WhatsApp final 8510, a recuperacao
  segue a trilha real inbound -> decisao -> proof -> commit -> fila -> entrega
  e confirma recebimento no aparelho antes da bateria WA Validator. O numero
  permanece liberado para testes operacionais sem duplicar outbound.
- `n8n_agents` e somente compatibilidade de armazenamento. O runtime decide e
  prova a conversa; n8n nao e dono da decisao, do proof ou do commit.
- Metadados de pergunta e similaridade editorial produzem correcao ou avisos
  auditaveis, sem veto de resposta util. Gates tecnicos preservam identidade,
  publicacao, isolamento, idempotencia e compromissos comerciais reais.
- Conteudo da mensagem, servico/agendamento da Utzig e horario dos Disparos
  sao politicas distintas. Utzig presta servico e nao tem entrega de produto.
  Sem janela de Disparos, enviar imediatamente; com janela, programar o proximo
  horario permitido e expor espera, previa e acao persistida.
- Perguntas SDR publicadas podem ser obrigatorias, opcionais ou desativadas
  sem deploy do runtime; manter fatos ja coletados no ledger.
- O isolamento de galho e deterministico; o vocabulario do cliente nao. Enum
  fechado e alias sao exemplos de fraseado, nunca o filtro que decide se o fato
  existe - invariante 4 do `docs/roadmaps/AGENT_ROADMAP.md`.

## Rollout de microsservicos

- Producao roda quatro imagens em blue/green: `gateway`, `control-plane`,
  `conversation-runtime`, `transport`. O checkout `/opt/brain-ai` **nao e
  executado** -- serve so aos scripts de `ops/vps`.
- `bash ops/vps/rollout-microservices.sh status` e o ponto de partida: e
  somente-leitura e responde numa tela quais servicos estao atras do manifesto,
  se os claims estao pausados e os comandos exatos na ordem.
- Pausar claims para um agente vivo e **acao de operador**, nunca de agente. O
  script recusa `prepare` sem a pausa em vez de assumi-la.
- `validate-production-release.sh` trata servico e worker com regras
  diferentes: um servico tolera digest pendente e so avisa
  (`ALLOW_PENDING_MICROSERVICE_DIGESTS`); um worker so passa **parado e com
  claims pausados**. E por isso que um rollout de runtime exige parar
  `runtime-conversation` e `runtime-validator` antes do preflight.

## Leitura obrigatória antes de mudanças maiores

- `docs/roadmaps/AGENT_ROADMAP.md`
- `AGENTS.md`
- `PROJECT_REQUIREMENTS.md`
- `memory.md`
- `docs/knowledge-flow.md`

## Não ler

`docs/archive/**` é histórico arquivado em 2026-08-19 porque contradizia o
estado atual. Nunca é fonte de verdade. O bloqueio está em
`.claude/settings.json` (`permissions.deny`).
