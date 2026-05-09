## Fluxo de Conhecimento

A documentacao completa do fluxo, hierarquia e grafo de conhecimento esta em [`docs/knowledge-flow.md`](docs/knowledge-flow.md).

## Start Local

- Backend API: `cd api && uvicorn main:app --reload`
- Workers: `cd api && python -m workers.runner --all`
- Worker unico: `cd api && python -m workers.runner --worker health_check`

---

## Regra de negocio: Cliente = Persona

O Brain AI e operado por donos de agencia de marketing que gerenciam multiplos clientes. O modelo e:

- 1 USER (operador da agencia) -> N CLIENTES.
- 1 CLIENTE = 1 PERSONA (relacao 1:1, sem ambiguidade).
- Cada cliente e identificado pelo cadastro de email (campos basicos opcionais permitidos).
- O filtro "Cliente" na barra superior e o MESMO seletor de Persona usado em telas como `/persona`, `/grafos`, `/leads`, `/messages`, `/pipeline`.
- Trocar persona em qualquer tela DEVE atualizar o filtro Cliente do topo (e vice-versa) via o evento `ai-brain-persona-change` e o par `ai-brain-persona-slug` / `ai-brain-persona-id` no `localStorage`.
- `admin` ve todas as personas/clientes; `user`, `operator`, `viewer` veem apenas o que esta autorizado em `user_persona_access`.

### Estrutura de uma persona/cliente

Cada persona agrega:

- `brand`, `briefing`, `tone`, `rule` -> blocos de conhecimento que enriquecem o contexto.
- `campaign` -> integra com conectores e insights de ferramentas de ADS.
- `audience` (publicos) -> vem do WhatsApp conectado e/ou bulk via CSV (Meta lookalike). Cada publico e ligado ao galho de produtos.
- `product` -> pode futuramente ter conexoes diretas com sites/catalogos.
- `faq` -> conhecimento consolidado retornado aos agentes de IA do WhatsApp (RAG via Embedded/FAQ).
- `asset` em `gallery` (antiga aba Assets) -> imagens vinculaveis ao agente Maker em "Creative Studio" para gerar artes a partir de produtos. (Maker: feature futura, hoje so MOCK visual.)

### Knowledge Flow no Dashboard

O card "Knowledge Flow" do Dashboard tem dois destinos:

- **Brain** -> abre `/knowledge/graph` com `focus=embedded` (KB / RAG do agente conversacional).
- **Maker** -> abre `/knowledge/graph` com `focus=gallery` (galeria de assets do Creative Studio).

---

## Regra de negocio: Grafo vs KB Validada vs RAG

Tres camadas distintas que NUNCA devem ser tratadas como sinonimos:

| Camada               | O que armazena                                          | Tabelas                                             |
|----------------------|---------------------------------------------------------|-----------------------------------------------------|
| **Grafo**            | Todo conhecimento (aprovado, pendente, rascunho)        | `knowledge_nodes`, `knowledge_edges`                |
| **KB Validada**      | Todo conhecimento aprovado (qualquer tipo)              | `kb_entries` (status=`ATIVO`)                       |
| **RAG (vetorial)**   | SOMENTE FAQ aprovado consultavel pelos agentes          | `knowledge_rag_entries`, `knowledge_rag_chunks`     |

### Fluxo canonico

```
Markdown sincronizado / tela CRIAR / intake bulk
        |
        v
knowledge_intake_messages + knowledge_nodes (status=pending|draft)
        |
        v
Tela de aprovacao (/knowledge/validate)
        |
        v
Aprovacao manual -> knowledge_items.status=approved
        |
        +-> SEMPRE: kb_entries (KB Validada, status=ATIVO)
        |
        +-> SE content_type=faq:
                  +-> knowledge_rag_entries
                  +-> knowledge_rag_chunks
                  +-> edge automatica FAQ->Embedded
```

### Regra critica: RAG = FAQ aprovado

Hoje a camada vetorial aceita **somente FAQ**. Produtos, campanhas, regras, copys, briefings, tons de voz e entidades aprovados aparecem na KB Validada e no grafo, mas **NAO** sao enviados para `knowledge_rag_*` enquanto nao forem convertidos em FAQ.

A unica fonte da verdade dessa regra e o helper:

```python
# api/services/knowledge_rag_intake.py
def is_rag_eligible(content_type: str | None) -> bool:
    return (content_type or "").strip().lower() in RAG_ELIGIBLE_CONTENT_TYPES  # {"faq"}
```

Para liberar outro tipo no futuro, adicionar a `RAG_ELIGIBLE_CONTENT_TYPES` (uma linha) — todos os call sites ja consultam esse helper:

- `process_intake` (rota `/knowledge/intake`)
- `process_intake_plan` (rota `/knowledge/intake/plan`)
- `sync_embedded_kb_node` (drag manual no grafo para Embedded)
- `promote_knowledge_item` (aprovacao via `/knowledge/queue/{id}/approve`)

### Edge FAQ -> Embedded

A edge para o node Embedded representa "esta unidade esta ativa no RAG". Por isso:

- Em `promote_knowledge_item`, a edge so e criada automaticamente quando `content_type=faq`.
- No drag manual via UI (`POST /knowledge/graph-edges`), a edge pode ser criada para qualquer tipo (espelho visual em `kb_entries`), mas o efeito colateral de gravar em `knowledge_rag_*` e gateado pelo `is_rag_eligible`.
- Excluir a edge nao apaga o `kb_entries` nem o node — soft delete por design (CLAUDE.md secao 9).

---

## Identidade das agentes no Criar

`Criar` e o nome da ferramenta/tela de captura e construcao de conhecimento. A agente que conversa com o usuario nao deve se apresentar como Criar.

Identidade padrao atual:

- Nome: Sofia
- Papel: agente de inteligencia marketing comercial
- Abertura esperada: "Ola! Eu sou a Sofia. Aprendi bastante sobre marketing para te ajudar a construir conhecimento para tua marca."

Direcao de produto:

- Sofia conduz a criacao de conhecimento comercial e de marketing.
- Em algum momento do fluxo, a conversa podera mudar organicamente para Zaya.
- Zaya sera a agente de marketing visual.
- Essa transicao nao precisa estar ativa agora, mas o backend deve manter suporte a perfis de agente para permitir essa evolucao.

Regra de UX:

- A tela/menu pode se chamar Criar.
- A conversa deve vir da agente ativa, hoje Sofia.
- O modelo nao deve responder "sou o Criar".

---

## 11. WORKFLOWS N8N (FONTE OPERACIONAL)

Este repositório utiliza workflows validados do n8n como base de operação atual.

Os arquivos JSON estão localizados na raiz ou em `integrations/n8n/workflows/`.

---

### 11.1 CRM Vitória Low

Arquivo: `crm-vitoria-low.json`

Função:

- fluxo principal de aquisição e atendimento comercial
- recebe mensagens (WhatsApp)
- processa contexto básico
- insere leads e mensagens no Supabase
- executa lógica comercial (SDR-like)

Observações:

- não possui integração com Maker (conteúdo/design)
- representa o fluxo validado de vendas atual

---

### 11.2 Midware CRM Supabase → Airtable

Arquivo: `midware-crm-supabase-to-airtable.json`

Função:

- sincronização de dados entre Supabase e Airtable
- executado via webhook
- mantém consistência entre:
  - backend (Supabase)
  - interface operacional (Airtable)

---

### 11.3 KB Update Tock

Arquivo: `kb-update-tock.json`

Função:

- atualização periódica da base de conhecimento
- consome dados do Google Sheets
- gera/atualiza embeddings
- alimenta a knowledge_base do sistema

---

## 12. PAPEL DOS WORKFLOWS NO SISTEMA

Atualmente:

- n8n é o motor de execução
- Brain AI é o motor de inteligência

Objetivo:

→ migrar lógica do n8n para o Brain AI progressivamente

---

## 13. ESTRATÉGIA DE MIGRAÇÃO

### Etapa 1
n8n executa → Brain AI observa e aprende

### Etapa 2
Brain AI decide → n8n executa

### Etapa 3
Brain AI executa → n8n removido ou reduzido

---

## 14. IMPORTANTE

Os arquivos JSON do n8n devem ser tratados como:

→ fonte de verdade operacional atual  
→ dataset para evolução do Brain AI  

Eles NÃO devem ser executados diretamente pelo Brain AI.
