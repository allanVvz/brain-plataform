---
{
  "type": "briefing",
  "persona": "baita-conveniencia",
  "slug": "checkout-vitoria",
  "title": "Checkout da Vitoria",
  "source": "sources/operator-policy.md",
  "status": "validated",
  "active": true,
  "tags": ["baita", "briefing", "checkout"],
  "metadata": {
    "final_state": "confirmed_pending_human",
    "required_fields": ["customer_name", "address"]
  },
  "relations": [
    {"relation_type": "briefed_by", "target": "baita"}
  ]
}
---

Depois de resumir os itens, quantidades e total, coletar nome e endereço e pedir
confirmação. Uma confirmação cria o estado `confirmed_pending_human`, pausa a IA
e transfere o atendimento.
