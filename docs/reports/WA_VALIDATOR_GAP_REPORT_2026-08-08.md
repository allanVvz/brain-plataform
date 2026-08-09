# Relatório de gaps — validações WA Validator / Aurora, 2026-08-08

Baseado em 11 execuções do WA Validator contra a Aurora hoje (leads 61-71,
`graph_agent_runtime_v3`), incluindo as rodadas pós-deploy do fix definitivo
(publicação v26, imagem `9dc8a4b`). Dados extraídos direto de
`conversation_turn_proofs` em produção (leads 66-71 são as execuções mais
recentes e refletem o estado atual do código).

Resumo agregado de erros em todos os turnos de hoje (61 turnos, 12 inválidos):

| erro | ocorrências |
|---|---|
| `cited_chunk_outside_package` | 6 |
| `fact_source_message_mismatch` | 4 |
| `fact_evidence_not_literal` | 4 |
| `next_question_not_for_pending_field` | 4 |
| `field_owner_mismatch` | 3 |
| `cited_chunk_outside_branch` | 3 |
| `branch_evidence_not_literal` | 2 |
| `qualification_completion_mismatch` | 2 |
| `cited_node_outside_package` | 2 |
| `cited_node_outside_branch` | 1 |
| `handoff_not_authorized` | 1 |

## O que já foi confirmado corrigido hoje

- **Perguntas de qualificação reabertas após troca de branch** (bug original
  do handoff) — `field_owner_mismatch` e o padrão de reabertura só aparecem
  nos leads 61-65 (antes do fix definitivo em `publish_aurora_graph.py`,
  publicação v23 revertida). Zero ocorrências nos leads 66-71 (publicação
  v26). `nome_cliente`, `modelo_veiculo`, `vehicle_year`, `condicao`,
  `objective`, `can_visit_in_person` sobrevivem a troca de branch.
- **Seleção de branch errada por owner de `servico` inconsistente** — zero
  `field_owner_mismatch:servico` nos leads 66-71, confirmando o fix em
  `graph_agent_runtime_v3._normalize_servico_owner`.

## Gaps novos identificados (não corrigidos)

### A. Pergunta duplicada na mesma mensagem — o mais frequente hoje

**Evidência** (lead 66, turno 4 — troca de "o carro" por "o Onix" quebra o
match):
```
ai: Perfeito, Marcos! Cuidar bem do carro é o melhor caminho. Você consegue
    trazer o Onix aqui na Aurora para uma avaliação rápida, ou prefere
    seguir tudo por aqui mesmo?

    Você consegue trazer o carro aqui na Aurora para uma avaliação rápida,
    ou prefere seguir tudo por aqui mesmo?
```
Mesmo padrão em leads 62 ("E qual é o ano do seu Byd Dolphin?\n\nE qual é o
ano dele?"), 68 ("E qual é o ano do Civic?\n\nE qual é o ano dele?"), e
outros — presente na maioria das execuções de hoje, inclusive nas 100%
válidas (não gera erro de proof, é um problema cosmético/de qualidade de
resposta, não de dados).

**Causa raiz** — `graph_proof_checker_v3.compose_published_question()`:
```python
if not question or question.casefold() in text.casefold():
    return text
return f"{text}\n\n{question}".strip()
```
Só evita duplicar se o texto canônico da pergunta aparecer **literalmente**
(substring) na resposta do modelo. Qualquer personalização do modelo (trocar
"o carro" por "o Onix", "o Civic") quebra esse match, então a pergunta
canônica é anexada de novo mesmo já tendo sido feita com outras palavras.

**Direção de correção:** trocar o teste de substring literal por uma
comparação mais tolerante (normalizar entidades antes de comparar, ou
comparar por similaridade/embedding), ou reestruturar para nunca depender de
o modelo repetir palavra-por-palavra o texto publicado.

### B. Modelo não reconhece de forma confiável quando a qualificação está completa

**Evidência:**
- Lead 66, turno 6 (último campo, `condicao`, acabou de ser respondido):
  modelo propõe `qualification_complete=False, handoff_requested=True` →
  `qualification_completion_mismatch`.
- Lead 68, turno 7 (último turno do script): modelo propõe
  `qualification_complete=True, handoff_requested=True` com a resposta
  "Perfeito, Ana! Anotei tudo por aqui. A Equipe Aurora vai te chamar..."
  mas `condicao` ainda estava pendente → `qualification_completion_mismatch`
  + `handoff_not_authorized`.

**Impacto:** hoje é inofensivo — o proof-checker rejeita e cai no fallback
(pergunta publicada genérica), então nenhuma informação errada chega ao
cliente. Mas o fallback é pior UX exatamente no momento mais importante da
conversa (o fechamento/handoff), substituindo uma resposta natural por uma
pergunta genérica.

**Direção de correção:** não fixado — precisa investigar se é um problema de
prompt (o modelo não recebe um sinal claro de "este é o último campo
pendente") ou se o modelo está confundindo "o cliente parece satisfeito" com
"todos os campos obrigatórios estão resolvidos".

### C. Troca de serviço no meio da conversa pode falhar silenciosamente e nunca ser retomada

**Evidência** (lead 68, turno 4 — cliente pede explicitamente para trocar de
pintura para chapeação):
```
client: Na verdade, prefiro fazer chapeação em vez de pintura
--turno 4-- valid=False errors=[
  'cited_node_outside_package:aurora-product-bodywork',
  'cited_node_outside_branch:aurora-product-paint',
  'cited_chunk_outside_package:...' (x3),
  'cited_chunk_outside_branch:...' (x3),
]
ai (entregue): Você consegue trazer o carro aqui na Aurora para uma
    avaliação rápida, ou prefere seguir tudo por aqui mesmo?
```
A conversa **nunca mudou de branch** pelo resto do atendimento — continuou
qualificando para "pintura" até o fim, ignorando silenciosamente o pedido
explícito do cliente.

**Causa raiz:** `check()` só marca `repair_required=True` (e tenta de novo
automaticamente) quando **todos** os erros são do tipo `outside_package`.
Aqui a lista mistura `outside_package` com `outside_branch` (que indica um
problema mais sério — o node/chunk citado nem pertence ao fechamento da
nova branch), então `repair_only` fica `False` e a proposta inteira é
rejeitada sem nova tentativa. O pedido de troca do cliente simplesmente
desaparece.

**Impacto:** este é o gap com maior risco de negócio real — um cliente que
muda de ideia sobre qual serviço quer pode acabar sendo qualificado e
agendado para o serviço errado, sem que ninguém perceba durante a conversa.

**Direção de correção:** ou (a) garantir que a recuperação Fase-B para a
branch recém-selecionada aconteça de forma síncrona antes de validar a
proposta de troca, ou (b) permitir reparo também quando os erros são
`outside_branch` no contexto específico de uma troca de branch recém-aceita
(branch_action=switch), já que nesse caso é esperado que o pacote antigo não
cubra a nova branch ainda.

### D. Ritmo de mensagens do WA Validator não reflete um cliente real (mensagens agrupadas)

**Evidência** (leads 69 e 70): várias mensagens do script aparecem em
sequência sem nenhuma resposta do bot intercalada:
```
client: Quero saber sobre chapeação do meu carro
client: Camila
client: Civic
client: 2021
ai: Camila, obrigada! ... Qual é o modelo do seu carro?
```//lead 70 — 4 mensagens do cliente, 1 única resposta do bot
```
Isso acontece porque `run_session_direct()` limita a espera entre passos do
script a no máximo 3s (`wait_s = min(step.get("wait", 10), 3)`,
`wa_validator_service.py`), independente do `wait` configurado no script
(10s). Quando o pipeline (retrieval + modelo + possível reparo) demora mais
que isso, várias mensagens do cliente chegam antes da primeira resposta e
acabam processadas juntas em um único turno.

**Impacto:** o teste deixa de simular "um cliente manda uma mensagem, espera
a resposta, manda a próxima" — que é como o WhatsApp real funciona — e passa
a testar um cenário artificial (múltiplas informações novas de uma vez), o
que pode tanto mascarar quanto inflar certas classes de erro (ex.: parte dos
`field_owner_mismatch`/falhas do turno 0 vistas hoje podem ser efeito desse
agrupamento, não do fluxo real).

**Direção de correção:** o validator deveria esperar a resposta do turno
anterior ser efetivamente entregue (via polling do buffer/mensagem, não um
sleep fixo) antes de enviar o próximo passo do script.

### E. Observação não confirmada — fluxo `saudacao_despedida` sem nenhuma resposta

Lead 71 (`Oi` / `Quais categorias estão disponíveis?` / `Obrigado`) não gerou
nenhuma linha de `ai:` nem ledger de conversa. Não investigado a fundo nesta
sessão — pode ser específico desse fluxo não pertencer ao business model
`appointment` da Aurora, ou uma falha real. Vale conferir separadamente.

## Priorização sugerida

| # | Gap | Risco para o cliente | Esforço estimado |
|---|---|---|---|
| C | Troca de serviço falha silenciosamente | Alto — pode qualificar para o serviço errado sem ninguém perceber | Médio |
| A | Pergunta duplicada na mesma mensagem | Baixo (cosmético, mas visível em quase toda conversa) | Baixo |
| B | `qualification_complete` incorreto no fechamento | Baixo (fallback cobre, mas piora a resposta final) | Médio-alto (precisa investigação) |
| D | Validator agrupa mensagens (ritmo irreal) | Nenhum risco de produção — mas compromete a confiabilidade dos próprios testes | Baixo |
| E | `saudacao_despedida` sem resposta | Desconhecido | Investigação primeiro |
