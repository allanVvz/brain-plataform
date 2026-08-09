# Relatório E2E — tela de Validações (WA Validator), 2026-08-09

Teste feito via navegador real (Chrome automatizado), na tela de produção
(`https://brain-plataform-plum.vercel.app/settings?tab=messaging&sub=validacoes`,
aba Configurações → Mensageria → Validações), não via script direto no servidor.
Objetivo: confirmar que as mudanças desta sessão (estado inicial, correções de
Fase A/B, conteúdo de tom/fluxo) funcionam de ponta a ponta pela tela real, e
levantar problemas de UI/analytics que só aparecem usando a tela de verdade.

## O que foi confirmado funcionando

- O seletor **"Estado inicial"** (Frio / Cliente já conhecido / Aleatório) está
  visível e funcional na tela, exatamente como implementado.
- Gerado e executado um teste real: persona Aurora, fluxo "SDR agêntico de
  agendamento", estado inicial "Cliente já conhecido".
- **Confirmado visualmente na própria tela de conversa**: a primeira resposta do
  bot já chama o cliente pelo nome ("Diego, fazemos sim! O polimento de vidros
  é um dos serviços da Aurora...") mesmo o script nunca tendo enviado o nome —
  prova end-to-end de que a semeadura de `nome_cliente` (via
  `commit_graph_turn_v3`, mesma RPC de produção) funciona pela tela real, não
  só quando chamada direto por script.
- Nenhuma pergunta repetida, uma pergunta por turno, nota comercial exibida
  corretamente no cabeçalho da conversa (`servico: polimento de vidros ·
  objective: manter o carro e cuidar bem dele`).

## Problemas encontrados (novos, específicos da tela)

### A. "Analisar Evidências" reporta um gap falso para toda persona em `graph_agent_runtime_v3` — ALTA prioridade

A conversa acima rodou perfeitamente (nome nunca reperguntado, zero erros de
prova nos primeiros 6 turnos), mas a análise automática deu **score 42%** e
reportou um gap "high":

> Runtime reportou ['40:sha256:bd4149fb...'], esperado
> 14:sha256:93ab4cf0...

**Causa raiz** (`api/services/wa_validator_service.py`):
- `generate_script()` (linha ~432) monta `expected_knowledge` a partir de
  `_build_graph_context()`, que lê a versão do **store v2.1 legado**
  (`graph_json_v2_store.load_current`, hoje `v14` para a Aurora — é o mesmo
  "Grafo v14" mostrado na etiqueta da tela).
- Mas cada turno de conversa registra `graph_version`/`graph_checksum` do
  **runtime v3 de verdade** (`graph_agent_runtime_v3.build_context()`, hoje
  publicação `v40`).
- `analyze_gaps()` (linha ~731-750) compara esses dois contadores como se
  fossem a mesma coisa. Para qualquer persona em `graph_agent_runtime_v3`
  (Aurora e futuras), essa checagem **nunca vai bater**, porque são dois
  versionamentos independentes por design — não é uma coincidência rara, é
  garantido sempre dar gap "high" e derrubar o `overall_score` (a fórmula usa
  50% baseada em `evidence_ratio`, que conta esse gap).
- Consequência prática: quem olhar só o score (42%) vai achar que o teste
  falhou feio, quando na verdade a conversa foi impecável. Isso mascara
  regressões reais (um score sempre baixo por um motivo errado ensina a
  ignorar o score) e engana quem usa a tela sem ler os gaps um por um.

**Recomendação**: em `analyze_gaps()`, pular a checagem `graph:` (ou resolvê-la
contra a publicação do `graph_agent_runtime_v3` em vez do store v2.1) quando a
persona usa `graph_agent_runtime_v3` — `graph_agent_runtime_v3.binding_uses_v3`
já existe e pode informar essa decisão.

### B. Lista de leads não atualiza sozinha depois que um teste termina — média prioridade

Depois de "Executar Direto" terminar (status "done"), o lead novo (`Diego`)
não aparecia na lista "Conversas de validação registradas" nem era encontrado
pela busca — só apareceu depois de clicar manualmente no ícone de atualizar.

**Causa raiz**: `ValidatorWorkspace` (`dashboard/app/wa-validator/page.tsx`) e
a lista de leads (`MessagesLayout validationMode`, renderizada como
componente irmão em `dashboard/components/settings/MessagingSettingsPanel.tsx`
linha 139-152) são componentes independentes sem nenhuma coordenação — quando
o teste termina, nada avisa a lista de leads para buscar de novo.

**Recomendação**: `MessagingSettingsPanel` já é o pai de ambos; adicionar um
callback `onRunComplete` em `ValidatorWorkspace`/`wa-validator/page.tsx`
(disparado no fim de `handleRunDirect`/`handleRunWA`) que o pai usa para forçar
um refresh do `MessagesLayout` (ex.: bump de uma `key` prop).

### C. Última mensagem de uma qualificação completa pode ficar sem nenhuma resposta — confirma gap já conhecido, ainda aberto

No mesmo teste, a mensagem final do script ("Os bancos estão meio manchados")
gerou o gap `transport_or_reply: "1 turno(s) sem resposta válida"` — o cliente
literalmente não recebeu resposta nenhuma para essa mensagem.

**Causa raiz confirmada**: quando `graph_proof_checker_v3.check()` rejeita a
proposta do modelo só por causa do sinal de conclusão
(`qualification_completion_mismatch`/`question_after_completion` +
`handoff_required_by_rule`, sem nenhum campo faltando), o fallback em
`graph_agent_runtime_v3.decide()` calcula `fallback_id = None` (não há campo
pendente para perguntar de novo) e
`compose_published_question(reply="", next_question_node_id=None, ...)`
retorna string vazia. Em `conversation_runtime.commit()`, todo envio é
condicionado a `if response.reply_text:` (verdadeiro só para string não-vazia)
— então nada é enfileirado. Este é o Gap B do relatório de 2026-08-08
("`qualification_complete` incorreto perto do fechamento"), que já era sabido
inofensivo-mas-feio; esta sessão confirma que na pior forma ele não é só
"resposta genérica", é **silêncio total** no último turno.

**Recomendação**: quando o fallback dispara sem nenhum campo pendente (ou
seja, a qualificação já está de fato completa pelo cálculo autoritativo),
usar uma pergunta/frase de encerramento publicada pelo grafo (ex.: o texto de
`aurora-rule-operation.handoff_rule.text`) em vez de string vazia, para que o
cliente nunca fique sem resposta na mensagem que efetivamente fecha a
qualificação.

## Priorização sugerida

| # | Problema | Risco | Esforço |
|---|---|---|---|
| A | Score/gap falso para personas v3 | Alto — mascara regressões reais, engana quem lê só o score | Baixo |
| C | Silêncio total no turno de fechamento | Alto — cliente real fica sem resposta | Médio |
| B | Lista de leads não atualiza sozinha | Baixo — só atrito de operador, dado existe | Baixo |
