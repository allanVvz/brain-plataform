# Revisao SDR livre — Tock — 2026-10-02

Escopo: revisao do commit Claude `f59cd370ba68225b9efae967c6a52574c5d8400b`
e seus ancestrais, comparados com `main` `04a8b810`. Implementacao propria na
branch `fix/tock-sdr-free`; nenhum commit Utzig incorporado. Worktree movido
com verificacao integral para
`/home/allan/src/agent-work/tock-sdr-free-20261002/tock-brain-prod`.

## Achados do trabalho Claude

1. **P1 — protecao comercial removida sem substituto.** `e6eaafc` remove os dois
   guards do `conversation_runtime.commit`: confirmacao de preco/agenda e
   politica publicada de preco reservado ao humano. `graph_proof_checker_v3`
   declara explicitamente depender desses guards, e seu filtro de erros
   bloqueantes reconhece somente `publication_`. O prompt e claims declaradas
   pelo proprio modelo nao substituem autorizacao real. Nao promover essa
   remocao sem uma verificacao equivalente e caminho de recuperacao seguro.
2. **P2 — normalizador continua reinterpretando o modelo por texto.**
   `ae511333` transforma `matched_keys` de regex/similaridade na autoridade
   sobre `asked_field_key`, mesmo quando o modelo aponta outro campo elegivel.
   Uma coincidencia lexical pode consumir a tentativa errada no ledger.
3. **P2 — confirmacao perde sua identidade.** No mesmo normalizador, uma
   pergunta de `question_kind=confirmation`, sem campo, cai no ramo que a
   converte em `consultative`. A pontuacao tambem funciona como classificador
   principal; um pedido natural sem ponto de interrogacao perde seu campo.
4. **P2 — erro tecnico permanece sem recuperacao equivalente.** `e6eaafc`
   troca o handoff apos falhas consecutivas por `pass` e fixa
   `handoff_required=False`; retirar a pausa nao gera uma resposta nem cria
   encaminhamento humano visivel. Deve existir retry limitado ou recuperacao
   explicita, com resultado e candidato persistidos, sem looping nem duplicata.
5. **Acertos a preservar.** Avisos editoriais separados do proof tecnico,
   candidato em diagnosticos, configuracao de perguntas no grafo, fatos
   preservados e envio imediato quando nao existe janela operacional.

## Implementado nesta branch

- Um unico reconciliador de metadados, usado antes da decisao e na finalizacao.
  Nao usa regex, listas de palavras comerciais nem score de similaridade.
- Campo publicado elegivel informado pelo modelo tem prioridade. Texto livre
  e pedidos sem `?` continuam validos. Um exemplo autoral exato serve somente
  para recuperar um ponteiro ausente, nunca para vetar o texto ou sobrepor um
  campo explicitamente informado.
- Campo invalido, coletado ou ambiguo entre donos perde somente o ponteiro.
  Nao consome tentativa `ask_once`; resposta permanece inalterada. Confirmacao
  mantem seu tipo; handoff encerra coleta sem consumir pergunta.
- A segunda passagem usa os metadados originais. Nao pode recuperar por texto
  um ponteiro descartado na primeira passagem. Esse contraexemplo foi encontrado
  na revisao independente e coberto por regressao.
- Repeticao e divergencias editoriais viram avisos. Proof guarda texto candidato,
  original, normalizado e correcoes. Falha tecnica posterior registra candidato.
- Versao de contrato erronea declarada pelo modelo e corrigida a partir do schema
  suportado, com aviso; publicacao/checksum reais continuam sujeitos a verificacao.
- Guards comerciais existentes e caminho canonico de commit/outbox preservados.

## Caminho mais inteligente proposto

`inbound -> contexto publicado e memoria -> interpretacao semantica -> resposta
-> reconciliacao advisory -> proof tecnico -> commit atomico -> fila -> recibo`.

O modelo interpreta duvida, dado fornecido, interrupcao, confirmacao e proxima
pergunta. O backend valida referencias, escopo e autorizacoes; nao adivinha
intencao por palavras. Qualidade pode ser avaliada em paralelo depois do envio.

Para informacao comercial, separar **fato publicado** de **acao confirmada**.
Um preco de catalogo citado e uma informacao; uma reserva ou preco final negociado
exige comprovante de capability/aprovacao. Proposta futura de autorizacao tipada:
`persona_id`, `binding_id`, `publication_id/checksum`, `action`, parametros/valores,
`authorization_id`, validade e origem verificavel. O modelo solicita uma acao;
a autorizacao vem da integracao ou aprovacao real, nunca de uma flag do modelo.

Quando um candidato seguro tiver metadados ruins: corrigir ou remover somente
metadados, registrar aviso e continuar. Quando houver compromisso comercial
sem autorizacao ou evidencia de escopo incorreto: conservar o candidato no audit,
permitir uma reformulacao limitada pelo modelo usando apenas contexto autorizado,
revalidar e fazer um unico commit. Se a recuperacao falhar, registrar erro acionavel
na fila e encaminhamento humano explicito. Nunca inventar uma resposta autoral
fixa nem anunciar que o handoff foi feito antes do commit correspondente.

Tambem revisar, em etapa propria, o gate de isolamento: no checker atual,
`cited_node_outside_branch` e `cited_chunk_outside_branch` entram em qualidade,
pois o filtro de gates so reconhece `publication_`. A recuperacao graciosa precisa
preservar a garantia de escopo comercial sem transformar toda citacao incompleta
em silencio. Este risco preexistente nao foi modificado nesta branch.

## Verificacao e limites

106 testes focados passaram: parser, metadados, duas etapas, texto preservado,
proof real de finalizacao, pergunta diferente, duvida, inconsistencia, confirmacao,
handoff, ambiguidade de dono, normalizacao dupla, texto vazio, publicacao trocada
e helpers dos guards comerciais. Revisao independente Astra encontrou a
normalizacao dupla, corrigida e retestada; nao encontrou outro bloqueador novo
no diff revisado. Acrescentado o teste de handoff final solicitado na revisao.

Uma execucao adicional de `tests/test_conversation_runtime.py` completa teve
4 falhas de contrato legado: testes chamam `decide(context)` sem o parametro
`model_observation`, obrigatorio tambem no HEAD original. Nao sao evidencia de
regressao do patch. Os 5 testes especificos dos guards comerciais passaram;
o resultado dessa execucao adicional nao foi ocultado nem tratado como gate verde.

Testes locais nao provam modelo real, producao, transporte nem entrega.
Nao executados: candidate remoto, WA Validator produtivo, reprocessamento,
publicacao de grafo, migration, release ou envio WhatsApp. Exactly-once continua
no contrato atomico existente e exige prova runtime/DB na fase candidata;
esta revisao nao declara uma entrega real comprovada.

## Proximas mutacoes e autorizacoes

- Build/candidate do runtime: preparar digest imutavel e prova interna do mesmo
  caminho, conforme autorizacao especifica de release; nenhuma release nesta etapa.
- Publicacao de pergunta/configuracao: autorizacao especifica para a persona e
  checksums revisados, sem deploy de runtime.
- Reprocessamento: autorizacao especifica do inbound, apos auditoria dos commits,
  outbounds e recibos existentes; nunca repetir mensagem entregue.
- Migration: nenhuma necessaria para este patch; qualquer outra permanece
  sujeita a autorizacao especifica.
