# Relatório e handoff — piloto Baita / Vitoria

Data de fechamento: 2026-07-28
Escopo: fonte Markdown, Graph/RAG, runtime conversacional determinístico, workflows n8n equivalentes, WhatsApp, WA Validator e seletor operacional no Brain Platform.

## 1. Estado entregue

- A Baita está vinculada ao modo `internal / deterministic`; é o worker da VPS que responde ao número Meta ativo.
- O seletor `Determinístico` / `n8n SDR + Closer` está disponível em `Configurações > Chaves de API` e em `Persona > Roteamento de mensagens`.
- O dashboard foi compilado e publicado na Vercel. Alias observado no fechamento: `https://brain-plataform-plum.vercel.app`.
- API e worker foram reconstruídos na VPS e estavam saudáveis no fechamento.
- O grafo Baita corrente na VPS é a versão 9, derivada da publicação canônica Markdown cujo checksum completo é `d7dcaad4caa14af432134895e35a0cd897d66c1097b05c07bd6de41f664386d3`.
- A publicação canônica validada possui 15 grupos, 382 produtos ativos, 444 nodes, 859 edges e 443 chunks. O 383º produto permanece pendente/inativo por preço inválido na fonte; ele não foi corrigido nem inferido.
- O estado conversacional de QA contaminado durante os testes foi limpo sem apagar mensagens ou auditoria.
- Workflows e scripts hardcoded da Tock/Baita foram removidos; rollback não deve reativá-los.

## 2. Principais componentes entregues

- Fonte única da Baita em `docs/sdr/baita-conveniencia`, com produtos auditáveis, categorias, persona, agente, regras, tom, FAQ, copy, briefings e evidência de origem.
- Compilação/publicação Markdown → Graph JSON v2 → RAG entries/chunks → nodes/edges.
- Contratos `ConversationContext`, `ConversationDecision` e `AgentResponse`.
- Runtime determinístico sem chave de modelo e runtime n8n com a mesma estrutura e fonte de verdade.
- Carrinho persistido em `leads.metadata`, histórico canônico em `messages`, auditoria e handoff.
- Gate de versão/checksum para impedir que um carrinho baseado em grafo antigo seja reutilizado silenciosamente.
- Seletor operacional sem tabela nova, usando `personas.process_mode` e metadata do binding.
- Executor Playwright interno para WhatsApp Web com perfil persistente, busca por nome/telefone e geração de artefatos.
- CI anti-hardcoded e testes de publicação, runtime, modos de conversa, projeção do grafo e WhatsApp.

## 3. Incidentes encontrados e correções

### Produto e preço incorretos

- Uma pergunta sobre Red Bull recuperou Crunch do histórico. A causa foi herança de produto aplicada a uma pergunta completa quando a resolução corrente falhava.
- O grafo v8 armazenava preço aprovado em `price_cents`, enquanto o leitor aceitava apenas `price.amount`.
- Correções: ranking por termos, herança apenas para referências realmente curtas, leitura de `price.amount`, `price.unit.amount` e `price_cents`, e proibição de inserir item sem preço no carrinho.

### Estado conversacional

- `oio` era aceito como nome sem que o fluxo tivesse pedido o nome.
- `quero um chocolate` interpretava `um` como follow-up de quantidade e recuperava Coca-Cola do histórico.
- `awaiting_address` bloqueava novas consultas de produtos e categorias.
- Um número isolado, como `152`, podia ser interpretado como quantidade do produto.
- Correções: nome somente em `awaiting_name`; follow-up sem substantivo explícito; produto/categoria pode interromper coleta; número isolado em `awaiting_address` vira número do endereço.

### Consulta de cervejas

- `cerveja` singular não resolvia o grupo Markdown/Grafo `cervejas` e a listagem era truncada em oito itens.
- Correção: matching simples singular/plural, prioridade do grupo para consultas genéricas e listagem dos 42 produtos ativos ligados ao grupo, com preço aprovado. A resposta atual cabe no limite de 4.096 caracteres do WhatsApp.

### Respostas repetidas sobre endereço

- O diálogo mostrava uma resposta para cada mensagem recebida enquanto a máquina permanecia travada em `awaiting_address`; não foi comprovada duplicação da Meta nesse trecho específico.
- A prioridade de produto/categoria foi corrigida. A idempotência continua dependendo do `message_id` Meta e das leases do buffer.

## 4. Validações realizadas

- 12 testes do motor determinístico passaram, incluindo as regressões do diálogo informado.
- Build local do dashboard Next.js passou com TypeScript e 33 rotas.
- Build de produção na Vercel passou.
- Verificação dentro da VPS contra o grafo v9 confirmou:
  - typo de saudação não vira nome;
  - chocolate não recupera Coca-Cola;
  - cerveja resolve `consult_category`;
  - 42 produtos ligados são listados;
  - consulta de categoria interrompe endereço sem corrompê-lo;
  - `152` é preservado como número do endereço.
- API `/health` respondeu `ok`; API e worker estavam ativos.
- O binding ativo foi consultado diretamente: `process_mode=internal`, `conversation_mode=deterministic`, `decision_owner=deterministic`.
- Busca pelos tokens/segredo fornecidos durante a sessão não encontrou ocorrência no workspace.

## 5. Vulnerabilidades e riscos residuais

### Críticos

1. **Credenciais Meta foram expostas na conversa.** Mesmo sendo descritas como descartáveis, o token e o segredo do app devem ser tratados como comprometidos. Revogar/rotacionar token e segredo antes do piloto, revisar sessões e confirmar que só existem em secret store/env da VPS.

### Altos

2. **Atendimento aceita todos os contatos.** A allowlist foi removida por decisão explícita. Isso amplia spam, abuso, enumeração do catálogo, consumo de infraestrutura e risco de contatos não consentidos. Aplicar rate limit, opt-out, bloqueio operacional e monitoramento antes de ampliar o piloto.
3. **Álcool sem barreira etária determinística comprovada.** O fluxo lista cervejas e outras bebidas alcoólicas sem uma verificação etária obrigatória implementada e testada no motor determinístico. Criar regra bloqueante baseada no grafo antes de vendas reais.
4. **E2E real completo não foi repetido depois da última correção.** A correção final foi validada dentro da VPS contra o grafo real, mas o cenário completo via WhatsApp Web — pedido, mudança de quantidade, endereço, confirmação, handoff e silêncio da IA — ainda precisa ser reexecutado e arquivado.
5. **Concorrência e ordem das mensagens.** Mensagens rápidas podem ser processadas por leases diferentes, com estado em `leads.metadata` sujeito a last-write-wins. As leases/idempotência reduzem duplicação, mas ainda é necessário teste de corrida com mensagens consecutivas e reordenadas.
6. **Deploy manual pode gerar drift.** Parte do backend foi atualizada na VPS por cópia e rebuild antes do commit final. O próximo deploy deve partir exclusivamente do commit/release, comparar checksum dos arquivos e eliminar divergência entre repositório e servidor.

### Médios

7. **Matching determinístico é heurístico.** Singularização simples e sobreposição de tokens não cobrem sinônimos, erros ortográficos, marcas ambíguas e todas as 15 categorias. Em caso de ambiguidade deve perguntar ou transferir, nunca escolher o primeiro item.
8. **Mapeamento semântico incompleto.** `cerveja` está coberto, mas termos como `chocolate` ainda não são necessariamente um grupo canônico; hoje o comportamento seguro pode ser “não localizado”. Criar aliases como conhecimento validado no Markdown/grafo, não no código.
9. **Listas não têm paginação.** As 42 cervejas cabem hoje em uma mensagem, mas crescimento do grupo pode superar limite do WhatsApp ou degradar a experiência. Implementar paginação determinística baseada no grupo.
10. **Sem estoque em tempo real.** `active/validated` significa conhecimento publicável, não disponibilidade física. Toda promessa de estoque deve continuar com humano ou integração de inventário.
11. **Preço não inclui regras operacionais externas.** Total considera apenas `quantity × unit_price`; frete, taxa, promoções, restrições de endereço e substituições não estão modelados.
12. **Dados pessoais persistidos.** Nome, telefone, endereço e conversa ficam em `leads.metadata/messages`. Definir retenção, minimização, acesso por persona, exportação/exclusão LGPD e criptografia/backup operacional.
13. **Automação do WhatsApp Web é frágil.** Selectors, autenticação e perfil podem expirar; scraping pode quebrar com mudanças de UI e deve ser usado apenas para QA, não como transporte de produção.
14. **Modo n8n não está validado com modelos reais.** O seletor existe, mas esta etapa usa classificador determinístico e nenhuma chave de modelo. Antes de ativar `n8n_agents`, validar schemas, correção única, timeout, custo, ausência de evidência e handoff.
15. **Webhooks precisam de auditoria contínua.** Confirmar assinatura Meta, token inbound n8n, rotação, replay protection e que callbacks não geram resposta conversacional.
16. **Histórico legado possui semântica inconsistente.** Há mensagens antigas outbound registradas como `sender_type=client/role=user`, o que já contaminou recuperação histórica. O novo follow-up é restrito, mas o legado deve ser normalizado ou excluído do contexto por direção confiável.
17. **Mudança de versão invalida carrinho.** O comportamento atual faz handoff seguro, mas pode frustrar conversas durante publicação. Planejar janela de deploy ou migração explícita de carrinhos compatíveis.
18. **Diferença v8/v9 é grande.** O v8 observado tinha 1.187 nodes; o v9 canônico tem 444. A redução é intencional para a fonte Markdown limpa, mas precisa de auditoria de conteúdo antes de descartar qualquer conhecimento legado ainda necessário.
19. **Checksum aparece em comprimentos diferentes.** Alguns eventos usam checksum abreviado de 16 caracteres e scripts/artefatos usam SHA-256 completo. Padronizar o contrato para evitar falsa divergência de linhagem.
20. **Handoff operacional depende do humano.** Pedido confirmado fica `confirmed_pending_human`; não existe fechamento automático. É necessário SLA, fila e procedimento de `resume-ai`.

### Baixos / qualidade

21. Typos como `oio` são tratados de modo seguro, mas não recebem saudação tolerante.
22. Uma lista integral de 42 itens é correta, porém pouco escaneável; paginação/categorias secundárias melhorarão UX.
23. Avisos de conversão LF/CRLF permanecem no Windows; não alteraram o conteúdo, mas `.gitattributes` deve ser padronizado em etapa separada.

## 6. Gates antes de ampliar o piloto

1. Revogar e rotacionar token e segredo Meta expostos.
2. Implementar e testar regra etária para álcool.
3. Reexecutar E2E real completo e cenários adversos do WA Validator.
4. Testar corrida, duplicação e reordenação de webhooks Meta.
5. Confirmar assinatura Meta, token inbound n8n e callbacks de entrega/falha.
6. Validar rate limiting, opt-out e resposta a abuso, já que não há allowlist.
7. Fazer backup de banco, volumes n8n e evento Graph JSON v9.
8. Reimplantar backend a partir do commit final e comparar versão/checksum com a VPS.
9. Manter Tock exclusivamente humana até possuir sua própria base Markdown/grafo/workflow validados.

## 7. Operação e rollback

Auditoria básica:

```powershell
docker compose --env-file .env.compose ps
docker compose --env-file .env.compose logs -f db api workers
curl http://localhost:8080/health
curl http://localhost:8080/api/menu/baita-conveniencia
```

Rollback permitido: desativar o binding determinístico/n8n e colocar a Baita em atendimento exclusivamente humano, preservando histórico, carrinho, eventos e grafo publicado. Não restaurar scripts, catálogos, prompts ou workflows hardcoded.

## 8. Próximo responsável

O próximo responsável deve começar pelos gates críticos/altos, especialmente rotação das credenciais, regra etária e E2E real completo. Novas capacidades comerciais devem entrar no Markdown, ser validadas, publicadas no grafo e só então consumidas pelos dois modos de conversa.
