# Relatório de compatibilidade — merge, publicação e deploy

Branch `agent/sofia-vitoria-audit` (18 commits), worktree isolada.
**Nada foi deployado, publicado ou ativado.** A v8 segue ativa.

## Resumo executivo

O pedido era: juntar as sessões, publicar o grafo, deployar tudo junto,
pulando testes. Três descobertas mudam o quadro — duas bloqueiam, uma libera:

1. **Pular testes é impossível por construção.** `deploy-production.yml` exige
   CI verde para o SHA alvo (`Require successful CI for this SHA`, linhas 36-52).
   Rodar a suíte não é opcional; é o portão. Rodei: **1308 passando, 2 falhando**
   (as duas pré-existentes, confirmadas no commit base).
2. **`main` divergiu 33 commits, 9+ deles reescrevendo o MESMO arquivo que eu
   reescrevi.** Colisão arquitetural real, detalhada abaixo.
3. **Publicar conhecimento não depende de deploy.** Existe caminho seguro para
   ter a Tock Fatal publicada hoje, sem tocar no backend.

## 1. Merge das duas sessões — feito

`audit/sofia-authoring-and-vitoria-runtime-2026-08-21` (3 commits de Aurora da
outra sessão) mergeado **sem conflito**. O diretório compartilhado
`C:\Repositores\brain-plataform` não foi tocado — o trabalho não commitado da
outra sessão continua intacto lá.

Suíte após o merge: **1308 passando, 2 falhando** (pré-existentes).

## 2. Colisão com `main` — BLOQUEIA o deploy

`main` está **33 commits à frente**. Nove reescrevem
`api/services/graph_agent_runtime_v3.py`, exatamente o arquivo do meu trabalho:

```
ba6d716 fix(runtime): reconcile the last published question
21dc270 fix(runtime): reconcile natural enum answers
fd3a8e5 fix(runtime): align question normalization with proof scope
138356b fix(runtime): preserve multi-service question order
ebf0edb fix(runtime): advance after proven service additions
00d1c76 fix(runtime): reconcile answers across active contracts
5ed8fcb fix(runtime): reconcile facts across active branches
40cdef4 fix(runtime): reconcile graph-owned fact scopes
bd4667f fix(aurora): unblock natural qualification
```

Verificado no código de `main`:
- `_EXPLICIT_CONFIRMATIONS` → **ainda presente (3 ocorrências)**
- `SemanticInterpretation` → **ausente (0 ocorrências)**

Ou seja: **`main` atacou os mesmos problemas por outro caminho** — correções
incrementais sobre o matcher literal, em vez de substituí-lo pela camada
semântica. São duas soluções concorrentes para o mesmo conjunto de defeitos,
desenvolvidas em paralelo.

**O perigo concreto:** ao tentar o merge, os 4 conflitos que apareceram foram
todos em arquivos de Aurora — e `graph_agent_runtime_v3.py`
**auto-mergeou em silêncio**. Textualmente limpo, semanticamente não verificado.
Um auto-merge entre "9 correções incrementais do matcher literal" e "remoção do
matcher literal" é exatamente o tipo de merge que compila, passa em muito teste
e se comporta de forma errada numa conversa real.

Merge abortado. Não vou deployar isso para um agente que fala com cliente real
sem reconciliação deliberada — não é trabalho de "pular teste e subir".

## 3. Publicação de conhecimento — o que dá para fazer HOJE

Descoberta que libera o caminho rápido: **o compilador deployado não conhece
`include_subtree_in_branch`** (verificado no container: 0 ocorrências).

Consequência medida, simulando o compilador deployado sobre a v9 original:

| | nós por ramo | produtos alcançáveis |
|---|---|---|
| v8 (ativa hoje) | 176 | 73 |
| **v9 original publicada hoje** | **16** | **0** |
| v9-compat | 175 | 73 |

Publicar a v9 original agora **apagaria o catálogo inteiro** da Vitória. Foi por
isso que parei antes de publicar.

`sdr-qualification-v9-brand-scope-compat.json` expressa o mesmo escopo com 318
arestas `include_in_branch` por nó — que o compilador deployado entende. Compila
com 175 nós por ramo, 73 produtos, marcas isoladas, zero preço.

**Ressalva honesta sobre o valor da v9:** como a v9 remove os `offer`, as duas
marcas ficam vazias, então o isolamento de marca não produz diferença prática
ainda. A v9 é ganho estrutural, não de comportamento. O ganho real está na v10.

## 4. v10 (preço) — por que ainda não

A v10 publica 146 preços reais. A trava que impede o SDR de afirmar preço
errado **não existe no v3**: o proof-checker valida a lista estruturada
`claims`, mas **não o texto livre da resposta**. O modelo pode escrever
"R$ 650" na prosa com `claims` vazia e nada barra.

O código pronto existe em `graph_conversation_contract.py:587-606,746-763`
(`_MONETARY_FIGURE`, `check_proposal`), com testes em
`tests/test_graph_conversation_contract.py:404-457` — mas é do pipeline legado,
e o v3 não o chama. Portar isso é a seção G, ainda não feita.

Publicar a v10 sem G contradiz diretamente o seu próprio requisito
("sem publicar preço errado").

## 5. Erros possíveis se o deploy for forçado assim

- **Auto-merge silencioso do runtime**: comportamento divergente em conversa
  real, sem sintoma em teste unitário.
- **Orçamento de prompt**: a recuperação unida entre ramos dobra o pacote com 2
  ramos ativos; estouro dispara `prompt_budget_exceeded` e o turno falha.
- **Matriz do WA Validator nunca rodou**: a reescrita semântica nunca foi
  validada contra uma conversa real, nem sintética.
- **Contrato do modelo**: o template novo exige que o DeepSeek devolva o schema
  novo; resposta fora do schema cai em `interpretation_parse_errors` → fallback
  (degrada, não quebra).

## 6. Recomendação

**Caminho rápido e seguro, sem deploy:** publicar `v9-compat` (estrutura e
escopo, zero preço) — funciona com o backend que já está no ar.

**Antes de qualquer deploy de backend:** reconciliar deliberadamente o meu
runtime com os 9 commits de `main`, decidindo o que sobrevive de cada
abordagem, e rodar a matriz do WA Validator com transporte e IA pausados.

**Antes da v10:** seção G (cards Embedded por agente + trava de preço em texto
livre derivada do card do agente).
