# Handoff — Utzig SDR livre, estágios da lead e grafo v17

Data: 2026-10-03.
Autor: Claude Code, modelo **Claude Opus 5.5** (`claude-opus-5-5`), sessão de
02–03/10/2026 com o usuário (Allan).

## Estado em produção

| Componente | Versão ativa | Evidência |
|---|---|---|
| Grafo Utzig | **v17** (`utzig-concise-closing-v17.json`), publicação `version 16`, runtime `sha256:681263e9121b6e0a44ca4fee29feb5668d49f61ca3a521387c1a22bd3e94263d` | publish runs `37085714766` / `37085765125` / `37085872687` |
| conversation-runtime | `5ad1678` (estágios da lead), digest `sha256:51bd8f6b…` | release `37069701038` |
| transport | `e6eaafc` (sem pausa por runtime indisponível), digest `sha256:8ef12ce9…` | release `37045665076` |
| control-plane | `91b7aad` (menu ignora ofertas `registered_only`; aliases de FAQ), digest `sha256:ce9bf23c…` | release `37079724638` |
| Schema | 162 (envio imediato sem janela) | `deploy-schema` apply |
| LP | Cloudflare Pages `utziggarage.pages.dev`, sem preços, layout da cliente | `utzig-pages` `feat/utzig-lp-v15` |

Leads de teste da Utzig: **328 Allan Rodrigues** (WhatsApp final 8510) e
**369 Alisson** — conversas limpas em 03/10, estágio `novo`. As demais leads da
Utzig (`sdr_qualificacao_carro v*`, `Beatriz Souza`) são do WA Validator.

## Decisões do usuário (vigentes)

1. **Grafo antes de backend.** Comportamento e conteúdo mudam por publicação de
   GraphBundle; código só quando o grafo não alcança.
2. **Sem guardas nem bloqueios no SDR.** O modelo responde livremente; RAG
   orienta. Falha técnica é **logada** (`conversation.technical_failure`,
   `whatsapp.inbound_decision_failed`) e **não pausa** a lead.
3. **Preço: produto × serviço.** Produto (varejo/atacado, ex. Tock) tem valor que o
   SDR conhece e o closer pode descontar. **Serviço (Utzig) não tem valor fixo e o
   SDR nunca sabe o valor.** Valores da cliente ficam só registrados
   (`offer.data.visibility: registered_only`) para religar no futuro; nada na LP,
   no JSON público ou no RAG. Tock não foi alterada.
4. **Dono = Wilian.** "Utzig Garage do Wilian", alternando Utzig e Wilian. Nunca o
   apelido. Ids internos (`entity:alemao`, arquivos `alemao-*.webp`) ficaram.
5. **Estilo:** mensagens curtas (até duas frases), sem repetir resumo, no máximo
   um emoji só na abertura e no encerramento.
6. **Final do roteiro:** depois do "sim", uma mensagem curta passa ao Wilian e dá
   uma dica única de fotos (ou levar o carro pessoalmente). Não é etapa do SDR.
7. **Estágios:** contatado → engajado (cliente deu um fato) → qualificado
   (obrigatórias respondidas) → **oportunidade** (cliente confirmou o resumo =
   handoff para o closer humano, IA pausa). Nunca regride.

## O que mudou nesta sessão

- Runtime: sem guarda de preço no commit; sem pausa por falha técnica;
  `depends_on` não descarta fato; campos `scope: persona` (veículo, nome) são da
  lead e atravessam atendimentos; confirmação aceita o "sim" com qualificação
  completa; estágios acima.
- Grafo v15 → v16 → v17: setores (Limpeza e higienização, Brilho e correção,
  Proteção, Avaliação e orientação); funilaria, pintura, envelopamento e películas
  retirados; preços da Luiza só registrados; FAQs sem valor (vinham da
  Aurora/Aura); nome confirmado uma vez (`human_full_name`); Wilian no lugar do
  apelido; mensagens curtas; `objective` fora do roteiro;
  `procedimento_anterior` opcional; FAQs de fotos e avaliação presencial.
- Publicação: `publish-graphbundle.yml` arquiva `metadata.retired_nodes`
  (`api/scripts/apply_graph_node_retirements.py`) com restauração no rollback;
  tombstones de aresta idempotentes entre stage e activate; galeria vazia de
  upload (`gallery-default`) arquivada porque o site exige uma galeria.
- Ferramentas: workflows `send-queue-preview`, `read-lead-conversation`,
  `read-persona-graph-structure`; **acesso direto somente leitura `akia-db`**
  (usuário `claude_readonly`, chave SSH com comando forçado; ver
  `agent-work/validate-tock-fatal-agent/db-readonly/README.md`).

## Como publicar o próximo grafo

1. Gerador em `data/graph_bundles/utzig-garage/build_*.py` sobre o último bundle
   publicado; baseline = publicação ativa (`akia-db`: `graph_publications`).
2. `api/scripts/compile_graph_bundle.py` → `.PLAN.json`; confira que o compilador
   do control-plane dá o mesmo `runtime_checksum`. **Não use `question_modes`**: o
   compilador do plano (`api/`, v3.6.5) não os conhece e o checksum diverge;
   mude `required` ou remova o campo.
3. `ops/microservices/validate-graphbundle-plan.py` local.
4. Push da branch por SSH (`git@github.com:…`) quando houver arquivo de workflow
   (o token do `gh` perdeu o escopo `workflow`).
5. `publish-graphbundle.yml` plan → stage → activate na branch.
6. Limpar leads de teste com `cleanup-production-lead.yml` (dry-run, apply,
   trava de nome).

## Pendências

- PRs abertos para `main`: brain-plataform **#195** e Card-pio **#3** (sem
  merge). A branch de produção é `feat/utzig-commercial-v15`.
- Testes que ainda esperam a pausa por falha técnica:
  `test_second_consecutive_failure_handoffs_and_duplicate_reuses_events` e o de
  dispatch boundary do transport.
- `e2e/utzig-public-site.spec.ts` desatualizado.
- Confirmar com a Luiza: valor de referência da lavagem detalhada; setor da
  hidratação de couros; valores fixos × "a partir de"; foto nova do hero; FAQ
  "não fazemos funilaria…" (pendente em `…v15.pending-faqs.json`); garantia de 10
  anos do PPF e FAQs herdadas da Aura; tempos não informados.
- Roadmap: `docs/roadmaps/graph-publication-simplification.md` (publicador só
  cuida do que o bundle criou; remoção nativa; base sempre exportada);
  `docs/roadmaps/utzig-commercial-alignment-v15.md`; LP futura sem preços;
  escopo de recuperação por papel (`retrieval_scope`) quando houver closer
  agêntico; alerta ao operador para falhas técnicas repetidas.
- Upload de asset recria `gallery-default` (`ensure_gallery_node`); a próxima
  publicação pode travar de novo até o roadmap de publicação ser implementado.
