# Sofia paths

> **Create e Graph compartilham as mesmas tools centrais, taxonomia e validação.**
> A diferença entre eles é o **prompt** e o **tamanho da operação**, não as regras.
> Fonte única de hierarquia/anti-alucinação: `api/services/graph_validation.py`
> (derivada de `api/services/knowledge_taxonomy.py`).

## Create path — criação em massa
- **UI:** `/knowledge/capture` ("Criar conhecimento")
- **Endpoint:** `/kb-intake/start|message|save`
- **Serviço:** `api/services/kb_intake_service.py`
- **Tools:** `api/services/sofia_tools.py` (LLM tool-calling, gate `SOFIA_TOOLS_ENABLED`)
- **Validador:** `validate_sofia_knowledge_plan` (usa `graph_validation`) + `_DIAGNOSTIC_*`
- **Taxonomia:** `knowledge_taxonomy` + `graph_validation`
- **Prompt:** `_SYSTEM_PROMPT` (kb_intake_service) — começa com **plano inicial**, preenche **galhos completos**
- **Uso:** "crie uma campanha completa", "3 grupos com 3 produtos cada", "FAQ/copy para todos os produtos"
- **Testes:** `test_sofia_create_plan_product_group.py`, `test_sofia_create_repair_product_group_tree.py`,
  `e2e_criar_*.py`, `e2e_kb_intake_*.py`, `integration_criar_*.py`

## Graph path — edição cirúrgica do grafo
- **UI:** `/knowledge/graph` (sidebar Sofia)
- **Endpoint:** `/sofia/graph-command`
- **Serviço:** `api/services/sofia_orchestrator.py`
- **Tools:** determinístico (`resolve_persona/operation/node` + `_simple_graph_patch`)
- **Validador:** `_validate_plan_json` + `_validate_patch_canonical` — **ambos usam `graph_validation`** (mesmas regras do Create)
- **Taxonomia:** `knowledge_taxonomy` + `graph_validation`
- **Prompt:** `api/prompts/sofia_graph_command.md` — opera em **nodes individuais** (criar/conectar/mover/corrigir/preencher)
- **Uso:** "conecte esse produto nesse grupo", "mova esse node", "corrija os pais inválidos", "preencha o markdown"
- **Testes:** `test_sofia_graph_product_group.py`, `e2e_sofia_graph_*.py`, `test_bra91_sofia_graph_intents.py`

## Marketing path (NÃO é grafo)
- **UI:** `/marketing/criacao` (item de menu "Criar" leva aqui)
- Criação visual/marketing. **Não** usar para testar a Sofia de grafo/conhecimento.
- ⚠️ Armadilha: o menu "Criar" abre `/marketing/criacao`, não `/knowledge/capture`.

## Regras comuns (obrigatórias nos dois caminhos)
```
persona -> brand -> briefing -> campaign -> audience -> product_group -> product
        -> offer -> copy -> {faq, gallery}
faq -> embedded (após aprovação)
product_group é OPCIONAL; obrigatório quando o operador pede grupos.
product pode ficar sob product_group OU direto sob audience/campaign/briefing/brand.
product_group NUNCA abaixo de product.
```
Anti-alucinação (ambos): termos amplos ("óculos esportivos", "moda inverno",
"linha premium"…) são contexto, não produtos. Só criar `product` com nomes reais,
quantidade explícita, "use estes produtos", "extraia do catálogo" ou catálogo
conectado — senão **perguntar**. (`graph_validation.has_explicit_product_signal`)
