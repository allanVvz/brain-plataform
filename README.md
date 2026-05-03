## Fluxo de Conhecimento

A documentacao completa do fluxo, hierarquia e grafo de conhecimento esta em [`docs/knowledge-flow.md`](docs/knowledge-flow.md).

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
- AI Brain é o motor de inteligência

Objetivo:

→ migrar lógica do n8n para o AI Brain progressivamente

---

## 13. ESTRATÉGIA DE MIGRAÇÃO

### Etapa 1
n8n executa → AI Brain observa e aprende

### Etapa 2
AI Brain decide → n8n executa

### Etapa 3
AI Brain executa → n8n removido ou reduzido

---

## 14. IMPORTANTE

Os arquivos JSON do n8n devem ser tratados como:

→ fonte de verdade operacional atual  
→ dataset para evolução do AI Brain  

Eles NÃO devem ser executados diretamente pelo AI Brain.
