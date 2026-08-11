# Handoff — Aurora repete perguntas de qualificação já respondidas

Data de abertura: 2026-08-08
Escopo: `graph_agent_runtime_v3`, `services/conversation_runtime.py`, `services/graph_conversation_contract.py`, `services/deterministic_appointment.py`, WA Validator, persona Aurora (`business_model: "appointment"`).
Status: **bug real, reproduzido 3 vezes, causa raiz ainda não confirmada.** Este documento existe para retomar a investigação em uma sessão nova, com contexto limpo.

## 1. Como chegamos aqui (linha do tempo desta sessão)

A sessão começou como um diagnóstico do WA Validator (ferramenta de teste do dashboard que simula uma conversa de cliente contra o pipeline real, sem WhatsApp de verdade). Ao longo do trabalho, encontramos e corrigimos, em produção, nesta ordem (todos com testes de regressão, todos já deployados em `main`):

1. **UI órfã do WA Validator** — o componente `ValidatorWorkspace` (a tela de gerar/rodar teste) estava importado mas nunca renderizado depois de uma consolidação de configurações; a aba "Validações" mostrava só uma lista de conversas antigas.
2. **`X-Webhook-Token` nunca enviado** ao n8n — a lógica de headers tinha um bug invertido (`headers = {} ` quando o token EXISTIA).
3. **`/internal/conversations/technical-failure` faltando em `PUBLIC_EXACT_PATHS`** (`api/middleware/auth.py`) — o próprio mecanismo de failsafe do workflow n8n da Aurora quebrava com 401 "Sessao obrigatoria", fazendo qualquer erro interno virar um HTTP 200 com corpo vazio em vez de uma falha diagnosticável.
4. **`pipeline_contract` hardcoded errado** no WA Validator (`"conversation_v1"` quando o workflow ativo exige `"conversation_v3"`).
5. **`response_limit=65_536` truncando JSON válido no meio** (bug que eu mesmo introduzi ao corrigir o item 2, encontrado e corrigido na mesma sessão).
6. **Leads de validação nunca reaproveitam a fila real de WhatsApp** — `commit()` agora persiste a resposta do agente na tabela `messages` (para aparecer na tela) mas com status inerte (`"sent"`, fora do conjunto reclamável por `claim_whatsapp_buffer`), nunca disparando um envio real.
7. **Fluxo de teste incompatível com o modelo de negócio da persona** — o seletor de fluxo do WA Validator oferecia fluxos de e-commerce (`compra_simples`, pergunta preço/quantidade de "produto") para a Aurora, que é `business_model: "appointment"` sem nenhum node de produto. Corrigido com `_FLOW_BUSINESS_MODELS` filtrando por persona.
8. **Redesenho da tela** (consolidação de UI, seletor de agente SDR/Closer escopado pelo dropdown global de cliente, nomenclatura de sessões `<fluxo> v<versão do grafo>`).

Cada um desses itens tinha uma causa raiz clara, confirmada com evidência ao vivo (logs de execução do n8n, tracebacks reais, testes automatizados). **Nenhum deles explica o bug deste documento.**

## 2. O bug: campos de qualificação já respondidos são perguntados de novo

Encontrado pela primeira vez numa conversa **real** (não um teste) via WhatsApp, lead "Allan Vigel" (aurora, `lead_ref=50`, já apagado do banco a pedido do usuário antes deste handoff — só existe o registro abaixo). Reproduzido depois, de forma semelhante mas não idêntica, em duas execuções do WA Validator contra o fluxo `sdr_qualificacao_carro`.

### Evidência 1 — conversa real "Allan Vigel" (WhatsApp, `graph_agent_runtime_v3`, deterministic)

Sequência completa de mensagens (extraída via `/api-brain/portal/conversations/50/messages`):

```
user: Ooi
bot:  Oi! Tudo bem? Sou a Aurora, da Aurora Estética Automotiva. Antes de tudo, como você se chama?
user: Allan vigel
bot:  Você consegue trazer o carro aqui na Aurora para uma avaliação rápida, ou prefere seguir tudo por aqui mesmo?
user: Aqui
bot:  Perfeito, Allan! Qual é o modelo do seu carro?
user: Byd dolphin
bot:  Perfeito, Allan! E qual é o ano do seu Byd Dolphin?\n\nE qual é o ano dele?     <- pergunta duplicada na mesma mensagem
user: 2025
bot:  Perfeito, Allan! Qual é a cor do veículo?
user: Cinza
bot:  Perfeito, Allan! O que mais te incomoda no carro hoje?
user: Cheiro, muita sujeira, alguns amassados pontuais
bot:  Entendi, Allan! Cheiro, sujeira e amassados pontuais — anotei tudo. E você pretende vender o carro em breve ou vai continuar com ele e quer investir em cuidado e proteção?
user: Não pretendo vender o carro
bot:  Antes de tudo, como você se chama?              <- JÁ SABIA ("Allan" foi usado em toda resposta anterior)
user: Allan
bot:  Você pretende vender o carro em breve ou vai continuar com ele e quer investir em cuidado e proteção?   <- JÁ RESPONDIDA no turno anterior
user: Não quero vender
```

Estado do lead no momento (via `/api-brain/portal/leads`):

```json
"qualification": {
  "stage": "novo",
  "version": "graph_agent_runtime_v3",
  "stage_source": "graph_contract",
  "missing_fields": ["nome_cliente"],
  "resolved_fields": ["can_visit_in_person", "condicao", "modelo_veiculo", "servico", "vehicle_color", "vehicle_year"]
}
```

`nome_cliente` aparece como pendente mesmo depois de ter sido respondido **duas vezes** ("Allan vigel" e "Allan"), e mesmo tendo sido usado corretamente em toda resposta personalizada entre os dois pedidos. `stage` nunca saiu de `"novo"` apesar de 6 dos 7 campos estarem resolvidos — isso é consequência direta: o contrato do grafo trata `nome_cliente` como eternamente pendente, então o score/estágio nunca avança.

Nota: a suspeita inicial de que `can_visit_in_person: true` era um valor "inventado" sem evidência **estava errada** — o cliente respondeu "Aqui" à pergunta presencial/remoto, evidência real e correta. Não investigar essa parte de novo.

### Evidência 2 — WA Validator, fluxo `sdr_qualificacao_carro`, `n8n_agents`

```
validator: Quero saber sobre a higienização interna do meu carro
validator: Allan
validator: Onix
validator: 2020
bot: Perfeito, Allan! Ano 2020 anotado. E me conta: você pretende vender o carro em breve ou vai continuar com ele e quer investir em cuidado e proteção?
validator: Quero manter o carro e cuidar bem dele
bot: Perfeito, Allan! Cuidar bem do carro é o melhor investimento. Para te atender da melhor forma, você consegue trazer o Onix aqui na Aurora para uma avaliação rápida, ou prefere seguir tudo por aqui mesmo? Você consegue trazer o carro aqui na Aurora para uma avaliação rápida, ou prefere seguir tudo por aqui mesmo?    <- pergunta duplicada na mesma mensagem, de novo
validator: Consigo levar até vocês
bot: O que mais te incomoda no carro hoje?
validator: Os bancos estão meio manchados
bot: Você consegue trazer o carro aqui na Aurora para uma avaliação rápida, ou prefere seguir tudo por aqui mesmo?    <- JÁ RESPONDIDA ("Consigo levar até vocês")
```

### Evidência 3 — segunda execução do WA Validator, mesmo fluxo (via tabela `messages`, já com o fix do item 6 aplicado)

```
assistant: Você consegue trazer o carro aqui na Aurora para uma avaliação rápida, ou prefer...   (turno 1, esperado)
assistant: Você consegue trazer o carro aqui na Aurora para uma avaliação rápida, ou prefer...   (turno 2, repetida)
assistant: Você consegue trazer o carro aqui na Aurora para uma avaliação rápida, ou prefer...   (turno 3, repetida de novo)
...
assistant: O que mais te incomoda no carro hoje?
assistant: Que bom! Então você quer investir em cuidado e proteção. O q...
assistant: Perfeito! A avaliação presencial é rápida e sem custo. O que...
assistant: Entendi, os bancos estão manchados. Qual é o modelo do seu c...   <- "Onix" já tinha sido dado
```

### Padrão observado

Não é um campo específico (`nome_cliente`) — é uma classe de bug. Em execuções diferentes, os campos re-perguntados foram `nome_cliente`, `can_visit_in_person` (presencial/remoto) e `modelo_veiculo`. O ponto em comum: em toda ocorrência, a re-pergunta acontece depois de pelo menos uma resposta bem-sucedida e contextualizada (a IA usa "Allan!"/"Onix" corretamente ANTES de re-perguntar algo sobre esse mesmo contexto).

## 3. Hipóteses de causa raiz (nenhuma confirmada)

### Hipótese A — `ledger_from_state` só copia se a chave ainda não existir

`services/graph_conversation_contract.py`, função `ledger_from_state()` (~linha 408):

```python
def ledger_from_state(state: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    facts = deepcopy(state.get("facts") or {})
    request = state.get("appointment_request")
    ...
    for key, value in request.items():
        if key not in fields or value in (None, "") or key in facts:
            continue
        facts[key] = {...}
```

Se um "fact" vazio/pendente para uma chave já existir em `facts` (por exemplo, criado no primeiro turno do fluxo de qualificação, antes do valor real chegar), essa condição bloqueia a atualização **para sempre**. O valor certo fica preso em `appointment_request` mas nunca sobe pro ledger que decide `missing_fields`. Ainda não confirmado se `ledger_from_state` é de fato chamado a cada turno ou só na inicialização do estado — precisa ler os callers.

### Hipótese B — troca de `active_branch_node_id` reseta os campos obrigatórios

O ledger rastreia `active_branch_node_id` (ex.: `"aurora-product-interior"`) e provavelmente cada branch/produto tem seu próprio conjunto de campos obrigatórios (via `compile_branch_contract`). Se o classificador agentic (LLM) reancorar a conversa para uma branch diferente entre turnos — por exemplo, ao processar "higienização interna" vs. depois inferir "chapeação" a partir de "amassados" — o conjunto de campos exigidos pode mudar, fazendo um campo que já era "known" globalmente aparecer como "missing" para a nova branch.

**Como distinguir as duas hipóteses:** capturar `proof.ledger.facts` e `proof.ledger.active_branch_node_id` (ou equivalente) turno a turno via a execução do n8n (`n8n_client.get_execution(id)`, já usado nesta sessão — ver `run_data["Persist once and enqueue send"]`) e comparar exatamente no turno em que um campo é re-perguntado: (a) se o fact já existia como `"known"` no ledger anterior e simplesmente foi ignorado pela pergunta seguinte → aponta pra um bug de geração de pergunta, não de ledger (hipótese C abaixo); (b) se o fact "known" desaparece do ledger nesse turno → hipótese A; (c) se `active_branch_node_id` muda nesse turno → hipótese B.

### Hipótese C — a pergunta é gerada sem checar o ledger atualizado

Também não descartado: talvez o ledger esteja correto e atualizado, mas a etapa que decide "qual pergunta fazer a seguir" (o LLM em `Build graph grounded agent request` / `Bound conversation model`, ou o helper determinístico `_next_field_question` em `conversation_runtime.py`) esteja lendo um snapshot desatualizado de `missing_fields`, ou o LLM esteja simplesmente reformulando/repetindo uma pergunta anterior por conta própria (sem que o ledger realmente ache o campo pendente) — isso explicaria também a **pergunta duplicada dentro da mesma mensagem** (visto duas vezes, evidências 1 e 2), que parece um sintoma relacionado: o modelo está gerando texto que reafirma uma pergunta que o "trailing question" determinístico (`_ensure_trailing_question`, `conversation_runtime.py` ~linha 408) também adiciona.

**Correlação a verificar primeiro:** a pergunta duplicada-na-mesma-mensagem e a pergunta-repetida-em-turnos-diferentes podem ser a mesma causa raiz vista em dois lugares (o modelo agentic reafirma a pergunta atual do `field_questions` do grafo independente do que já foi resolvido, e o `_ensure_trailing_question` do lado determinístico faz o mesmo).

## 4. Plano de investigação e correção

1. **Reproduzir com instrumentação completa.** Rodar `sdr_qualificacao_carro` contra Aurora via SSH (comando abaixo) e, para cada turno, salvar `n8n_client.get_execution(execution_id)["data"]["resultData"]["runData"]` completo (não só o output de `Persist once and enqueue send`) — precisamos ver o output de `Build graph grounded agent request`, `Bound conversation model` e `Reconcile fields with graph policy` em cada turno pra saber o que o LLM recebeu como "campos pendentes" ANTES de gerar a pergunta.

   ```bash
   ssh -i ~/.ssh/id_ed25519_srv1846215 root@<VPS_HOST>
   cd /opt/brain-ai
   docker compose --env-file .env.compose exec -T -e WA_VALIDATOR_DIRECT_WAIT=1 api python - << 'PYEOF'
   import asyncio, json
   from services import wa_validator_service as wv, n8n_client
   result = wv.generate_script("aurora", "sdr_qualificacao_carro", "Handoff Repro")
   session_id = result["session_id"]
   asyncio.run(wv.run_session_direct(session_id))
   execs = n8n_client.get_executions(limit=10, workflow_id="k5JWkvpQyb8EB3Vw")
   for e in execs[:7]:
       full = n8n_client.get_execution(str(e["id"]))
       run_data = full["data"]["resultData"]["runData"]
       for node in ("Build graph grounded agent request", "Bound conversation model", "Reconcile fields with graph policy", "Persist once and enqueue send"):
           if node in run_data:
               print(f"=== exec {e['id']} :: {node} ===")
               print(json.dumps(run_data[node][0]["data"]["main"], ensure_ascii=False)[:2000])
   PYEOF
   ```

2. **Ler, sem assumir, os arquivos relevantes** antes de mexer em qualquer linha:
   - `services/graph_conversation_contract.py` — `compile_branch_contract`, `ledger_from_state`, `missing_fields`, `apply_extracted_facts`, `check_proposal`, `fallback_question`.
   - `services/conversation_runtime.py` — `_next_field_question`, `_merge_extracted_fields`, `_ensure_trailing_question`, e a chamada que monta o prompt para o modelo agentic (grep por `graph_agent_runtime_v3` e por onde `missing_fields`/`ledger` viram texto de prompt).
   - `api/n8n-workflows/aurora-conversation.json` — os nodes de Code (`Build graph grounded agent request`, `Validate agent response`, `Reconcile fields with graph policy`) para ver exatamente que JS decide o que mandar pro modelo e como reconciliar a saída dele com o ledger.

3. **Escrever um teste de regressão que reproduza exatamente a Evidência 1 ou 2** (mesma sequência de mensagens, mesmo padrão de campos) antes de tocar em qualquer código de produção — sem isso não dá pra saber se uma mudança realmente resolveu o problema ou só mudou o sintoma.

4. **Corrigir a causa raiz confirmada** (não as três ao mesmo tempo — confirmar qual hipótese é real primeiro, então corrigir só ela).

## 5. Plano de validação — isso interfere em produção?

1. **Testes unitários** — o teste de regressão do passo 3 acima, mais qualquer teste existente em `tests/test_graph_conversation_contract.py` e `tests/test_conversation_runtime.py` que já cubra `ledger_from_state`/branch switching (ler antes de assumir que não existe cobertura).
2. **WA Validator ao vivo** — rodar `sdr_qualificacao_carro` contra Aurora do início ao fim (7 mensagens) e confirmar **zero** perguntas repetidas e **zero** perguntas duplicadas-na-mesma-mensagem; conferir que `stage` avança de `novo` para `engajado`/`qualificado` conforme os campos são preenchidos (hoje trava em `novo`).
3. **Impacto em outras personas** — este runtime (`graph_agent_runtime_v3`, `business_model: appointment`) não é exclusivo da Aurora. Rodar:
   ```sql
   select slug from personas p
   join <graph/publication table> ... where business_model = 'appointment';
   ```
   ou equivalente via `conversation_runtime._business_model`, para listar todas as personas afetadas, e repetir a validação do item 2 para cada uma antes de considerar resolvido.
4. **Produção real, sem enviar mensagem nova** — antes de fechar, auditar (só leitura) `leads.metadata.qualification` das personas afetadas em produção para estimar quantos leads reais estão hoje travados em `stage=novo` por causa deste bug (campos resolvidos mas nunca reconhecidos) — isso dá uma medida do impacto real, não só do sintoma reproduzido em teste.
5. **Não repetir o erro desta sessão**: qualquer mudança em `commit()`/`whatsapp_outbox` deve ser revalidada contra `tests/test_whatsapp_exactly_once.py` inteiro — esse arquivo cobre exatamente os invariantes de exactly-once e outbox que já foram tocados hoje.

## 6. O que NÃO fazer

- Não usar WhatsApp real / scraping para testar isso enquanto a causa raiz não estiver identificada — o WA Validator já reproduz o padrão sem custo/risco.
- Não "resolver" simplesmente forçando `missing_fields` a ignorar campos já vistos uma vez sem entender por que o ledger ou a geração de pergunta perdeu o estado — isso pode mascarar um bug de sincronização mais sério (ex.: se for a Hipótese B, silenciar a repetição sem corrigir a branch errada deixaria a IA presa numa branch/produto errado silenciosamente).
- Não tocar em `_ensure_trailing_question` sem primeiro confirmar se ele é realmente a causa da pergunta duplicada-na-mesma-mensagem (Hipótese C) — ele existe para uma razão documentada (linha ~408 de `conversation_runtime.py`, incidente de 2026-08-01 onde o modelo corretamente perguntava algo mas o filtro de preço descartava a resposta).

## 7. Próximo responsável

Comece pelo passo 1 da seção 4 (reprodução instrumentada) — sem ver o output completo dos nodes intermediários do n8n, qualquer correção seria um chute. As três hipóteses da seção 3 são mutuamente exclusivas o suficiente para serem descartadas rapidamente com esses dados antes de escrever qualquer código.

## 8. Atualização de sessão — 2026-08-08 (investigação estática, SSH/DB bloqueados)

**Ambiente desta sessão não teve acesso a SSH para o servidor de produção nem ao projeto Supabase real do brain-plataform** (só leitura de código local + 3 projetos Supabase MCP não relacionados). Não foi possível reproduzir ao vivo (passo 1 da seção 4) nem inspecionar o conteúdo real do grafo publicado da Aurora. O que segue é 100% leitura de código + git log, **não confirmado contra o grafo real**.

### Descoberta: o bug é no runtime `graph_agent_runtime_v3`, não no `graph_conversation_contract.py`/`conversation_runtime.py` "clássico"

`services/conversation_runtime.py::decide()` despacha logo no topo:
```python
if context.runtime_version == graph_agent_runtime_v3.RUNTIME_VERSION:
    return graph_agent_runtime_v3.decide(context, model_observation=model_observation)
```
Como o binding da Aurora usa `graph_agent_runtime_v3` (confirmado pelo próprio campo `qualification.version` no lead), **toda a Hipótese A/B/C da seção 3 (que investiga `graph_conversation_contract.py`) está investigando o motor errado.** Esse arquivo é do motor v2/legado. O motor real é `services/graph_agent_runtime_v3.py` + `services/graph_proof_checker_v3.py` + `services/graph_compiler_v3.py`.

### Causa raiz identificada (alta confiança, não confirmada ao vivo): variante da Hipótese B

Em `graph_proof_checker_v3.py`, a função `_resolved_for_field_owner()` (adicionada no commit `6538461`, "fix: stop v3 qualification state from leaking across branches and engines", autor Allan Ulisses, **2026-08-06 — dois dias antes deste handoff**) exige que `fact.owner_node_id == field.owner_node_id` para considerar um campo resolvido:

```python
def _resolved_for_field_owner(field, fact):
    """...Confirmed live 2026-08-06: field keys are shared across every
    product's field declarations (nome_cliente, modelo_veiculo, servico, ...),
    each with its own owner_node_id..."""
    return field_resolved(field, fact) and bool(fact) and fact.get("owner_node_id") == field.get("owner_node_id")
```

O próprio docstring desse commit **já nomeia `nome_cliente` como um dos campos observados nesse padrão**. O mecanismo, em `graph_compiler_v3.py::_field_declarations()`:
```python
"owner_node_id": str(item.get("owner_node_id") or node["id"]),
```
Se um campo é declarado (redundantemente) dentro do `qualification.fields` de CADA node de branch/serviço (em vez de UMA vez no node persona), cada branch compila esse campo com um `owner_node_id` DIFERENTE (o próprio id da branch), mesmo que a pergunta e a resposta esperada sejam idênticas em todo lugar (ex.: "Como você se chama?"). Como o motor v3 é agentic (o LLM propõe `branch_action` "keep"/"select"/"switch" a cada turno, via matching semântico/embedding em `_candidate_branches`, não por alias literal), qualquer troca de branch — inclusive uma legítima, motivada por uma frase ambígua como "Os bancos estão meio manchados" (evidência 2, mensagem final do script do WA Validator) — reseta a resolução de QUALQUER campo cujo `owner_node_id` não bate com o da nova branch, mesmo campos que nunca deveriam ser branch-específicos.

Isso explica todos os sintomas:
- Campos diferentes reaparecem em execuções diferentes (`nome_cliente`, `can_visit_in_person`, `modelo_veiculo`) — qualquer campo redundantemente declarado por branch é vulnerável, não um campo específico.
- A pergunta reaparece só DEPOIS de pelo menos uma resposta contextualizada correta — o valor estava certo no fato local daquele turno/branch; só passa a ser tratado como "missing" quando o proof-checker recalcula `pending_fields` sob uma branch diferente.
- `stage` nunca sai de `"novo"` — `missing_fields` nunca zera de verdade porque a cada nova pergunta reaberta o ciclo se repete.

**Isso é uma variante nova/não coberta da Hipótese B original** — o mecanismo de troca de branch é real, mas quem troca de branch é o motor v3 (agentic, via embedding), não o `resolve_branch_anchor()` de alias literal do `graph_conversation_contract.py` legado.

### Teste de regressão adicionado (não commitado ainda — ver `tests/test_graph_agent_runtime_v3.py`)

`test_persona_wide_field_duplicated_per_branch_is_wrongly_reasked_on_switch` reproduz o mecanismo via `graph_compiler_v3.compile_graph()` real (duas branches, mesmo `field_key`/mesma pergunta, cada uma declarando o campo localmente) e prova que `pending_fields()` marca o campo como pendente de novo depois de uma troca de branch válida, mesmo com o fato já `"known"`. Toda a suíte local (`pytest tests/`) passa: **473 passed, 36 skipped, 0 failed** — nenhuma outra regressão visível sem infra ao vivo.

### O que NÃO foi possível fazer nesta sessão (bloqueado por acesso)

- SSH para `root@<VPS_HOST>` — bloqueado pelo classificador de auto mode (rede/produção). Não tentado contornar.
- Consulta ao Supabase real do brain-plataform — os 3 projetos Supabase MCP conectados (`allanVvz's Project`, `ai-brain-qa`, `north-portal`) **não são o banco do brain-plataform** (schema de `north-portal` não tem `personas`/`graph_nodes` etc., é outro produto). Não foi possível confirmar se o grafo publicado da Aurora de fato redeclara `nome_cliente`/`can_visit_in_person` por branch em vez de uma vez no node persona — essa é a única confirmação que falta para fechar a causa raiz com certeza.
- Não foi aplicada nenhuma correção de produção. Duas rotas possíveis, nenhuma tentada:
  1. **Conteúdo do grafo** (provável fix real): mover `nome_cliente`/`can_visit_in_person`/outros campos universais para o `qualification.fields` do node persona da Aurora, removendo a redeclaração em cada node de branch/serviço. Isso não exige nenhuma mudança de código — `_field_declarations()` já dá `owner_node_id` consistente (= persona.id) para campos declarados uma vez no persona, porque o persona node está no closure/ancestor path de toda branch.
  2. **Validação no compilador** (`graph_compiler_v3.compile_graph`): detectar em tempo de publicação quando o mesmo `field_key` é declarado em branches-irmãs com `owner_node_id` diferentes E texto de pergunta idêntico, e recusar a publicação — evitaria essa classe de erro de autoria para qualquer persona. Não implementado por não ter como validar contra o conteúdo real da Aurora nem rodar a suíte de validação ao vivo (seção 5 deste documento) antes de mexer em um pipeline compartilhado.

### Próximo passo real

Alguém com acesso SSH/Supabase real precisa: (1) rodar a query da seção 4 passo 1, ou simplesmente inspecionar o Graph JSON publicado da Aurora e conferir se `nome_cliente` (e `can_visit_in_person`) aparecem duplicados no `qualification.fields` de mais de um node de branch/serviço; (2) se confirmado, mover essas declarações para o node persona e republicar; (3) revalidar com o plano da seção 5 (incluindo `tests/test_whatsapp_exactly_once.py` inteiro, já que qualquer republicação de grafo passa por `graph_compiler_v3`).

## 9. Atualização de sessão — 2026-08-08 (SSH liberado, causa raiz confirmada e corrigida em produção)

Usuário autorizou acesso SSH nesta sessão. Confirmação ao vivo (read-only) via `docker compose exec api python`:

- Os 9 nodes `product` (branch anchor) da Aurora — `higienizacao-interna`, `pintura`, `ppf`, `vitrificacao`, `chapeacao`, `polimento-tecnico`, `polimento-de-vidros`, `avaliacao-inicial`, `lavagem-detalhada` — redeclaravam, cada um, os mesmos 7 campos (`nome_cliente`, `objective`, `can_visit_in_person`, `modelo_veiculo`, `vehicle_year`, `condicao`, `vehicle_color`) com `owner_node_id` apontando para a **própria branch**, todos compartilhando o mesmo `question_node_id` (ex.: `faq:qualification:aurora:nome_cliente`, um único node FAQ, filho direto do node persona `aurora-persona`, não de nenhuma branch específica).
- Isso confirma a Hipótese B (seção 8) com certeza: qualquer troca de branch — inclusive uma troca "silenciosa" por falha de proof-check na seleção inicial (ver abaixo) — reabria esses 7 campos como pendentes mesmo já resolvidos, porque `_resolved_for_field_owner()` exige `fact.owner_node_id == field.owner_node_id`.

### Correção aplicada

Para os 9 nodes, `owner_node_id` dos 7 campos acima (exceto `servico`, que permanece corretamente por-branch — é auto-derivado de `active_branch_node_id` a cada turno desde o commit `6538461`) foi trocado para `"aurora-persona"` (stable id do node persona, confirmado via `graph_compiler_v3.compile_graph`). Backup do `metadata` original dos 9 nodes salvo antes do write.

Grafo recompilado e republicado: `graph_compiler_v3.compile_persona_publication("aurora", activate=True)` → **versão 23**, `status=active`, sem erros de compilação. Conferido que a publicação ativa agora tem `owner_node_id="aurora-persona"` uniforme para os 7 campos em todas as 9 branches.

### Validação ao vivo (WA Validator, fluxo `sdr_qualificacao_carro`, 2 execuções reais pós-fix)

**Execução 1** (lead_ref 62): turnos 0-2 falharam no proof-check por um motivo **não relacionado a este fix** (`field_owner_mismatch:servico` — o modelo declarou `branch_anchor_node_id=aurora-product-interior` mas `servico.owner_node_id=aurora-product-wash`, inconsistente; depois `branch_evidence_not_literal`). Sem nenhum turno válido até o turno 3, a branch acabou fixada em `aurora-product-bodywork` (errada — devia ser `aurora-product-interior`, o que o cliente pediu explicitamente na primeira mensagem). `nome_cliente` ficou sem resolver ao final **porque os turnos em que foi extraído corretamente (`owner_node_id=aurora-persona`, já correto) pertenciam a propostas inválidas por outro motivo**, não porque o campo foi reaberto.

**Execução 2** (lead_ref 63): mesmo problema no turno 0 (`field_owner_mismatch:servico`, branch cai em `aurora-product-bodywork`), mas a partir do turno 1 **toda proposta foi válida e nenhum campo já respondido foi perguntado de novo**: `nome_cliente` ("Allan"), `modelo_veiculo` ("Onix"), `vehicle_year` ("2020"), `objective`, `can_visit_in_person`, `condicao`, `servico` — todos resolvidos e nunca reabertos, mesmo com a branch permanecendo "errada" (bodywork) a conversa inteira. `stage` avançou de `novo` para `engajado` (antes travava permanentemente em `novo`). Único campo pendente ao final foi `vehicle_color`, que o script de teste nunca fornece (não é bug — é exigido por `aurora-product-bodywork`, que não seria exigido em `aurora-product-interior`, a branch correta).

**Conclusão:** o bug relatado neste handoff (perguntas de qualificação repetidas mesmo já respondidas) está confirmado corrigido — 0 ocorrências nas duas execuções pós-fix, contra reincidência em toda execução pré-fix.

### Bug novo e distinto encontrado durante a validação (não corrigido, fora do escopo deste handoff)

Nas duas execuções, a seleção inicial da branch falhou (`field_owner_mismatch:servico`) e a conversa acabou presa em `aurora-product-bodywork` (chapeação) em vez de `aurora-product-interior` (higienização interna), apesar do cliente ter pedido "higienização interna" explicitamente na primeira mensagem. Isso não causa mais perguntas repetidas (graças a este fix), mas classifica errado qual serviço o cliente quer — pode gerar campos extras desnecessários (ex. `vehicle_color`) ou uma condução comercial equivocada. Meritório um handoff próprio; não investigado aqui.

### O que NÃO foi verificado

Rodei a suíte de testes local completa (`pytest tests/`) **antes** do fix ao vivo (473 passed, 0 failed) mas não voltei a rodá-la depois — nenhum arquivo de código local mudou nesta sessão além do teste de regressão já commitável (`tests/test_graph_agent_runtime_v3.py`), então não há motivo para regressão local, mas não foi re-confirmado. `tests/test_whatsapp_exactly_once.py` (pedido explicitamente pela seção 5 item 5) também não foi re-rodado pós-fix — o fix não tocou nada de outbox/whatsapp, mas fica como pendência de validação formal. Impacto em outras personas `business_model=appointment` (seção 5 item 3) não foi auditado.
