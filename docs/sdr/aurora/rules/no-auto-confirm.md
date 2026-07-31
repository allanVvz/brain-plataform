---
{
  "type": "rule",
  "persona": "aurora",
  "slug": "nunca-confirmar-preco-ou-agenda",
  "title": "Nunca confirmar preço ou agenda automaticamente",
  "source": "user_authorized_demo_briefing_2026_07_29",
  "status": "validated",
  "active": true,
  "tags": ["aurora", "rule", "safety"],
  "metadata": {
    "on_completed_qualification": "handoff",
    "handoff_team": "Equipe Aurora (Guilherme e Danielle)",
    "enforced_by": [
      "services/deterministic_appointment.py (DeterministicAppointment.handle)",
      "services/conversation_runtime.py (_reply_confirms_price_or_schedule, commit())",
      "n8n-workflows/aurora-conversation.json (Merge model reply safely)"
    ]
  },
  "relations": [
    {"relation_type": "belongs_to_persona", "target": "aurora"}
  ]
}
---

Valor final, data e horário dependem sempre de confirmação humana da Equipe
Aurora. O agente (determinístico ou reescrito pelo DeepSeek) só pode
apresentar valores demonstrativos já aprovados no grafo, nunca fechar um
preço nem confirmar um agendamento.

Essa regra é aplicada em três camadas independentes, para que uma falha em
uma delas não quebre a garantia:

1. **Motor determinístico** — `DeterministicAppointment` nunca gera uma
   resposta de confirmação; ao coletar todos os campos obrigatórios, sempre
   encerra com `handoff=True` e um texto que remete a decisão à equipe.
2. **n8n** — o node `Merge model reply safely` descarta qualquer reescrita
   do DeepSeek que combine linguagem de confirmação ("confirmado",
   "fechado", "reservado", "agendado para") com um valor em R$ ou uma
   data/horário, mantendo o texto determinístico original nesse caso.
3. **Servidor** — `conversation_runtime.commit()` roda a mesma checagem
   (`_reply_confirms_price_or_schedule`) antes de enfileirar qualquer
   resposta para o cliente, independentemente da origem (determinístico ou
   n8n), e força handoff se algo escapar das camadas anteriores.

Quando a qualificação termina (nome, veículo, objetivo, trilha
presencial/remoto e serviço de interesse coletados), a conversa é
encaminhada para a Equipe Aurora e a IA é pausada
(`handoff_whatsapp_lead_state`) até um humano retomar.
