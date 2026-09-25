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

Publicado: fonte `2834149cb9e94fe1271751dd1a6c8e419539dc31`, manifesto
`4a80ede6bf3475ee8e775c515b341123fa6b0027`, digest
`sha256:392e138720deeda5db5159e3ca35ad01eb7505023eb700fbcb6608b774a23523`.
Runtime ativo no slot azul; slot verde anterior preservado para rollback.
Gateway, control-plane e transport mantiveram seus SHAs/digests. Sem pausa global.

- [CI](https://github.com/allanVvz/brain-plataform/actions/runs/36117458324): passou.
- [Build único](https://github.com/allanVvz/brain-plataform/actions/runs/36117458037): passou.
- Primeiro dry-run falhou no checkout por SHA abreviado; nenhuma mutação.
- [Dry-run com SHA completo](https://github.com/allanVvz/brain-plataform/actions/runs/36117817783): passou.
- [Release](https://github.com/allanVvz/brain-plataform/actions/runs/36117961451): candidate,
  cutover e canário passaram. Apply começou às 09:22:45 UTC, ativação às 09:23:28;
  resposta do canário persistida às 09:23:48. Sem rollback ou segundo deploy.

O workflow seletivo recebeu um parâmetro opcional para executar fixtures
com modelo real no candidate antes do cutover. A fixture desta release reconstrói
dois contextos problemáticos sobre leads já internos do Validator, sem modificar
seu histórico ou ledger e com `commit_result=False`. Não é replay byte a byte:
histórico curto e nome pendente são reconstruídos em memória, com a publicação ativa.

Os dois probes tiveram duas chamadas e nenhum commit. Utzig respondeu à dúvida,
mas retomou o nome imediatamente: falha editorial, não identificada como warning
pelo proof. Tock respondeu ao contexto consultivo sem extrair o texto como nome;
registrou `fact_correction_not_explicit:retail_style`. O gate técnico passou,
sem transformar essa observação editorial em veto de envio.

## Jornadas internas

Evidências completas: [mensagens, fatos e audits](conversation-human-contract-2026-09-25.evidence.json).
Continuação guiada pelo operador através de `enqueue_validator_inbound` e dos
helpers de auditoria do WA Validator. Cada novo inbound teve identidade própria;
nenhuma sessão ou mensagem foi reexecutada. As duas amostras usaram exclusivamente
provider `internal_validator`, com mensagens de destino persistidas no sink interno.
Não houve navegador, screenshot ou captura do status HTTP bruto por turno.

| Amostra | Sessão / lead | Resultado |
| --- | --- | --- |
| Utzig | `1bdcfad0-cb83-48cb-b6c9-0c644529318b` / `377` | 4 turnos; interrupção de qualidade; `collecting` |
| Tock | `0efe66d3-240d-4267-8230-8fd8b60d9197` / `378` | 6 turnos; confirmação natural e um handoff; qualidade reprovada |

Em cada um dos 10 turnos: um inbound, uma decisão, um proof válido, um commit
concluído, um outbound persistido depois do proof, duas chamadas ao modelo e zero
repair. Todos os outbounds têm `metadata.validation=true`. As duas leads sintéticas
terminaram com `ai_enabled=true`, `ai_paused=false`; nenhuma persona/binding foi pausada.

Utzig usou publicação v12 `46925297-f966-42cc-a33a-bd031fa1ded5`, checksum
`sha256:a5bfac4a813f9c7c357910371d70a8e8a2df14e86d93c4374aa4e2f322b1c553`.
O canário inicial ocorreu às 09:23 UTC; os três turnos seguintes às 18:11–18:13 UTC,
com latências de 14,3–16,5 s. Veículo `Onix 2020`, cor e condição permaneceram no
ledger. Ao receber uma dúvida sobre avaliação por fotos enquanto aguardava nome,
respondeu e repetiu o nome na mesma mensagem. A amostra foi interrompida conforme
[brain-agent-e2e](../../.agents/skills/brain-agent-e2e/SKILL.md):
“Stop when … the reply substantially repeats any recent agent reply.”
Não houve resumo final ou confirmação nesta amostra; não declarar a jornada aprovada.

Tock usou publicação v38 `2b46d7a2-fba9-4b92-aa2a-27fb53f55af4`, checksum
`sha256:3aa4cd2d4a7c50389534ab9cb7c372474030b3852eaaa4c851fc8b7f14d6a28a`.
Turnos às 18:12–18:17 UTC; latências dos turnos guiados de 20,5–24,7 s.
Perguntou a ocasião de uso (`consultative`, sem campo); entendeu a resposta sobre
escritório e retomou a forma de recebimento. Depois anunciou encaminhamento
enquanto o estado ainda era `awaiting_confirmation`. A frase “Isso mesmo, pode
encaminhar para a equipe.” gerou `explicit_confirmation=true`, rota `HUMAN` e
`handed_off`, sem outra pergunta. Metadata de pergunta ausente no último turno
gerou warning e não descartou a resposta. O preço R$ 129,90 foi conferido contra
a FAQ publicada `faq:tock-vestidos-vestido-em-mousse-varejo-preco-canal-quantidade`.

## Pendências identificadas — não houve redeploy corretivo

1. Utzig ainda retoma o nome cedo demais. Tornar explícito o adiamento para outro
   turno e validar a redação com modelo real antes de uma próxima release.
2. Tock anuncia encaminhamento antes da confirmação. O brief já informa um único
   estado; falta verificar que o modelo respeita esse estado na fala.
3. Atualizações naturais de estilo/necessidade/grau de qualificação geraram
   `fact_correction_not_explicit`; fatos anteriores permaneceram no ledger.
4. O RPC `graph_turn_context_batch_v4` não devolve metadata das mensagens.
   A consulta `get_messages` confirmou `question_kind` e `asked_field_key`
   persistidos. As etapas usam o texto real como fallback; uma futura adaptação
   de leitura pode enriquecer metadata sem migration.
5. O último buffer da Tock, `5e11a86a-4a8b-4388-a8ac-242cd8bc384d`, permaneceu em
   `processing` depois do commit. A leitura repetida confirmou uma decisão/proof/
   outbound, sem duplicidade. O transport só chama `complete_whatsapp_buffer`
   quando `handoff=false`; no Validator, o handoff não pausa a lead. Essa combinação
   deixa o inbound sem terminalização. Não houve correção manual nem deploy do
   transport fora do escopo. O canário de uma mensagem não cobre esse encerramento;
   corrigir o contrato de terminalização e seu teste antes de outra release.

Auditoria final: serviços saudáveis, zero conflitos CAS, zero outbound sem proof,
zero divergência de checksum; um buffer em processamento, identificado acima.
Os invariantes por turno passaram, mas a qualidade e o encerramento completo do
teste não passaram. O objetivo de duas jornadas plenamente aprovadas permanece pendente.
