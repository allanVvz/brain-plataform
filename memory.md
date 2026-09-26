# Checkpoint 2026-09-26 - Tock e Utzig ativos, auditoria e WA Validator

O usuario pediu para garantir Tock e Utzig funcionando. Auditoria produtiva
read-only `36216395221` confirmou ambas as personas `active=true`, bindings
comerciais `active=true`, `connected`, sem `safety_paused`, claims globais nao
pausados, zero orfaos e zero outbound recente sem proof. O unico backlog real
na auditoria sao 12 `dead_letter` historicos de 14 a 25/09; nenhum foi
reprocessado. O status da Tock inclui `waiting_human` historico, que nao foi
retomado em lote. Nao houve comando de reativacao: os dois agentes ja estavam
ligados. Auditoria de estado adicionada ao workflow no commit `79df0c5`.

WA Validator direto/interno, sem WhatsApp real: Utzig `36209970058`, sessao
`d01aacba-2510-4fe1-b151-143139ee98f6`, Graph v13, cinco turnos de bot,
cinco decisoes/proofs validos/commits/outbounds internos, cinco auditorias
semanticas aprovadas e um handoff; `technical_pass=true`. Tock `36216043754`,
sessao `2a5606de-67bb-461d-9701-0cea74fd66c6`, Graph v38, seis turnos de
bot, seis decisoes/proofs validos/commits/outbounds internos, seis auditorias
semanticas aprovadas e um handoff; `technical_pass=true`, `quality_pass=true`.
As inspecoes foram `36215669745` e `36216381036`.

Dois ensaios previos da Tock ficaram registrados: `36209985187` teve
`technical_pass=true` mas o validador nao reconheceu a frase natural de
passagem a equipe no handoff final; `36215648356` teve quatro turnos tecnicos
e semanticos validos, mas o motorista sintetico nao sabia responder a uma
pergunta consultiva e encerrou a amostra como incompleta. Foram corrigidos
somente o validador e o perfil de cliente sintetico, nos commits `10367f2` e
`bbed44c`; 33 testes focados passaram. Nao houve deploy de runtime, graph ou
transport nesta retomada.

# Brain Platform Memory

## Correção de multi-serviço e perda de memória entre ciclos (2026-08-18)

Dois bugs reportados ao vivo (lead "Allan Rodrigues", produção) na mesma
sessão de teste, corrigidos juntos porque o segundo apareceu investigando o
primeiro.

### Bug 1 — confirmação/header tratavam o 2º serviço como apêndice

Sintoma: ao pedir dois serviços (Chapeação + PPF), a confirmação final saía
como duas cláusulas `serviço:` separadas mais um parágrafo redundante
"Também no seu pedido: ...", e o header do dashboard mostrava `chapeacao`
(slug cru) e `Chapeação · servico` duplicando o próprio título do grupo.

**Causa raiz real (não é o que parecia):** investigação direta em
`conversation_turn_proofs` de produção provou que o modelo e a camada de
galhos (`service_operations`, ativação de galho) já funcionavam
corretamente — os dois serviços eram ativados como galhos concorrentes
válidos, com fatos distintos persistidos (`proof["valid"]=True`,
`service_operation_proof["valid"]=True`). O bug estava inteiramente na
camada de renderização determinística:

1. `_collected_field_facts` (`api/services/graph_agent_runtime_v3.py`)
   iterava cada galho ativo e gerava uma tupla `("Serviço", valor)` por
   galho, porque o campo seletor (`servico`) é declarado propositalmente
   uma vez por galho, dono = o próprio galho. Corrigido com um parâmetro
   opcional `merge_selector` que funde os títulos de todos os galhos ativos
   numa única cláusula, reusando `active_offering_titles` (já existente).
2. `_active_service_summary` (função inteira removida, junto com sua
   chamada em `_decide`) sempre acrescentava o parágrafo "Também no seu
   pedido" quando havia ≥2 ofertas — em *todo* turno pós-qualificação, não
   só na confirmação — e seu guard de duplicata só pegava repetição
   literal, então era sempre redundante depois do fix acima.
3. `_commercial_note_projection` escrevia o fato do seletor com o slug cru
   (`"chapeacao"`) em vez do título humanizado, e a condição que separa
   fato comum de fato por-serviço exigia que **todo** galho ativo
   redeclarasse o mesmo campo antes de tratá-lo como comum — por isso
   `vehicle_color` (persona-scoped) ficou preso só ao galho de Chapeação
   quando o contrato do galho PPF simplesmente não declarava esse campo
   (gap de catálogo, não de código). Corrigido excluindo o fato do seletor
   dos "facts" normais (mantido só como fallback humanizado se for o único
   fato do galho) e simplificando a condição para `owner not in active`.

**Pontos de rigidez avaliados** (4 itens que o usuário pediu para checar
contra este bug específico): dos quatro, dois eram causa raiz real e
relevante e foram corrigidos junto — a validação de `extracted_facts` em
`check()` era escopada a um único contrato de galho por turno (um fato do
2º serviço na mesma mensagem virava `undeclared_field`/
`field_owner_mismatch` mesmo com a ativação do galho aceita), e um erro de
fato isolado em qualquer lugar derrubava `proof["valid"]` pro turno
inteiro, forçando o caminho 100% determinístico mesmo com o resto da
proposta correto. Corrigido com `additional_fields` em `check()` (união
dedupada por `(key, owner_node_id)` de todo galho ativo, não só o focado)
e particionamento de erros em `_decide` (erro de fato de um galho
não-focado não gateia mais o turno; erro do galho focado continua
gateando, sem afrouxar a validação de claims). Os outros dois pontos (um
mecanismo de "terceiro estado"/`needs_confirmation` ainda hardcoded por
`kind` em vez de genérico, e um caminho de fallback residual —
`_invalid_proposal_fallback`, disparado só quando o JSON do modelo falha
schema — que ainda não reabre confirmação pendente por galho) eram reais
mas não causalmente ligados a este bug específico (afetam tipos de campo
hipotéticos futuros / um gatilho raro); ficaram só anotados, não corrigidos
nesta rodada.

### Bug 2 — novo ciclo/appointment perdia o veículo, só lembrava o nome

Sintoma: depois que um atendimento fecha (evento comercial `delivered`/
`service_completed`/`cancelled`) e o cliente escreve de novo, a Aurora abre
uma jornada nova e repergunta modelo/cor do veículo do zero — só o nome
sobrevive.

**Causa raiz:** `carry_over` (o que semeia a jornada nova a partir da
anterior, `_seed_carried_facts`/`_carry_over_field_keys` em
`graph_agent_runtime_v3.py`) era calculado em
`api/scripts/publish_aurora_graph.py` como
`field_key == appointment_policy.get("identity_field")` — só
`nome_cliente`, um único campo literal — mesmo com os campos de veículo já
corretamente marcados `scope: "persona"` (deveriam sobreviver a troca de
galho *dentro* de uma jornada; carry_over decide sobrevivência *entre*
jornadas, os dois mecanismos estavam desconectados). O compilador genérico
em `graph_conversation_contract.py` já usa `scope=="persona"` como default
de `carry_over` para campos de persona-qualification — só o script de
publish da Aurora não seguia essa convenção (já documentada em
`docs/architecture/SDR_JOURNEY_STATE_MACHINE.md`).

**Correção:** `carry_over` passou a ser `scope=="persona" and field_key not
in {"objective", "can_visit_in_person"}` — híbrido escolhido com o usuário:
qualquer campo persona-scoped futuro carrega automaticamente sem precisar
de outra mudança de código, com `objective`/`can_visit_in_person` como
exceções explícitas (intenção daquele atendimento específico, não
identidade estável do cliente/veículo). **Só faz efeito depois de
republicar o grafo em produção** (`api/scripts/publish_aurora_graph.py`
contra o Supabase de produção) — deploy de código sozinho não resolve.
Publicado ainda em 2026-08-18 (publicação v3 → versão 62).

Sem cobertura ainda para a persona de roupas (`vzlupas_catalog.json` não
tem `appointment_policy`/qualificação estruturada) — quando essa persona
ganhar um grafo próprio, precisa do mesmo tratamento de `carry_over` para
o campo de tamanho de roupa.

## Memória durável entre jornadas + silêncio no reparo de dúvida (2026-08-18, rodada 2)

Duas horas depois do deploy da correção acima, dois testes ao vivo novos
(mesmo dia) reproduziram bugs mais fundos que a primeira rodada não cobriu
— o `carry_over` genérico funciona, mas só sobrevive a **um** fechamento
de jornada; e um caminho de "reparo" separado (dúvida do cliente antes de
escolher serviço) não tinha nenhum piso contra silêncio total.

**Memória não sobrevivia a dois fechamentos de jornada seguidos.**
`_seed_carried_facts` só emprestava o fato herdado pro turno atual em
memória — nunca gravava isso como fato real da jornada nova
(`accepted_facts`, a única coisa que `commit_graph_turn_v3` persiste). Ao
vivo, você mesmo fechou duas jornadas em sequência pelo dashboard
(confirmado no `metadata` da própria `conversation_journeys`,
`"source": "dashboard"` — fluxo normal de operação, não bug de
auto-fechamento). Na segunda troca, a busca por `get_latest_conversation_-
journey` (só a jornada imediatamente anterior) não achava nada, porque
essa jornada intermediária nunca teve o nome persistido de verdade.
Corrigido em duas frentes:
1. `graph_agent_runtime_v3.decide()` agora grava o fato herdado em
   `accepted_facts` sempre que `context.journey_id is None` (o turno exato
   em que a jornada nova está sendo criada) — persistência durável a cada
   troca, não só empréstimo de um turno.
2. Nova função `conversation_carry_over_facts_by_lead_v1` (migration 129)
   busca o valor `known` mais recente de cada campo `carry_over` em
   **qualquer** jornada do lead, não só a anterior imediata — jornadas já
   registradas viram a fonte de verdade completa, por pedido explícito do
   usuário ("temos uma tabela compras, jornadas, tudo deve estar
   registrado e deve ser a fonte de verdade"). Precisa da migration 129
   aplicada em produção pra valer (passo `migrate` do deploy, separado do
   deploy de código e da republicação de grafo).

**Aurora ficava muda mesmo já sabendo a resposta certa.** Cliente
perguntou "como funciona o polimento de vidros?" antes de escolher
serviço. O grafo já tinha resolvido a dúvida deterministicamente
(`doubt_resolution: "answered"`, zero chamadas ao modelo) mas só
autorizava aquela FAQ pra `claim_type: "availability"`, não
`service_detail` — mesmo a resposta aprovada sendo uma explicação de como
funciona. Isso caía no bloco de reparo por dúvida/claim em `_decide`
(`graph_agent_runtime_v3.py`), que — só na primeira tentativa — devolvia
`reply_text=None` esperando uma segunda chamada ao modelo orquestrada
fora do Python, pelo n8n. Essa segunda chamada não completou: silêncio
total, mesmo com o texto certo já calculado. Corrigido em três frentes:
1. Conteúdo do grafo: 7 FAQs da família de polimento (`aurora-faq-glass-
   polish` e mais 6 `aurora-faq-polish-*`) ganharam um segundo claim
   `service_detail` além do `availability` já existente — mesmo padrão de
   `aurora-faq-ppf`, que já tinha os dois. Gap era editorial (`claim_type`
   é digitado à mão por FAQ, sem validação de conteúdo), não de código;
   provavelmente existem outros gaps do tipo em FAQs futuras — vale
   auditoria manual quando surgir sintoma parecido.
2. `_decide` (bloco de dúvida/claim, ~linha 4979): já que
   `repair_requirements` é sempre vazio nesse ramo (nunca há nada de fato
   pra buscar), removida a distinção `correction_attempt < 1` vs `>= 1` —
   resolve imediatamente com o texto aprovado do grafo desde a primeira
   tentativa, sem esperar o round-trip do n8n.
3. Rede de segurança em Python (`conversation_runtime._ensure_reply_text_-
   or_log`, chamada no início de `commit()`): se `reply_text` sair vazio e
   `proof["text"]` tiver conteúdo aprovado pelo grafo, usa isso como
   última instância; se nem isso existir, loga erro em vez de completar
   como sucesso silencioso. **Não cobre o workflow n8n** (`Align reply
   with qualification state` continua sem checar `reply_text` vazio) — só
   o lado Python; editar o workflow n8n é um tipo de risco à parte, fica
   como pendência conhecida pra próxima rodada.

## Decisão de produto — Utzig Garage (2026-09-22)

Foi criado um candidato graph-only para `utzig-garage`, sem publicação e sem
estado produtivo. Ele usa UUID determinístico de rascunho e permanece com
`publication_allowed=false` até confirmação do UUID produtivo e de um registry
ou CDN aprovado para derivados web. O bundle contém marca, Alemão como
`founder_specialist`, páginas, localização, audiências públicas, 12 serviços,
políticas de agendamento e assets em allowlist. Não contém preço, horário,
garantia ou promessa de resultado.

As faixas comerciais estimadas são privadas e existem somente em
`product.data.metadata.internal_commercial_value_band`; não entram no site,
RAG nem contratos conversacionais. Audiências no site são links telemetrados,
sem popular silenciosamente o CRM e sem vínculos serviço -> audiência.

Próxima evolução de memória/atribuição:

- tratar o grupo semântico de `/leads/import` como audiência canônica;
- correlacionar futuramente site -> WhatsApp -> lead e escrever
  `lead_audience_memberships` de forma idempotente, somente com identidade e
  consentimento suficientes;
- usar audiência como escopo de listas, disparos e templates Meta aprovados;
- manter uma `audience_of_journey` por jornada e iniciar
  `global_lead_audience` pela maior faixa observada entre jornadas;
- permitir que classificador paralelo por média ponderada reclassifique a
  audiência global, preservando notas comerciais e histórico;
- suportar múltiplas jornadas por campanha e propostas Sofia de vínculos
  serviço -> audiência com aprovação humana;
- direcionar campanhas de maior valor a regiões maiores apenas com fonte e
  aprovação;
- manter Meta Pixel condicionado a consentimento, e distinguir evento anônimo
  entregue de atribuição CRM ainda pendente;
- manter depoimentos, certificações e design system Figma como pendências, não
  como fatos publicados.
