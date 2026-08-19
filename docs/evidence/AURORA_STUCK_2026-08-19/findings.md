# P0 — evidência de produção, 2026-08-19

Coleta read-only via `.runtime/aurora-stuck-evidence.sql` contra a VPS de
produção (`srv1846215.hstgr.cloud`, `/opt/brain-ai`), persona `aurora`,
publicação ativa v66 (`graph-compiler-v3.5.0`).

## Lead 32 — conversa real, ativa (não é sessão de validador)

`evidence_lead32.txt` tem a saída completa. Resumo por hipótese:

1. **Migration 129/130 não aplicada** — descartada. As 4 funções
   (`conversation_carry_over_facts_by_lead_v1`, `graph_turn_context_batch_v3/v4`,
   `activate_graph_publication_v3`) estão presentes em produção.
2. **`reply_text` vazio não coberto pelo n8n** — **falso positivo do script de
   evidência**, não bug de runtime. As 15 últimas linhas mostram
   `final_decision->>'reply_text'` vazio em 100% dos turnos, mas o outbound
   real (`lead_buffer.payload->>'text'` para `outbound_id=8c6a9f6c-...`) tem
   texto completo e correto: *"Então ficou assim: nome: Luiza Camargo;
   serviço: Pintura, Polimento técnico, Polimento de vidros; objetivo:
   continuar com o veículo e cuidar bem dele;"*, `status='read'`. O texto sai
   por `proof_result->>'text'` (a rede de segurança
   `_ensure_reply_text_or_log`), não pela chave `final_decision.reply_text` —
   o script de evidência olha só a segunda chave, por isso sempre marca falso
   positivo. **A pendência real permanece**: essa rede de segurança cobre só
   o lado Python; o node do n8n ainda não checa `reply_text` vazio (já
   registrado em `memory.md`, não é novidade desta rodada).
3. **Orçamento de prompt estourado** — não testada (exigiria logs do n8n via
   outra via de acesso; não crítico dado que os outros sinais já vieram
   negativos).
4. **`publication_changed` invalidando fatos** — descartada. Checksum da
   publicação ativa bate com o do ledger nas duas jornadas do lead
   (`checksum_bate = t`), `invalidated_count = 0` em todos os 15 turnos.
5. **`unknown` absorvendo campo obrigatório** — descartada para este lead.
   Nenhum fato do lead está com `status='unknown'`; todos os 17 fatos
   coletados estão `known`.

**Achado extra, positivo:** a memória sobreviveu ao fechamento de jornada.
Jornada 1 (`299414ad...`) fechou às 17:57:44 com `nome_cliente=Luiza Camargo`,
`modelo_veiculo=Chevette`, `vehicle_year=1989`, `condicao=limpeza pós viagem`
confirmados. Jornada 2 (`258f6511...`) abriu às 17:59:17 por
`semantic_new_demand` e herdou exatamente esses 4 campos no mesmo instante de
criação (carry-over automático), reconfirmando somente `servico` — que é o
comportamento desenhado pelo fix de 2026-08-18/19. `vehicle_color` (o único
campo com `accepted_statuses: ["known","unknown"]`) não apareceu herdado
porque também não existia na jornada 1 — comportamento correto, não bug.

## Leads 29/30 (`ai_paused=true`)

São sessões do WA Validator (`canonical_inbound_id` prefixado
`validator-seed:`), congeladas às 10:11 desta manhã — não são conversas reais
travadas, são sessões de teste pausadas após o uso. Não indicam bug ativo.

## Veredito

Nenhuma das 5 hipóteses do roadmap reproduziu contra tráfego real de hoje.
O sintoma original do P0 (SDR travado, sem memória) não está presente na
única conversa real ativa auditada. Consistente com os fixes já mesclados
(`40d89e6`, `fd9e20b`, `3153c8c`) resolvendo o problema na prática, mesmo sem
o fechamento formal do processo ter acontecido ainda.

**O que NÃO foi coberto por esta rodada** (ficam como pendência, não como
bloqueio do P0):
- Prova formal via `POST /wa-validator/run-direct` (sessão sintética
  controlada) — esta rodada observou tráfego orgânico real, não rodou uma
  sessão nova pelo Validator interno como o processo pede.
- Hipótese 3 (orçamento de prompt) não testada — sem sinal que a motive.
- O node n8n `Align reply with qualification state` continua sem checar
  `reply_text` vazio — pendência antiga, não nova, não bloqueia o P0 porque a
  rede de segurança em Python já cobre o caso observado.

**Recomendação:** tratar o P0 como **desbloqueado na prática** — não há
evidência de bug ativo — mas manter a linha do roadmap como "evidência
coletada, sem sessão de prova formal" até alguém rodar o WA Validator
diretamente, em vez de marcá-la "concluído" sem essa prova.
