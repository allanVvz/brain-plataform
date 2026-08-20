# Relatório: o deploy da Tock Fatal (fix de catálogo) afeta a Aurora/Lia?

Data: 2026-08-19
Escopo: PR #38 (`feat: separate Meta WhatsApp messaging credentials from Meta
catalog`, merge `b8b5f84`, deploy via `deploy-production.yml` run
`32313914461`).

## Resposta curta

**Não.** Este deploy específico não toca nenhum dado, migration ou caminho de
execução exclusivo da Aurora. O acoplamento real entre personas neste projeto
não é "deploy", é **runtime compartilhado** (mesmo binário `api`/`workers`
para todas as personas) — e este deploy não alterou nenhum arquivo desse
runtime compartilhado.

## Por que não afeta

1. **Diff da PR #38 é só integração/dashboard, não runtime de conversa.**
   `git show b8b5f84 --stat`:
   - `api/routes/integrations.py` (+4/-2)
   - `api/services/integration_service.py` (+55)
   - `dashboard/app/tools/page.tsx` (+10)

   Nenhum desses arquivos é lido por `graph_agent_runtime_v3.py`,
   `conversation_runtime.py` ou qualquer worker de despacho de WhatsApp. O fix
   cria um `service="meta_whatsapp"` separado de `service="meta"` (catálogo) —
   ambos são linhas na tabela de credenciais de integração, escopadas por
   persona/serviço (`api/services/integration_service.py:90,168,223,305,409`).
   Não existe leitura cruzada entre personas nessa tabela.

2. **Deploy de código nunca muta binding/routing operacional.**
   `ops/vps/deploy.sh:167-168` é explícito: *"Binding ownership/routing is
   operational content. Code deploys never mutate persona bindings; use the
   reviewed reassignment procedure instead."* A troca de qual número/persona
   está ativo é um procedimento manual e revisado à parte (`api/scripts/
   move_whatsapp_binding.py`, `set_binding_deterministic.py`), nunca algo que
   o pipeline de deploy dispara sozinho.

3. **Nenhuma migration nova neste deploy.** A migration mais recente no repo é
   `130_shared_lead_memory_and_journey_commit_v4.sql`, e a evidência coletada
   hoje mais cedo (`docs/evidence/AURORA_STUCK_2026-08-19/findings.md`) já
   confirmou 129 e 130 aplicadas em produção *antes* deste deploy. O passo
   `migrate` deste rollout não tem DDL/DML novo para rodar — logo não há
   superfície de mutação de dados da Aurora neste ciclo.

4. **`seed-admin` (único container além de `api`/`migrate`/`workers` que roda
   a cada deploy) só cria o usuário admin** (`scripts/ensure_seed_admin.py`,
   `docker-compose.yml:342-357`) — não toca persona, grafo nem binding.

5. **Grafo da Aurora é publicado por processo separado, fora do CI/CD.**
   `publish_aurora_graph.py` roda manualmente contra o Supabase de produção,
   não faz parte de `deploy-production.yml`. O pipeline de deploy só builda e
   sobe imagens de código; a publicação de conteúdo/grafo é outro sistema,
   outro gatilho, outro humano apertando o botão.

## Onde o acoplamento real existe (e por que isso importa)

Não há isolamento por container/processo entre personas — `api` e `workers`
são um **runtime único e compartilhado** que lê configuração e roteamento do
banco (`workflow_bindings`, integrações, grafos publicados) para decidir como
responder cada persona. Isso significa:

- Um bug introduzido em `graph_agent_runtime_v3.py`, `conversation_runtime.py`
  ou nos workers de despacho **afeta todas as personas simultaneamente**,
  Aurora incluída — não porque o deploy "vazou" dado de uma pra outra, mas
  porque as duas rodam o mesmo código.
- `AGENT_ROADMAP.md` já marca isso como princípio arquitetural a corrigir:
  regra de governança #8 ("nunca ramificar código de produção por cliente,
  persona, produto ou serviço") e o item 7 do roadmap (orquestradores por
  estágio) descrevem exatamente esse alvo de desacoplamento futuro — hoje
  Aurora "permanece no processo atual até o fim" (congelada, só correção de
  bug) enquanto a Tock Fatal nasce no pipeline novo (`GraphBundle`), e as
  duas convergem só quando a Aurora for migrada por último, comparada por
  checksum.

## O que precisaria existir para isolamento real (fora do escopo deste deploy)

Já é o alvo declarado no roadmap (`docs/roadmaps/AGENT_ROADMAP.md`, seção
"Arquitetura alvo — GraphBundle" e item 7 "Orquestradores por estágio"), não
uma proposta nova deste relatório:

- `PublicationPlan` por persona com staging + ativação atômica independente
  (já desenhado, ainda não implementado — item 1 do roadmap).
- Nenhuma alteração de conteúdo/grafo de uma persona deveria depender de
  deploy de código de outra — já é assim hoje na prática (grafo publica fora
  do CI/CD), mas ainda não é **estruturalmente garantido** por testes ou por
  isolamento de processo.
- Runtime compartilhado continua sendo o ponto de falha correlacionado até o
  item 7 (orquestradores por estágio) sair do papel.

## Conclusão para este deploy específico

Seguro confirmar: **o deploy do fix de catálogo da Tock Fatal (PR #38) não
alterou nada que a Aurora/Lia leia em produção.** A verificação pós-deploy
(workers saudáveis, `safety_paused` da Aurora, e um teste real via WhatsApp
nos dois números) serve para confirmar isso empiricamente, não porque há
motivo estrutural para dúvida.
