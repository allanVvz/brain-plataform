# KB Intake Graph Rules Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alinhar o `kb_intake_service` e a materialização do grafo às regras atuais de `ai_brain_regras_negocio_grafo.md`, eliminando cards criados no lugar errado, conexões top-down incorretas e relações diretas indevidas com Embedded.

**Architecture:** Primeiro consolidar a regra canônica em uma única fonte compartilhada, depois fazer `kb_intake_service`, `graph_validation`, `knowledge_taxonomy` e `knowledge_graph.apply_plan_hierarchy` consumirem essa mesma regra. O chat monta um JSON de proposta, traduz as conexões em linguagem operacional para confirmação humana, e só depois da confirmação transforma esse JSON em nodes/edges reais.

**Tech Stack:** FastAPI, Python services, Supabase/Postgres via `supabase_client`, testes Python existentes em `tests/test_*sofia*`, `tests/test_marketing_criacao_kb_intake_flow.py` e `tests/e2e_kb_intake_*`.

---

## Avaliação Atual

### O Que A Regra De Negócio Exige

Fonte: `ai_brain_regras_negocio_grafo.md`.

- Cadeia canônica máxima: `Persona -> Brand -> Briefing opcional -> Campaign -> Briefing opcional -> Audience -> Product Group opcional -> Product opcional -> Copy opcional -> FAQ -> Embedded`.
- `Product Group`, `Product`, `Copy` e `Rule` adicionam contexto extra ao JSON final quando existem; não são obrigatórios por si só.
- Se `Product Group` existe, `Product` deve ficar dentro dele por ligação top-down `product_group -> product`.
- Se `Copy` existe para um Product ou Product Group, `FAQ` deve considerar essa Copy como contexto mais específico.
- `FAQ` deve ficar no alvo semântico mais específico do mesmo branch, com prioridade `Copy`, `Product`, `Product Group`, `Audience`, `Campaign/Briefing`, `Brand`, `Persona`.
- `FAQ` nasce como `pending_validation`.
- Só `FAQ approved` pode conectar ao `Embedded`.
- `Embedded` nunca recebe conexão direta de `Persona`, `Brand`, `Briefing`, `Campaign`, `Audience`, `Product Group`, `Product` ou `Copy`.
- O sistema não deve criar cards estruturais abstratos automaticamente sem confirmação. Defaults só podem aparecer como proposta explícita no chat e virar nodes reais depois do operador confirmar.

### O Que Não Está Coerente Hoje

1. `offer` ainda está no galho canônico do serviço, mas não existe no galho principal do arquivo de regra atual.
   - `api/services/kb_intake_service.py:167` define `persona -> ... -> product -> offer -> copy -> { faq, gallery }`.
   - `api/services/knowledge_taxonomy.py:10` e `api/services/knowledge_taxonomy.py:56` também incluem `offer`.
   - A regra atual permite ofertas como dados comerciais, mas não como camada obrigatória entre `Product` e `Copy`.

2. `Product Group` está tratado como opcional sem uma regra clara de conexão quando ele existe.
   - `api/services/kb_intake_service.py:160` diz que `product_group` é opcional quando o operador não pede grupos.
   - `api/services/kb_intake_service.py:1184` registra que `product_group` é opcional e permite `product` direto em `audience/campaign/briefing/brand`.
   - `api/services/graph_validation.py:17` e `api/services/graph_validation.py:34` repetem essa regra.
   - O problema não é ele ser opcional; o problema é permitir que Sofia crie `Product Group` e depois pendure `Product` no pai errado.

3. O validador aceita `copy` abaixo de lugares ambíguos sem traduzir isso para confirmação operacional.
   - `api/services/graph_validation.py:35` aceita `copy` sob `offer`, `product`, `product_group`, `campaign`, `audience`.
   - `Copy` é opcional. Quando existir, precisa ficar ligada ao card que ela contextualiza, por exemplo `product -> copy` ou `product_group -> copy`, e não paralela ao galho.

4. O validador aceita `FAQ` sob `offer` e outros fallbacks sem garantir confirmação do alvo semântico.
   - `api/services/graph_validation.py:38` aceita `faq` sob `copy`, `offer`, `product`, `product_group`.
   - `api/services/kb_intake_service.py:1214` aceita `faq` sob `rule`, `copy`, `offer`, e só adiciona `product` se não houver copy/offer.
   - Falta traduzir a decisão para o operador antes do save: por exemplo, "Essa FAQ responde sobre a copy X do produto Y?".

5. O `Embedded` aparece como warning e não como contrato de publicação.
   - `api/services/kb_intake_service.py:805` apenas emite `pending_embedded`.
   - O plano não deve conter edge para Embedded antes da aprovação, mas o sistema precisa validar e publicar `FAQ approved -> Embedded` no fluxo de aprovação, não deixar isso como pendência genérica.

6. A persistência pode deixar estado parcial no banco.
   - `api/services/kb_intake_service.py:6187` persiste item por item.
   - `api/services/kb_intake_service.py:6224` roda `apply_plan_hierarchy` depois, como best-effort.
   - Se a hierarquia falhar, itens e nodes já existem; isso contradiz a exigência de não haver conhecimento solto.

7. `repair_primary_tree_connections` mascara erro estrutural.
   - `api/services/knowledge_graph.py:556` conecta nó sem primary edge de volta ao root/persona.
   - Pela regra atual, fallback para Persona só é aceitável em exceção extrema, não como reparo geral.

8. As relações primárias materializadas ainda usam labels legados como `contains`, `supports_copy`, `answers_question`.
   - `api/services/knowledge_graph.py:168` define `_DEFAULT_PARENT_RELATION`.
   - `api/services/knowledge_graph.py:571` define `_default_plan_relation`.
   - A regra de grafo e o prompt do serviço falam em relações canônicas como `audience_has_product_group`, `product_group_has_product`, `copy_has_faq`. Misturar as duas famílias dificulta validação e renderização.

9. O prompt interno do Sofia/Kb intake contradiz a regra escrita.
   - Ele mistura "não inventar nós" com trechos que ainda sugerem expansão automática. A regra correta é propor JSON e só criar nodes reais depois de confirmação no chat.
   - Ele diz que `FAQ` deve ser gerada por tool e não escrita, mas também tem fallback de plano que pode gerar conteúdo.
   - Ele ainda menciona "Golden Dataset" e política de expansão de FAQ, que não aparece como regra central em `ai_brain_regras_negocio_grafo.md`.

## Decisão Necessária

Antes da implementação, fechar uma decisão: `offer` sai da árvore primária e vira metadata/node lateral, ou o arquivo `ai_brain_regras_negocio_grafo.md` deve ser atualizado para incluir `offer`.

Este plano assume a regra operacional corrigida: `product_group`, `copy` e `rule` são opcionais; quando aparecem, adicionam contexto e precisam de conexão top-down correta. `offer` não é camada primária obrigatória; ofertas entram em `metadata` de `product`, `copy` ou `faq`, ou como relação secundária quando necessário.

## File Structure

- Modify: `api/services/graph_validation.py`
  - Fonte única para validação de parent/edge conforme `ai_brain_regras_negocio_grafo.md`.
- Modify: `api/services/knowledge_taxonomy.py`
  - Ajustar `PRIMARY_CHAIN` ou marcar `offer` como não primário.
- Modify: `api/services/kb_intake_service.py`
  - Remover contradições do prompt, normalizador e validação de plano.
- Modify: `api/services/knowledge_graph.py`
  - Materializar relações primárias canônicas e parar fallback silencioso para Persona quando o nó tem parent inválido.
- Modify: `api/services/knowledge_lifecycle.py`
  - Garantir que item novo nasce `pending_validation` quando vier do Sofia/Criar e que edição de FAQ aprovada volta para validação.
- Test: `tests/test_sofia_create_plan_product_group.py`
- Test: `tests/test_create_path_autofix_campaign_audience_product_group.py`
- Test: `tests/test_marketing_criacao_kb_intake_flow.py`
- Test: novo `tests/test_kb_intake_graph_rules_alignment.py`

---

### Task 1: Congelar A Regra Canônica Em Testes

**Files:**
- Create: `tests/test_kb_intake_graph_rules_alignment.py`
- Modify: none

- [ ] **Step 1: Escrever testes que provam os contratos centrais**

```python
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "api"
sys.path.insert(0, str(API))

from services import graph_validation


def test_product_can_attach_to_audience_when_no_product_group_exists():
    assert graph_validation.parent_violation("product", "audience") is None


def test_product_must_attach_to_product_group_when_group_exists(monkeypatch):
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    from services import kb_intake_service as svc

    plan = {
        "persona_slug": "qa-persona",
        "entries": [
            {"content_type": "brand", "slug": "brand", "title": "Brand", "content": "Brand"},
            {"content_type": "campaign", "slug": "campaign", "title": "Campaign", "content": "Campaign", "metadata": {"parent_slug": "brand"}},
            {"content_type": "audience", "slug": "audience", "title": "Audience", "content": "Audience", "metadata": {"parent_slug": "campaign"}},
            {"content_type": "product_group", "slug": "radar", "title": "Radar", "content": "Grupo Radar", "metadata": {"parent_slug": "audience"}},
            {"content_type": "product", "slug": "produto-radar-01", "title": "Produto Radar 01", "content": "Produto", "metadata": {"parent_slug": "audience"}},
        ],
    }

    errors = svc.validate_sofia_knowledge_plan(plan, session={"mode": "criar"})
    assert any("produto-radar-01" in err or "product_group" in err for err in errors)


def test_product_inside_product_group_is_valid():
    assert graph_validation.parent_violation("product", "product_group") is None


def test_copy_parent_is_product_or_product_group_only():
    assert graph_validation.parent_violation("copy", "product") is None
    assert graph_validation.parent_violation("copy", "product_group") is None
    assert graph_validation.parent_violation("copy", "audience") is not None
    assert graph_validation.parent_violation("copy", "campaign") is not None
    assert graph_validation.parent_violation("copy", "offer") is not None


def test_faq_parent_priority_is_enforced_by_plan_validator(monkeypatch):
    os.environ["SOFIA_TOOLS_ENABLED"] = "true"
    from services import kb_intake_service as svc

    plan = {
        "persona_slug": "qa-persona",
        "entries": [
            {"content_type": "brand", "slug": "brand", "title": "Brand", "content": "Brand"},
            {"content_type": "campaign", "slug": "campaign", "title": "Campaign", "content": "Campaign", "metadata": {"parent_slug": "brand"}},
            {"content_type": "audience", "slug": "audience", "title": "Audience", "content": "Audience", "metadata": {"parent_slug": "campaign"}},
            {"content_type": "product_group", "slug": "grupo", "title": "Grupo", "content": "Grupo", "metadata": {"parent_slug": "audience"}},
            {"content_type": "product", "slug": "produto", "title": "Produto", "content": "Produto", "metadata": {"parent_slug": "grupo"}},
            {"content_type": "copy", "slug": "copy", "title": "Copy", "content": "Copy", "metadata": {"parent_slug": "produto"}},
            {"content_type": "faq", "slug": "faq", "title": "FAQ", "content": "Pergunta? Resposta.", "metadata": {"parent_slug": "produto"}},
        ],
    }

    errors = svc.validate_sofia_knowledge_plan(plan, session={"mode": "criar"})
    assert any("faq" in err.lower() and "copy" in err.lower() for err in errors)
```

- [ ] **Step 2: Rodar teste e confirmar falha**

Run: `python -m pytest tests/test_kb_intake_graph_rules_alignment.py -q`

Expected: falha em pelo menos um teste, porque hoje o validador não diferencia "sem product_group" de "product_group existe e este produto deveria ficar dentro dele".

### Task 2: Atualizar `graph_validation.py` Para A Regra Escrita

**Files:**
- Modify: `api/services/graph_validation.py`
- Test: `tests/test_kb_intake_graph_rules_alignment.py`

- [ ] **Step 1: Ajustar parents canônicos**

Trocar `CANONICAL_PARENTS` para:

```python
CANONICAL_PARENTS: dict[str, set[str]] = {
    "persona": set(),
    "brand": {"persona"},
    "briefing": {"brand", "campaign"},
    "campaign": {"briefing", "brand"},
    "audience": {"briefing", "campaign"},
    "product_group": {"audience"},
    "product": {"product_group", "audience", "campaign", "briefing", "brand"},
    "copy": {"product", "product_group"},
    "faq": {"copy", "product", "product_group", "audience", "briefing", "campaign", "brand", "persona"},
    "gallery": {"copy"},
    "embedded": {"faq"},
}
```

Adicionar uma função específica para prioridade de FAQ:

```python
FAQ_PARENT_PRIORITY = (
    "copy",
    "product",
    "product_group",
    "audience",
    "briefing",
    "campaign",
    "brand",
    "persona",
)


def faq_priority_violation(parent_type: str, available_types: set[str]) -> str | None:
    parent = _canon(parent_type) or (parent_type or "").strip().lower()
    if parent not in FAQ_PARENT_PRIORITY:
        return f"faq nao pode ficar abaixo de {parent}; parent permitido por prioridade: {list(FAQ_PARENT_PRIORITY)}"
    for preferred in FAQ_PARENT_PRIORITY:
        if preferred in available_types:
            if parent != preferred:
                return f"faq deve ficar no menor node disponivel: esperado {preferred}, recebeu {parent}"
            return None
    return None


def contextual_parent_violation(
    child_type: str,
    parent_type: str,
    available_types: set[str],
) -> str | None:
    child = _canon(child_type) or (child_type or "").strip().lower()
    parent = _canon(parent_type) or (parent_type or "").strip().lower()
    if child == "product" and "product_group" in available_types and parent != "product_group":
        return "product_group existe no plano; confirme qual grupo recebe este produto e conecte product_group -> product"
    if child == "copy" and "product" in available_types and parent not in {"product", "product_group"}:
        return "copy precisa ficar ligada ao product ou product_group que ela contextualiza"
    return None
```

- [ ] **Step 2: Rodar teste focado**

Run: `python -m pytest tests/test_kb_intake_graph_rules_alignment.py::test_product_can_attach_to_audience_when_no_product_group_exists tests/test_kb_intake_graph_rules_alignment.py::test_product_must_attach_to_product_group_when_group_exists tests/test_kb_intake_graph_rules_alignment.py::test_copy_parent_is_product_or_product_group_only -q`

Expected: PASS.

### Task 3: Remover `offer` Da Árvore Primária

**Files:**
- Modify: `api/services/knowledge_taxonomy.py`
- Modify: `api/services/kb_intake_service.py`
- Modify: `api/services/knowledge_graph.py`
- Test: `tests/test_kb_intake_graph_rules_alignment.py`

- [ ] **Step 1: Alterar `PRIMARY_CHAIN`**

Em `api/services/knowledge_taxonomy.py`, trocar:

```python
("product", "offer", "product_has_offer"),
("offer", "copy", "offer_has_copy"),
```

por:

```python
("product", "copy", "product_has_copy"),
("product_group", "copy", "product_group_has_copy"),
```

Manter `offer` em `CANONICAL_NODE_TYPES` somente se ainda houver dados legados, mas sem relação primária.

- [ ] **Step 2: Ajustar prompt e normalização em `kb_intake_service.py`**

Remover dos textos de prompt a frase `product -> offer -> copy` e substituir por:

```text
persona -> brand -> briefing -> campaign -> audience -> product_group -> product -> copy -> faq
```

Atualizar `_PREFERRED_PARENT_TYPES` para preferir o contexto mais específico sem transformar cards opcionais em bloqueio abstrato:

```python
_PREFERRED_PARENT_TYPES: dict[str, tuple[str, ...]] = {
    "briefing": ("campaign", "brand"),
    "campaign": ("briefing", "brand"),
    "audience": ("briefing", "campaign"),
    "product_group": ("audience",),
    "product": ("product_group", "audience", "campaign", "briefing", "brand"),
    "copy": ("product", "product_group"),
    "faq": ("copy", "product", "product_group", "audience", "briefing", "campaign", "brand", "persona"),
    "asset": ("product", "product_group", "campaign", "brand"),
    "tone": ("brand", "briefing", "campaign"),
    "rule": ("campaign", "briefing", "brand"),
    "other": ("product", "product_group", "audience", "campaign", "brand", "briefing"),
}
```

- [ ] **Step 3: Rodar testes existentes de Sofia**

Run: `python -m pytest tests/test_sofia_create_plan_product_group.py tests/test_create_path_autofix_campaign_audience_product_group.py -q`

Expected: PASS ou falhas que apontem fixtures ainda baseadas em `offer`.

### Task 4: Validar Alvo Semântico Da FAQ No Mesmo Branch

**Files:**
- Modify: `api/services/kb_intake_service.py`
- Test: `tests/test_kb_intake_graph_rules_alignment.py`

- [ ] **Step 1: Usar validação contextual por branch**

Dentro de `validate_sofia_knowledge_plan`, após calcular `parent_type`, adicionar validação contextual. Ela não deve travar o processo por falta de `copy`, `product_group` ou `rule`; deve travar apenas quando o card existe e a conexão escolhida ignora esse contexto mais específico.

```python
def _ancestor_types_for_entry(entry: dict, slug_to_entry: dict[str, dict]) -> set[str]:
    seen: set[str] = set()
    current = entry
    for _ in range(20):
        parent_slug = _entry_parent_slug(current)
        if not parent_slug or parent_slug == "self":
            break
        parent = slug_to_entry.get(parent_slug)
        if not parent:
            break
        parent_type = _entry_type(parent)
        if parent_type:
            seen.add(parent_type)
        current = parent
    return seen

if ctype_lower == "faq":
    branch_types = _ancestor_types_for_entry(entry, slug_to_entry)
    violation = graph_validation.faq_priority_violation(parent_type, branch_types)
    if violation:
        errors.append(f"entry[{idx}] {violation}")

if ctype_lower in {"product", "copy"}:
    available_types = _ancestor_types_for_entry(entry, slug_to_entry)
    if ctype_lower == "product":
        available_types |= {
            _entry_type(candidate)
            for candidate in entries
            if isinstance(candidate, dict) and _entry_type(candidate) == "product_group"
        }
    violation = graph_validation.contextual_parent_violation(ctype_lower, parent_type, available_types)
    if violation:
        errors.append(f"entry[{idx}] {violation}")
```

- [ ] **Step 2: Rodar teste de alvo semântico**

Run: `python -m pytest tests/test_kb_intake_graph_rules_alignment.py::test_faq_parent_priority_is_enforced_by_plan_validator -q`

Expected: PASS; planos sem `copy`, `rule` ou `product_group` continuam válidos quando não há card mais específico no mesmo branch.

### Task 5: Confirmar JSON Antes De Criar Nodes Reais

**Files:**
- Modify: `api/services/kb_intake_service.py`
- Test: `tests/test_create_path_autofix_campaign_audience_product_group.py`

- [ ] **Step 1: Implementar estado de proposta aguardando confirmação**

O `chat()` deve montar `normalized_plan`, mas o `save()` só pode persistir quando a sessão tiver confirmação explícita do operador depois da tradução operacional do JSON.

```python
def _plan_requires_operator_confirmation(session: dict, plan_hash: str) -> bool:
    confirmed_hash = str(session.get("confirmed_plan_hash") or "")
    return not confirmed_hash or confirmed_hash != str(plan_hash or "")
```

No `save()`, antes de persistir:

```python
if _plan_requires_operator_confirmation(session, plan_state.get("plan_hash")):
    return {
        "error": "Confirme o plano no chat antes de salvar.",
        "error_code": "PLAN_CONFIRMATION_REQUIRED",
        "plan_hash": plan_state.get("plan_hash"),
        "plan_state": plan_state,
        "operator_translation": _translate_plan_edges_for_operator(plan_payload),
    }
```

- [ ] **Step 2: Traduzir edges para linguagem operacional**

Adicionar helper:

```python
def _translate_plan_edges_for_operator(plan: dict) -> list[str]:
    entries = {
        str(entry.get("slug")): entry
        for entry in (plan.get("entries") or [])
        if isinstance(entry, dict) and entry.get("slug")
    }
    lines: list[str] = []
    for entry in entries.values():
        child_type = _entry_type(entry)
        parent_slug = _entry_parent_slug(entry)
        if not parent_slug or parent_slug == "self":
            continue
        parent = entries.get(parent_slug) or {}
        parent_type = _entry_type(parent)
        child_title = str(entry.get("title") or entry.get("slug"))
        parent_title = str(parent.get("title") or parent_slug)
        if parent_type == "product_group" and child_type == "product":
            lines.append(f"Esse produto `{child_title}` deve ficar dentro do grupo de produtos `{parent_title}`.")
        elif child_type == "copy":
            lines.append(f"Essa copy `{child_title}` contextualiza `{parent_title}`.")
        elif child_type == "faq":
            lines.append(f"Essa FAQ `{child_title}` responde sobre `{parent_title}`.")
        else:
            lines.append(f"`{parent_title}` contém `{child_title}`.")
    return lines
```

Quando o operador responder "sim", "confirmo", "pode salvar", gravar `session["confirmed_plan_hash"] = session["plan_hash"]`.

- [ ] **Step 3: Rodar teste de confirmação**

Run: `python -m pytest tests/test_create_path_autofix_campaign_audience_product_group.py -q`

Expected: PASS, ajustando expectativas para não exigir criação automática de product_group; exigir apenas que, quando product_group existir, products apontem para ele ou peçam confirmação/correção.

### Task 6: Materializar Relações Primárias Canônicas

**Files:**
- Modify: `api/services/knowledge_graph.py`
- Test: `tests/test_marketing_criacao_kb_intake_flow.py`

- [ ] **Step 1: Atualizar `_DEFAULT_PARENT_RELATION`**

Usar relações de árvore primária:

```python
_DEFAULT_PARENT_RELATION = {
    ("persona", "brand"): "persona_has_brand",
    ("brand", "briefing"): "brand_has_briefing",
    ("brand", "campaign"): "brand_has_campaign",
    ("briefing", "campaign"): "briefing_has_campaign",
    ("campaign", "briefing"): "campaign_has_briefing",
    ("campaign", "audience"): "campaign_has_audience",
    ("briefing", "audience"): "briefing_has_audience",
    ("audience", "product_group"): "audience_has_product_group",
    ("product_group", "product"): "product_group_has_product",
    ("product_group", "copy"): "product_group_has_copy",
    ("product", "copy"): "product_has_copy",
    ("copy", "faq"): "copy_has_faq",
    ("product", "faq"): "product_has_faq",
    ("product_group", "faq"): "product_group_has_faq",
    ("faq", "embedded"): "faq_published_to_embedded",
}
```

- [ ] **Step 2: Atualizar `_default_plan_relation` para chamar o mapa**

```python
def _default_plan_relation(parent_type: Optional[str], child_type: Optional[str]) -> str:
    parent = (parent_type or "").strip().lower()
    child = (child_type or "").strip().lower()
    return _DEFAULT_PARENT_RELATION.get((parent, child), "contains")
```

- [ ] **Step 3: Rodar fluxo de criação**

Run: `python -m pytest tests/test_marketing_criacao_kb_intake_flow.py -q`

Expected: PASS com edges primárias canônicas.

### Task 7: Bloquear Reparo Silencioso Para Persona

**Files:**
- Modify: `api/services/knowledge_graph.py`
- Test: novo teste no `tests/test_kb_intake_graph_rules_alignment.py`

- [ ] **Step 1: Alterar `repair_primary_tree_connections`**

Se o nó não é top-level e não há parent canônico resolvível, marcar quarentena em vez de conectar à persona:

```python
if node.get("node_type") not in {"brand", "briefing"}:
    supabase_client.update_knowledge_node(node["id"], {
        "metadata": {
            **(node.get("metadata") or {}),
            "quarantine_state": "structural",
            "quarantine_reason": "missing_canonical_parent",
        }
    })
    fallback_nodes.append({
        "id": node.get("id"),
        "slug": node.get("slug"),
        "title": node.get("title"),
        "node_type": node.get("node_type"),
        "quarantine_reason": "missing_canonical_parent",
    })
    continue
```

- [ ] **Step 2: Rodar testes de grafo**

Run: `python -m pytest tests/smoke_knowledge_graph.py tests/integration_knowledge_ui_hierarchy.py -q`

Expected: nenhum nó operacional novo cai direto na persona como reparo silencioso.

### Task 8: Tornar Save Atômico Ou Compensável

**Files:**
- Modify: `api/services/kb_intake_service.py`
- Optional later migration: Supabase RPC `persist_knowledge_plan_bulk`
- Test: `tests/e2e_kb_intake_save_capture.py`

- [ ] **Step 1: Curto prazo: validar hierarquia antes de persistir**

Antes de `_write_entry_file` e antes de `persist_pending_knowledge_item`, chamar validação final:

```python
final_violations = validate_sofia_knowledge_plan(plan_payload, session=session)
if final_violations:
    return {
        "error": "Plano viola as regras do grafo.",
        "violations": final_violations,
        "plan_state": _plan_state_from_normalized(plan_payload, session=session, violations=final_violations),
    }
```

- [ ] **Step 2: Médio prazo: implementar RPC transacional**

Seguir `docs/criar-bulk-save-investigation.md`: `public.persist_knowledge_plan_bulk(payload jsonb) returns jsonb`.

O payload deve conter `persona`, `session_id`, `entries`, `links`, `file_paths`, `plan_hash`.

Rollback esperado: se qualquer edge canônica falhar, nenhum `knowledge_item`, `knowledge_node` ou `knowledge_edge` novo fica ativo.

- [ ] **Step 3: Rodar E2E de save**

Run: `python -m pytest tests/e2e_kb_intake_save_capture.py tests/e2e_kb_intake_hierarchy_depth.py -q`

Expected: PASS; em caso de plano inválido, resposta 400 com `violations`, sem item parcialmente salvo.

### Task 9: Publicação De FAQ Para Embedded

**Files:**
- Modify: `api/services/knowledge_lifecycle.py`
- Modify: rota/serviço de aprovação existente em `api/routes/knowledge.py` ou `api/routes/qa_contract.py`
- Test: `tests/test_approved_faq_publication_contract.py`

- [ ] **Step 1: Garantir que FAQ nova nasce pendente**

Em `persist_pending_knowledge_item`, trocar status inicial para:

```python
requested_status = "pending_validation" if content_type == "faq" else "pending"
```

Manter status existente apenas se o conteúdo não mudou e já está validado.

- [ ] **Step 2: Garantir edge FAQ aprovada -> Embedded só na aprovação**

No serviço de aprovação, após status `approved`, criar ou garantir:

```python
knowledge_graph.ensure_faq_published_to_embedded(
    faq_node_id=faq_node["id"],
    persona_id=persona_id,
    approved_by=current_user_id,
)
```

A função deve rejeitar `node_type != "faq"` e `status` diferente de `approved`.

- [ ] **Step 3: Rodar contrato de FAQ aprovada**

Run: `python -m pytest tests/test_approved_faq_publication_contract.py tests/smoke_rag_faq_only_gate.py -q`

Expected: PASS; FAQ pendente não chega ao Embedded.

### Task 10: Limpar Prompt E Mensagens De UI Do Serviço

**Files:**
- Modify: `api/services/kb_intake_service.py`
- Test: `tests/test_criar_entry_flow_summary.py`

- [ ] **Step 1: Remover contradições de prompt**

Substituir trechos que dizem:

```text
product_group é opcional sem precisar confirmar a ligação
product -> offer -> copy
FAQ Golden Dataset
copy SEMPRE filho de offer
```

por:

```text
Product Group é opcional; se existir, traduza a ligação como "esse produto fica dentro do grupo X" e conecte product_group -> product.
Offer não é camada primária; use metadata ou relação secundária quando houver condição comercial.
Copy é opcional; se existir, ela contextualiza Product ou Product Group e a FAQ deve usar esse contexto.
Rule é opcional; se existir, ela adiciona restrição/contexto, mas não bloqueia o fluxo quando ausente.
FAQ fica no alvo semântico mais específico disponível e nasce pending_validation.
O JSON só vira nodes reais depois de confirmação explícita no chat.
Embedded só recebe FAQ aprovada.
```

- [ ] **Step 2: Atualizar resumo visível**

Em `_rewrite_visible_plan_summary`, remover `oferta N` da linha principal ou mover para `metadata/comercial`.

- [ ] **Step 3: Rodar teste de resumo**

Run: `python -m pytest tests/test_criar_entry_flow_summary.py -q`

Expected: resumo não promete offer como camada obrigatória.

## Ordem De Execução Recomendada

1. Task 1: testes de contrato primeiro.
2. Task 2 e Task 3: fonte canônica e remoção de `offer` primário.
3. Task 4 e Task 5: validação contextual e confirmação do JSON antes de persistir.
4. Task 6 e Task 7: materialização e reparo estrutural.
5. Task 8: reduzir risco de persistência parcial.
6. Task 9: aprovação e Embedded.
7. Task 10: limpeza final de prompt/UX.

## Critérios De Aceite

- `product` sem `product_group` é permitido quando não há grupo no plano.
- Se existe `product_group`, Sofia não pode conectar o `product` no node errado; deve conectar `product_group -> product` ou perguntar em linguagem operacional.
- `FAQ` em camada alta é rejeitada apenas quando existe card mais específico disponível no mesmo branch e confirmado.
- `copy` não fica em paralelo ao galho.
- `rule`, `copy` e `product_group` não são obrigatórios e não bloqueiam o processo quando ausentes.
- O JSON proposto só vira `knowledge_nodes` e `knowledge_edges` depois de confirmação explícita no chat.
- `Embedded` só recebe edge de `FAQ approved`.
- Nenhum repair conecta nó operacional direto à Persona sem quarentena explícita.
- Save inválido não deixa `knowledge_items`/`knowledge_nodes` parcialmente ativos.
- Relações primárias usam labels canônicos e previsíveis.

## Comandos De Verificação

```powershell
cd api
python -m py_compile main.py routes\*.py services\*.py core\*.py workers\*.py
cd ..
python -m pytest tests/test_kb_intake_graph_rules_alignment.py -q
python -m pytest tests/test_sofia_create_plan_product_group.py tests/test_create_path_autofix_campaign_audience_product_group.py -q
python -m pytest tests/test_marketing_criacao_kb_intake_flow.py tests/test_approved_faq_publication_contract.py -q
```

## Risco Principal

Há migrações e testes já modelados com `offer` como camada primária. A mudança mais segura é faseada: primeiro bloquear novos planos incoerentes no `kb_intake_service`, depois migrar/compatibilizar dados antigos marcando `offer` como secundário sem apagar histórico.
