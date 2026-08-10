# Investigação Completa: Aurora não responde para Allan

**Data:** 2026-08-10  
**Lead:** Allan (VZ Lupas `lead_ref=41` ↔ Aurora `lead_ref=29` exibido como Vitória)  
**Status:** IA ligada, MAS não responde

---

## 📋 Checklist de Diagnóstico

### 1. Estado da Conversa

**Última informação conhecida (2026-08-04):**
- Aurora estava em estado `HANDOFF/PAUSA`
- Causa: detectou grafo desatualizado (v5 → v7)
- Mensagens ficavam em `buffered` sem processar
- Ao retomar manualmente, gerava respostas duplicadas

**Cenário atual (2026-08-10 agora):**
- IA está LIGADA (conforme você relata)
- Mas não responde a mensagens
- Provavelmente ainda em estado `HANDOFF` ou com fila travada

### 2. Diagnóstico - 5 Cenários Possíveis

#### ❓ Cenário A: Aurora em HANDOFF/PAUSA
```
Sintoma:   IA ligada, sem resposta
Causa:     Estado HANDOFF não foi limpo
Duração:   > 6 dias (desde 2026-08-04)
Solução:   Resume conversation
```

#### ❓ Cenário B: Fila de Mensagens Travada
```
Sintoma:   Mensagens em "buffered"
Causa:     Worker de processamento parado/morto
Duração:   Variável
Solução:   Reiniciar workers
```

#### ❓ Cenário C: Webhook Quebrado
```
Sintoma:   IA liga, pero não recebe inbound
Causa:     Webhook Evolution falhando
Duração:   Desde última falha
Solução:   Verificar Evolution binding
```

#### ❓ Cenário D: Grafo Ainda Desatualizado
```
Sintoma:   IA processa, mas não consegue classificar
Causa:     Grafo v5 vs v7 conflito
Duração:   > 6 dias
Solução:   Migrar grafo atomicamente
```

#### ❓ Cenário E: Contexto Corrompido
```
Sintoma:   IA ligada, sem erro, silêncio
Causa:     Histórico de Ford Ka bloqueando novo intent
Duração:   Indefinida
Solução:   Limpar contexto (apenas novo fluxo)
```

---

## 🔍 Dados a Coletar (Ações Necessárias)

Para diagnosticar corretamente, preciso de:

### A. Estado da Conversa
```sql
-- Query: Estado atual de Aurora/Allan
SELECT 
  conversation_id,
  lead_ref,
  state,           -- HANDOFF? ACTIVE? PAUSED?
  last_message_at,
  last_agent_state,
  metadata
FROM conversations
WHERE lead_ref = 29 OR lead_ref = 41
ORDER BY last_message_at DESC
LIMIT 5;
```

### B. Últimas Mensagens
```sql
-- Query: Últimas 10 mensagens
SELECT 
  id,
  created_at,
  sender_type,    -- bot? human? agent?
  direction,      -- Inbound? Outbound?
  status,         -- sent? buffered? failed?
  texto,
  metadata
FROM messages
WHERE lead_ref = 29
ORDER BY created_at DESC
LIMIT 10;
```

### C. Eventos de Processamento
```sql
-- Query: Últimos eventos
SELECT 
  event_type,
  entity_type,
  entity_id,
  payload,
  created_at
FROM events
WHERE (entity_id = '29' OR entity_id = '41')
  AND event_type IN ('handoff_initiated', 'ai_paused', 'ai_resumed', 'message_received')
ORDER BY created_at DESC
LIMIT 20;
```

### D. Logs de Worker
```bash
# Procurar por erros de processamento
grep -i "aurora\|lead.*29\|handoff" /var/log/api/*.log | tail -100

# Procurar por exceções
grep -i "error\|exception" /var/log/api/*.log | grep -E "29|Aurora" | tail -50
```

### E. Estado do N8N (SDR)
```bash
# Verificar se workflows de Aurora estão rodando
curl -X GET https://your-n8n.com/api/v1/workflows \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  | jq '.[] | select(.name | test("aurora|Aurora")) | {id, name, active}'
```

---

## 💡 Hipótese Mais Provável

Com base nos dados de 2026-08-04, minha **hipótese principal** é:

### **Aurora ainda está em estado HANDOFF**

**Evidência:**
- Entrou em HANDOFF em 2026-08-04 01:35:50Z
- Razão: `graph_version_changed`
- Nunca foi formally `resume`d
- 6 dias sem resposta = consistente com estado travado

**Por que IA está ligada?**
- Lead foi `resume_lead()` em algum ponto
- Mas Aurora nunca saiu do HANDOFF internamente
- IA processa, mas handoff bloqueia respostas

**Como confirmar:**
```python
# Checar estado em tempo real
lead = get_lead_by_ref(29)  # Aurora/Vitória
conversation = get_conversation(lead_id=29)
print(f"Conversation state: {conversation.state}")
print(f"AI paused: {lead.ai_paused}")
print(f"Last message: {conversation.last_message_at}")
print(f"Handoff pending: {conversation.handoff_required}")
```

---

## 🔧 Próximas Ações (Ordenadas por Probabilidade)

### Passo 1: Verificar Estado (SEM MUDANÇA)
```bash
# Chamar endpoint /by-ref para ver estado
curl -X GET https://brain-plataform-plum.vercel.app/leads/29 \
  -H "Authorization: Bearer YOUR_TOKEN" | jq '.state, .ai_paused, .handoff'
```

### Passo 2: Se em HANDOFF → Resume
```bash
# Se confirmado em HANDOFF, retomar
curl -X POST https://brain-plataform-plum.vercel.app/leads/29/resume-ai \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Passo 3: Se Ainda Sem Resposta → Limpar Contexto
```bash
# Se resume não funcionar, limpar histórico de Ford Ka
# (SEM hardcode, apenas próximo fluxo)
UPDATE conversation_context
SET appointment_request = JSON_BUILD_OBJECT()
WHERE lead_ref = 29;
```

### Passo 4: Se Ainda Sem Resposta → Verificar Worker
```bash
# Verificar se worker de processamento está vivo
curl -X GET https://brain-plataform-plum.vercel.app/health | jq '.workers'
```

---

## 📊 Checklist Executável

- [ ] **Coletar dados** via queries SQL acima
- [ ] **Confirmar estado** = HANDOFF, PAUSED, ou OK?
- [ ] **Se HANDOFF** → Execute Step 2 (resume)
- [ ] **Testar** → Enviar mensagem, aguardar 10s
- [ ] **Se falhar** → Execute Step 3 (limpar contexto)
- [ ] **Se falhar** → Execute Step 4 (verificar worker)
- [ ] **Documentar** achados aqui

---

## 📝 O Que NÃO Fazer

❌ **NÃO fazer:**
- ❌ Hardcoded fixes específicas para Aurora
- ❌ Forçar migração v5→v7
- ❌ Locks de idempotência
- ❌ Deletar histórico completo

✅ **Fazer:**
- ✅ Resume genérico (qualquer conversa)
- ✅ Deixar bot escolher contexto
- ✅ Permitir multi-persona
- ✅ Sem travamentos

---

**Status:** Aguardando dados para diagnóstico  
**Próximo:** Execute queries acima e reporte findings

