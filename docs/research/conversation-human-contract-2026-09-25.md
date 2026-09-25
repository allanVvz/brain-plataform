# Conversa humana — contrato e evidências, 2026-09-25

Impacto: `service`, somente `conversation-runtime`. Sem migration, limpeza,
republicação de GraphBundle ou outbound real. Artefato n8n versionado preservado.

## Implementação

- Duas chamadas ao modelo com prompts centralizados em português e seção técnica.
- Histórico recente e última mensagem enviada nas duas etapas; sem inferência de
  resposta esperada pelo último campo pendente.
- `question_kind` e `asked_field_key` no proof e metadata dos outbounds comercial
  e interno. Metadata inválida gera aviso, preservando a resposta válida.
- Resolução única de fatos, ramo, jornada e conclusão; finalização valida redação
  e registra a pergunta. O brief não inclui estado completo nem manifesto.
- Confirmação afirmativa do modelo exige trecho literal e referência pendente.
- Validator aceita consultivas e registra amostra incompleta quando não sabe seguir.

## Auditoria e verificação local

`rollout-microservices.sh status`: quatro serviços alinhados, claims sem pausa.
`validate-production-release.sh`: checksums/digests e serviços saudáveis; zero
conflitos CAS, buffers críticos, outbound sem proof e divergência de grafo.
Backup antigo foi aviso; esta release não inclui migration.

77 testes focados do runtime e 7 testes de contratos/rollout passaram. Sintaxe
Python, fronteiras do monorepo, anti-hardcode, YAML e `bash -n` passaram.
O build do dashboard inicialmente encontrou tipos gerados obsoletos de uma rota
removida. Esses arquivos foram movidos para `.codex-run`, preservados para inspeção;
o build foi repetido com `/api-brain` e o gateway produtivo aprovado e passou.

## Candidate e release

Pendente. O workflow seletivo recebeu um parâmetro opcional para executar fixtures
com modelo real no candidate antes do cutover. A fixture desta release reconstrói
dois contextos problemáticos sobre leads já internos do Validator, sem modificar
seu histórico ou ledger e com `commit_result=False`. Não é replay byte a byte:
histórico curto e nome pendente são reconstruídos em memória, com a publicação ativa.

## Jornadas internas

Pendentes. Devem registrar IDs, publicação/checksum, mensagens, facts, proof,
ledger, exactly-once, latência, encaminhamento e ausência de outbound real.
Não há browser neste fluxo interno; screenshots não substituem essas evidências.
