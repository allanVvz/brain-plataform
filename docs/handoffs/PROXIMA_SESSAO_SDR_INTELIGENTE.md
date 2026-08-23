# Handoff — tornar o SDR inteligente, humano e preparado

Para quem continuar. Branch `agent/sofia-vitoria-audit`, worktree
`C:\Repositores\brain-plataform-sofia-vitoria-audit`. Estado técnico e histórico
completo em `SESSAO_2026-08-22_SEMANTIC_RUNTIME_E_ESCOPO.md` — este documento é
sobre **comportamento**, que é onde as duas personas estão ruins.

Ambas rodaram conversa real em produção hoje. As transcrições abaixo são
literais, não hipóteses.

---

## 1. Tock Fatal — o loop, com causa exata

```
cliente: ooie
Vitória: Você procura para uso próprio ou para revender?
cliente: uso proprio
cliente: quais opcoes voce tem?
Vitória: Ainda não tenho uma informação publicada e validada sobre preço,
         estoque, prazo, política ou pedido mínimo. [...]
         Você procura para uso próprio ou para revender?
cliente: uso proprio
Vitória: Perfeito, uso próprio! O que você está procurando para uso próprio?
cliente: quais as opcoes      → mesma deferral + mesma pergunta
cliente: roupas               → "O que você está procurando para uso próprio?"
cliente: alguma roupa         → idem
cliente: vestidos             → idem
cliente: vestido mousse       → idem   (produto REAL, publicado)
cliente: modal                → idem
```

São **dois defeitos independentes**. Os dois estão provados por dados, não por
leitura de código.

### 1a. Deadlock de dependência — a causa do loop

`conversation_turn_proofs` do turno que repete:

```
field_validation: [{
  "field_key": "retail_need",
  "valid": false,
  "errors": ["fact_dependency_unsatisfied:retail_need:purchase_profile"]
}]
missing: ["purchase_profile", "retail_need", "retail_style"]
```

E o fato que ficou gravado para `purchase_profile`:

```json
{"field_key":"purchase_profile","status":"unknown","value":null,
 "reason":"ignored_twice","evidence_span":"","owner_node_id":"audience:tock-retail"}
```

Sequência real (por turno, de `conversation_turn_proofs`):

| turno | resolution_method | status | accepted_facts |
|---|---|---|---|
| 1 | none | none | `[]` |
| 2 | exact_catalog_informative_mention | needs_confirmation | `[]` |
| 3 | **exact_catalog** | **resolved** | `purchase_profile = unknown / ignored_twice` |
| 4+ | none | none | `[]` |

O ramo **foi resolvido** (turno 3, `resolved`) e a Vitória respondeu "Perfeito,
uso próprio!". Mas o fato correspondente foi persistido como
`status=unknown, value=null`, porque a política de repetição
(`question_repetition.max_attempts: 1`) já tinha marcado a pergunta como
"ignorada duas vezes" e desistido dela.

Aí:
- `retail_need.depends_on = ["purchase_profile"]`
- `purchase_profile.accepted_statuses = ["known"]`
- o fato está `unknown` → dependência **nunca** satisfeita
- → toda resposta a `retail_need` é rejeitada, para sempre

O cliente responde certo cinco vezes e o sistema descarta as cinco.

**Onde corrigir:** `_apply_authoritative_branch_resolution`
(`graph_agent_runtime_v3.py:~1601`). Hoje só grava o fato de seleção quando
`resolved_anchor and evidence_span and not (...)`. No turno 3 o
`evidence_span` veio vazio, então o `unknown` anterior sobreviveu. Quando a
resolução de ramo é `resolved`, **a própria resolução é a evidência**: o fato
do campo seletor tem que ser gravado como `known`, sobrescrevendo qualquer
`unknown`/`ignored_twice` anterior. Vale também revisar se `ignored_twice`
deveria mesmo poder marcar como `unknown` um campo que o ramo já respondeu.

### 1b. Zero nós capazes de responder — "não fala os produtos"

```
faq nodes no ramo varejo: 9
eligible_faq (answerable):  0
```

**Nenhum.** A Tock tem 73 produtos, 146 ofertas e 146 copies publicados e
recuperáveis — e **nada que possa responder uma pergunta**.

Regra do compilador (`graph_compiler_v3.py:955-972`): um FAQ só vira "claim
autorizada" se estiver ligado ao `Embedded`, tiver pergunta+resposta, **não**
for `role: qualification_question`, e tiver `claims`. Os 9 FAQs da Tock são
saudação e perguntas de qualificação — todos excluídos.

Consequência arquitetural, e é o ponto mais importante deste documento:
**só nó `faq` responde. `product`, `offer`, `copy` e `product_group` entram no
contexto mas nunca podem sustentar uma resposta.** Por isso "quais opções você
tem?" — que não é pergunta de preço, estoque nem prazo — cai na deferral
genérica. O catálogo existe e é invisível para a conversa.

Duas correções possíveis, provavelmente as duas:
1. **Curto prazo:** gerar FAQs de catálogo a partir dos produtos ("quais
   vestidos vocês têm?", "o que tem em modal?") com `claims` apontando para os
   nós de produto. A Sofia já tem `faq_bulk_generator` para isso.
2. **Estrutural:** deixar nó de catálogo sustentar resposta **descritiva**
   (nome, categoria, disponibilidade de item) sem virar afirmação comercial.
   Listar o que existe não é o mesmo que afirmar preço/estoque — hoje o sistema
   trata os dois como a mesma coisa, e é por isso que ele fica mudo.

---

## 2. Aurora — conhecimento que existe e não é usado

```
cliente: nao sei ainda ele tem riscos como posso arrumar?
Lia:     O atendente vai te passar esse detalhe assim que concluirmos estas
         perguntas.  Qual serviço você procura para o veículo?
cliente: qual servico corrige riscos
Lia:     O atendente vai te passar esse detalhe assim que concluirmos estas
         perguntas.            (e desta vez nem repete a pergunta)
cliente: quero polimento como funciona?
Lia:     O processo inclui lavagem detalhada, descontaminação da pintura e
         isolamento de partes sensíveis, seguido do polimento — que pode ser
         feito para ativar o brilho ou de forma mais profunda para corrigir
         riscos, dependendo do estado do veículo. Você quer seguir com
         Polimento técnico?
cliente: sim
Lia:     Vou encaminhar agora para a Equipe Aurora.
         Dados informados: nome: Allan. Dados não confirmados: serviço.
```

Três coisas, em ordem de gravidade:

**2a. O conhecimento estava lá o tempo todo.** A resposta do quarto turno diz
explicitamente que o polimento "pode ser feito [...] para corrigir riscos" —
exatamente o que o cliente perguntou duas vezes e recebeu deferral. A Aurora só
libera o conhecimento **depois** que o cliente nomeia o serviço. Para um SDR
isso é o inverso do valor: o trabalho é mapear **necessidade → solução**, e ela
exige que o cliente já saiba a solução.

**2b. A confirmação não persistiu.** Ela perguntou "Você quer seguir com
Polimento técnico?", o cliente disse "sim", e o handoff saiu com
`Dados não confirmados: serviço`. O mesmo tipo de defeito que a Tock tem em
1a — resolução acontece na conversa e não vira fato — e merece ser investigado
junto, porque pode ser a mesma raiz.

**2c. Deferral sem avanço.** No segundo turno ela deferiu e não fez pergunta
nenhuma. A matriz do WA Validator chama isso de `acknowledgment sem avanço`.

---

## 3. A diferença essencial entre os dois fluxos

Isso é o que precisa estar claro antes de mexer em qualquer um dos dois.

| | **Tock Fatal** | **Aurora** |
|---|---|---|
| o que o *ramo* significa | **canal comercial** (varejo × atacado) | **serviço** (polimento, higienização) |
| o que a seleção de ramo decide | **qual preço** o cliente vê | **quais perguntas** serão feitas |
| campo seletor | `purchase_profile` | `servico` |
| pipeline | GraphBundle v3, publicação imutável | legado (`appointment_policy`), v73 |
| contrato do modelo | semântico (`interpretation`) | legado (`proposal`) |
| conhecimento | catálogo grande, **0 respondível** | catálogo pequeno, **bem respondível** |
| falha dominante | loop; não fala os produtos | não mapeia necessidade → serviço |

A implicação prática: **na Aurora o ramo é a própria coisa que o cliente está
tentando descobrir.** Ele pergunta "o que corrige riscos?" — a resposta *é* um
ramo, e o sistema se recusa a falar de ramo não selecionado. Na Tock o ramo é
ortogonal ao que ele quer saber (ele quer ver produtos; o ramo só decide o
preço). São dois problemas diferentes com a mesma aparência ("o agente não
responde"), e uma correção única não serve para os dois.

---

## 4. Próximos passos — ordem recomendada

### Fase 1 — Tock volta a funcionar (backend, prioridade máxima)
1. **Quebrar o deadlock (1a).** Ramo resolvido ⇒ fato do seletor `known`.
   É o que destrava o funil inteiro; sem isso nada mais importa.
2. **Deixar o catálogo responder (1b).** Começar por FAQs de catálogo geradas
   pela Sofia; avaliar depois o caminho estrutural de nó descritivo respondível.
3. **Separar pergunta comercial de pergunta descritiva.** "Quais opções vocês
   têm?" nunca deveria cair na deferral de preço/estoque/prazo. Hoje qualquer
   pergunta sem FAQ autorizado recebe o mesmo texto.
4. Rodar a matriz do WA Validator
   (`SEMANTIC_RUNTIME_WA_VALIDATOR_MATRIX.md`) com transporte e IA pausados.

### Fase 2 — Aurora mais agêntica, sem trocar de pipeline
Correções pequenas, no fluxo atual, como pedido:
1. **Responder pergunta diagnóstica antes de exigir o serviço.** Se a pergunta
   é respondível por conhecimento de um ramo não selecionado, responder **e**
   propor o ramo ("isso é o polimento — quer seguir por aí?"). Hoje ela cala.
2. **Confirmação tem que virar fato (2b).**
3. **Nunca deferir sem avançar (2c).**

### Fase 3 — Aurora para o pipeline novo
Só **depois** da Tock validada de ponta a ponta. Ordem: migrar Aurora para
GraphBundle (item 6 do roadmap) → publicar com escopo por ramo → trocar o
template n8n para o contrato semântico → validar → promover. O mecanismo de
promoção já está provado: workflow duplicado em path próprio, binding trocado
em um campo, rollback em um campo (ver seção "Duplicata do n8n" no handoff
principal).

### Movido para a próxima sessão
**`add per-agent embedded` (seção G) não foi feita** e sai do escopo atual.
Contexto que continua válido: hoje **só existe o SDR**; a única diferença
prevista é que o SDR **não** informa preço e o Closer informa. Enquanto houver
um agente só, o card `Embedded` sem `agent_slug` ("todos os agentes") descreve
a realidade — a divisão por agente só passa a valer quando o Closer existir.
Cuidado: a trava de preço em texto livre continua inexistente no v3, e os 146
preços **estão publicados** (hoje a persona defere na prática, mas por política
de deferral, não por guarda).

---

## 5. O problema de fundo: rigidez

O pedido foi "agentes mais inteligentes, menos travados, com espaço para
improviso". As duas transcrições mostram a mesma doença:

- **O backend descarta o que o modelo acertou.** Foi o tema desta sessão inteira
  (matcher literal → camada semântica), e 1a é a mesma doença num lugar novo: o
  ramo resolve, e o fato é gravado como `unknown`.
- **Só um tipo de nó pode falar.** `eligible_faq = 0` significa que a Vitória
  não tem permissão de dizer nada sobre 365 nós de catálogo. Não é falta de
  conhecimento; é falta de autorização.
- **Uma única frase para toda incerteza.** Qualquer coisa sem FAQ autorizado
  recebe o mesmo texto de deferral de preço — inclusive pergunta que não tem
  nada a ver com preço.
- **Campo obrigatório com dependência rígida vira beco sem saída.** Um campo
  `unknown` a montante trava todos os de baixo, sem caminho de recuperação.

A direção certa não é afrouxar a prova — é **ampliar o que pode ser provado**:
mais tipos de nó capazes de sustentar resposta descritiva, deferral específica
por tipo de dúvida, e dependência que se recupera quando a informação chega por
outro caminho (como o ramo).
