# Roadmap de agentes — contrato atual

Atualizado em 2026-09-07. Este documento descreve o fluxo operacional simples
para editar, revisar e publicar conhecimento no GraphBundle v3.

## Princípios

1. A publicação v3 ativa é a única fonte de conhecimento do runtime, catálogo,
   site e Golden Dataset. Draft e stage nunca aparecem nesses leitores.
2. Todo conhecimento registra persona, tipo, fonte, estado, node e relações.
3. O mesmo `draft_ref` acompanha Grafo, Golden Dataset e Mensagens.
4. WA Validator é telemetria posterior à publicação, não gate de aprovação.
5. Chaves ficam no cofre/backend. O dashboard mostra somente referência e
   estado mascarados.

## Experiência única de edição

O seletor global de persona, em Configurações, define o escopo de todas as
telas. Ele lista somente personas autorizadas. Trocar a persona troca grafo,
draft, FAQ, mensagens, agente e integração; nunca mistura dados.

### Grafo

- A publicação ativa abre em leitura.
- **Editar grafo** cria ou reutiliza o draft aberto da persona.
- O drawer permite alterar título, resumo, conteúdo, fonte e estado.
- Conectar e excluir edges salva com CAS; excluir edge não exclui node.
- Persona, Embedded e Gallery são protegidos.
- Persona fica no topo; entradas ficam em cima e saídas embaixo.
- Embedded e Gallery são destinos finais e têm somente entrada.
- Cada save mostra revisão/checksum atuais e conflito `409` recarrega o draft.

Ao alterar um fato, as FAQs derivadas voltam automaticamente para
`pending_validation`, perdem a projeção `publishes_to` e geram alerta para
revisão. Isso evita embedding caro e conteúdo antigo sem apagar histórico.

### Golden Dataset

- A publicação ativa é a leitura padrão.
- **Revisar FAQs** abre o mesmo `draft_ref` do Grafo.
- Pergunta e resposta são editáveis em linha.
- Aprovação em lote cria exatamente uma edge para Embedded.
- Rejeitada ou pendente não cria `knowledge_rag_entry` nem chunk.
- Reaprovação reutiliza embedding somente quando checksum, modelo e dimensão
  são iguais.

### Mensagens

A conversa preserva a publicação, checksum, nodes e chunks do turno. A tela
compara conteúdo histórico, conteúdo ativo e proposta. **Adicionar ao
rascunho** substitui publicação direta e grava no mesmo draft da persona.

Telemetria diferencia conhecimento recuperado, citado e autorizado pelo proof.
Ela correlaciona inbound canônico, lead, agente, executor, workflow/modelo,
publicação, decisão, proof e no máximo um outbound. Ausência de ID permanece
ausência; correlation ID nunca vira proof fictício.

## Barra de publicação

O fluxo comum é **Revisar → Publicar**. A revisão calcula diff, valida contratos
e sela documento/checksum. Publicar exige confirmação humana e as evidências da
mesma revisão. Stage persiste o documento aprovado e as projeções imutáveis;
activate usa o mesmo publication ID/checksum e não recompila.

O WA Validator pode executar uma conversa sintética interna depois da
publicação para medir qualidade. Ele não bloqueia nem aprova o grafo e nunca
envia WhatsApp real.

## Agentes no final do grafo

Cada persona pode terminar em um ou mais nodes de uso. Hoje o contrato ativo é
o agente `sdr`; `closer` e `image_editor` são extensões do mesmo modelo.

Ao clicar no node de agente, o operador vê:

- papel, slug e ID estáveis;
- executor (`n8n_agents` hoje; `backend_orchestrator` no futuro);
- prompt e capacidades versionadas no node/configuração;
- workflow, modelo e referência mascarada da credencial;
- publicação/checksum consumidos e readiness.

Cada agente possui integração, credencial, skills e plugins próprios. Nada é
herdado automaticamente de outro agente. O conhecimento chega ao agente por
edges explícitas e pela publicação ativa da mesma persona.

## Dois executores documentados

### Atual: n8n

O seletor global escolhe a persona; o binding resolve o workflow criado a
partir de `apps/conversation-runtime/n8n/persona-conversation-template.json`.
Só binding, webhook e credencial variam. Prompt, regras, produtos e FAQ vêm da
publicação/configuração, sem fork por cliente.

### Futuro: orquestrador no backend

O mesmo binding pode selecionar `backend_orchestrator`. O contrato de entrada,
GraphBundle, proof, idempotência e telemetria não muda; muda somente o executor.
Assim SDR, closer e editor de imagens podem usar modelos, chaves e ferramentas
diferentes sem duplicar o grafo ou as telas.

## Custo e velocidade

- Edição visual não chama modelo nem embedding.
- FAQ impactada é marcada para revisão, não regenerada silenciosamente.
- Embedding ocorre somente após aprovação e apenas para checksum novo.
- Alteração de conteúdo por persona não gera imagem nem deploy de código.
- Código constrói somente serviços alterados; serviços intactos mantêm digest.
- Dashboard permanece no Vercel.

## Isolamento e operação

Publicação de conteúdo pausa, quando necessário, somente o binding da persona
alvo. Persona nova e inerte não exige pausa. Personas não
envolvidas continuam operando.

Release compartilhada começa com auditoria read-only e dry-run. Migration exige
backup data-only recente, restore controlado e gate próprio. Corte de runtime
exige pausa global e drain. Depois do sucesso ou rollback, transportes e IAs
permanecem pausados até autorização posterior separada.

Não fazem parte do deploy: limpeza, resync n8n, conteúdo adicional, retomada ou
WhatsApp real.

## Critérios de conclusão

- duas personas editam e publicam sem vazamento ou perda concorrente;
- FAQ pendente/rejeitada não tem entry/chunk e reaprovação não duplica projeção;
- stage e activate preservam publication ID e checksum aprovados;
- SDR de cada persona resolve publicação, executor e credencial próprios;
- cada inbound produz uma decisão, um proof/commit e no máximo um outbound;
- histórico localiza publicação, nodes/chunks e conteúdo exato do turno;
- Python compile, anti-hardcode, Radon B, backend, frontend e build `/api-brain`
  passam;
- auditoria produtiva confirma SHA, digests, schema, readiness, backup/restore,
  GraphBundle ativo e zero conflitos CAS.
