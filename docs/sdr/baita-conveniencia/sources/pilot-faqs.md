---
{
  "type": "source",
  "persona": "baita-conveniencia",
  "slug": "pilot-faqs-original",
  "title": "FAQ factual do piloto ? evid?ncia migrada",
  "source": "api/scripts/publish_baita_pilot_faqs.py:SPECS",
  "status": "validated",
  "active": true,
  "tags": [
    "baita",
    "source",
    "faq"
  ],
  "metadata": {
    "sha256": "36ca10ee2db309508f9059e4a5d34b3bd65a36a12e2ad5414275d14b60f604d5",
    "faq_count": 20,
    "copy_count": 17
  },
  "relations": [
    {
      "relation_type": "derived_from",
      "target": "operator-policy"
    }
  ]
}
---

```json
[
  {
    "index": 1,
    "kind": "brand",
    "parent": "Baita",
    "question": "O que é a Baita Conveniência?",
    "answer": "A Baita Conveniência tem o Cardápio Baita v14 como referência comercial do piloto, com bebidas, alimentos e itens de tabacaria cadastrados.",
    "source": "baita_pilot_operator_policy",
    "parent_slug": "baita",
    "copy_slug": null,
    "faq_slug": "faq-baita-pilot-01-baita"
  },
  {
    "index": 2,
    "kind": "brand",
    "parent": "Baita",
    "question": "O que posso consultar pelo atendimento da Baita?",
    "answer": "Posso consultar itens, variações e preços cadastrados no Cardápio Baita v14. Horário, entrega, pagamento, estoque e disponibilidade são confirmados pelo atendimento humano.",
    "source": "baita_pilot_operator_policy",
    "parent_slug": "baita",
    "copy_slug": null,
    "faq_slug": "faq-baita-pilot-02-baita"
  },
  {
    "index": 3,
    "kind": "campaign",
    "parent": "Campanha principal",
    "question": "Qual é a campanha atual da Baita?",
    "answer": "No piloto, o Cardápio Baita v14 é a referência comercial vigente. Os valores informados vêm desse cardápio; disponibilidade e condições do pedido são confirmadas pelo atendimento.",
    "source": "baita_pilot_operator_policy",
    "parent_slug": "cardapio-baita-v14",
    "copy_slug": null,
    "faq_slug": "faq-baita-pilot-03-campanha-principal"
  },
  {
    "index": 4,
    "kind": "product_group",
    "parent": "Cervejas",
    "question": "Quais cervejas aparecem no cardápio Baita?",
    "answer": "O cardápio Baita inclui cervejas em lata, long neck e 600 ml. Posso consultar um rótulo específico e o preço cadastrado; o atendimento confirma a disponibilidade.",
    "source": "baita_full_menu_seed",
    "parent_slug": "cervejas",
    "copy_slug": "copy-baita-pilot-04-cervejas",
    "faq_slug": "faq-baita-pilot-04-cervejas"
  },
  {
    "index": 5,
    "kind": "product_group",
    "parent": "Energeticos",
    "question": "Quais energéticos aparecem no cardápio Baita?",
    "answer": "No cardápio Baita há opções de energéticos como Baly, Red Bull e Monster. Posso consultar as variações cadastradas e seus preços; estoque é confirmado pelo atendimento.",
    "source": "baita_full_menu_seed",
    "parent_slug": "energeticos",
    "copy_slug": "copy-baita-pilot-05-energeticos",
    "faq_slug": "faq-baita-pilot-05-energeticos"
  },
  {
    "index": 6,
    "kind": "product_group",
    "parent": "Refrigerantes / Sucos / Chas",
    "question": "Quais refrigerantes e sucos aparecem no cardápio Baita?",
    "answer": "O cardápio Baita reúne refrigerantes, sucos e chás em diferentes embalagens. Posso verificar o item e o preço cadastrados; o atendimento confirma disponibilidade.",
    "source": "baita_full_menu_seed",
    "parent_slug": "refrigerantes-sucos-chas",
    "copy_slug": "copy-baita-pilot-06-refrigerantes-sucos-chas",
    "faq_slug": "faq-baita-pilot-06-refrigerantes-sucos-chas"
  },
  {
    "index": 7,
    "kind": "product_group",
    "parent": "Destilados",
    "question": "Quais destilados aparecem no cardápio Baita?",
    "answer": "O cardápio Baita inclui destilados como whisky, licor e outras bebidas da categoria. Posso consultar um rótulo específico e o preço cadastrado; o atendimento confirma disponibilidade.",
    "source": "baita_full_menu_seed",
    "parent_slug": "destilados",
    "copy_slug": "copy-baita-pilot-07-destilados",
    "faq_slug": "faq-baita-pilot-07-destilados"
  },
  {
    "index": 8,
    "kind": "product_group",
    "parent": "Bomboniere",
    "question": "O que encontro na bomboniere da Baita?",
    "answer": "A bomboniere do cardápio Baita reúne snacks, chocolates e itens semelhantes. Posso consultar um produto específico e o preço cadastrado; o atendimento confirma disponibilidade.",
    "source": "baita_full_menu_seed",
    "parent_slug": "bomboniere",
    "copy_slug": "copy-baita-pilot-08-bomboniere",
    "faq_slug": "faq-baita-pilot-08-bomboniere"
  },
  {
    "index": 9,
    "kind": "product",
    "parent": "COCA COLA TRADICIONAL / SEM ACUCAR 600ML",
    "question": "Qual é o preço da Coca-Cola 600 ml?",
    "answer": "No card?pio Baita, Coca-Cola tradicional ou sem açúcar 600 ml est? cadastrado por R$ 8. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "refrigerantes-sucos-chas-coca-cola-tradicional-sem-acucar-600ml",
    "copy_slug": "copy-baita-pilot-09-coca-cola-tradicional-sem-acucar-600ml",
    "faq_slug": "faq-baita-pilot-09-coca-cola-tradicional-sem-acucar-600ml"
  },
  {
    "index": 10,
    "kind": "product",
    "parent": "BALY MACA VERDE / MORANGO E PESSEGO / TRADICIONAL / SEM ACUCAR 473ML",
    "question": "Quais Baly 473 ml estão no cardápio e qual o preço?",
    "answer": "No card?pio Baita, Baly 473 ml nas variações maçã verde, morango e pêssego, tradicional e sem açúcar est? cadastrado por R$ 10. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "energeticos-baly-maca-verde-morango-e-pessego-tradicional-sem-acucar-473ml",
    "copy_slug": "copy-baita-pilot-10-baly-maca-verde-morango-e-pessego-tradicional-sem-acucar-473ml",
    "faq_slug": "faq-baita-pilot-10-baly-maca-verde-morango-e-pessego-tradicional-sem-acucar-473ml"
  },
  {
    "index": 11,
    "kind": "product",
    "parent": "RED BULL TRADICIONAL / FRUTAS TROPICAIS / MACA SEM ACUCAR / MELANCIA / MELAO MARACUJA / MORANGO E PESSEGO / NECTARINA / SUGAR FREE / SUGAR FREE AMORA / SUGAR FREE POMELO / ZERO 250ML",
    "question": "Quais Red Bull 250 ml estão no cardápio e qual o preço?",
    "answer": "No card?pio Baita, Red Bull 250 ml em variações como tradicional, frutas tropicais, melancia, sugar free e zero est? cadastrado por R$ 15. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "red-bull-250ml",
    "copy_slug": "copy-baita-pilot-11-red-bull-tradicional-frutas-tropicais-maca-sem-acucar-melancia-melao-maracuja-morango-e-pessego-nectarina-sugar-free-sugar-free-amora-sugar-free-pomelo-zero-250ml",
    "faq_slug": "faq-baita-pilot-11-red-bull-tradicional-frutas-tropicais-maca-sem-acucar-melancia-melao-maracuja-morango-e-pessego-nectarina-sugar-free-sugar-free-amora-sugar-free-pomelo-zero-250ml"
  },
  {
    "index": 12,
    "kind": "product",
    "parent": "MONSTER ABSOLUT ZERO / DRAGON ICE TEA LIMAO / ENERGY ZERO ACUCAR / KHAOTIC / MANGO LOCO / PACIFIC PUNCH / PEACHY KEEN / PIPELINE PUNCH / RIO PUNCH / THE DOCTOR LT / ULTRA FIESTA MANGO / ULTRA / ULTRA STRAWBERRY DREAM / ULTRA VIOLET 473ML",
    "question": "Quais Monster 473 ml estão no cardápio?",
    "answer": "No cardápio Baita há Monster 473 ml em variações cadastradas como Mango Loco, Pacific Punch, Ultra e Zero Açúcar. O atendimento confirma preço, estoque e disponibilidade.",
    "parent_slug": "energeticos-monster-absolut-zero-dragon-ice-tea-limao-energy-zero-acucar-khaotic-mango-loco-pacific-punch-peachy-keen-pipeline-punch-rio-punch-the-doctor-lt-ultra-fiesta-mango-ultra-ultra-strawberry-dream-ultra-violet-473ml",
    "copy_slug": "copy-baita-pilot-12-monster-absolut-zero-dragon-ice-tea-limao-energy-zero-acucar-khaotic-mango-loco-pacific-punch-peachy-keen-pipeline-punch-rio-punch-the-doctor-lt-ultra-fiesta-mango-ultra-ultra-strawberry-dream-ultra-violet-473ml",
    "faq_slug": "faq-baita-pilot-12-monster-absolut-zero-dragon-ice-tea-limao-energy-zero-acucar-khaotic-mango-loco-pacific-punch-peachy-keen-pipeline-punch-rio-punch-the-doctor-lt-ultra-fiesta-mango-ultra-ultra-strawberry-dream-ultra-violet-473ml"
  },
  {
    "index": 13,
    "kind": "product",
    "parent": "AMSTEL LATA 473 ML",
    "question": "Qual é o preço da Amstel lata 473 ml?",
    "answer": "No card?pio Baita, Amstel lata 473 ml est? cadastrado por R$ 9. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "cervejas-amstel-lata-473-ml",
    "copy_slug": "copy-baita-pilot-13-amstel-lata-473-ml",
    "faq_slug": "faq-baita-pilot-13-amstel-lata-473-ml"
  },
  {
    "index": 14,
    "kind": "product",
    "parent": "BUDWEISER LATA 473ML",
    "question": "Qual é o preço da Budweiser lata 473 ml?",
    "answer": "No card?pio Baita, Budweiser lata 473 ml est? cadastrado por R$ 8. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "cervejas-budweiser-lata-473ml",
    "copy_slug": "copy-baita-pilot-14-budweiser-lata-473ml",
    "faq_slug": "faq-baita-pilot-14-budweiser-lata-473ml"
  },
  {
    "index": 15,
    "kind": "product",
    "parent": "SKOL BEATS GT / RED MIX/ TROPICAL LATA 269ML",
    "question": "Quais Skol Beats 269 ml aparecem no cardápio?",
    "answer": "No card?pio Baita, Skol Beats GT, Red Mix e Tropical em lata 269 ml est? cadastrado por R$ 11. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "bebidas-em-lata-skol-beats-gt-red-mix-tropical-lata-269ml",
    "copy_slug": "copy-baita-pilot-15-skol-beats-gt-red-mix-tropical-lata-269ml",
    "faq_slug": "faq-baita-pilot-15-skol-beats-gt-red-mix-tropical-lata-269ml"
  },
  {
    "index": 16,
    "kind": "product",
    "parent": "WHISKY WHITE HORSE 1L",
    "question": "Qual é o preço do Whisky White Horse 1 L?",
    "answer": "No card?pio Baita, Whisky White Horse 1 L est? cadastrado por R$ 104,99. Item de catálogo para maiores de idade. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "destilados-whisky-white-horse-1l",
    "copy_slug": "copy-baita-pilot-16-whisky-white-horse-1l",
    "faq_slug": "faq-baita-pilot-16-whisky-white-horse-1l"
  },
  {
    "index": 17,
    "kind": "product",
    "parent": "LICOR JAGERMEISTER ORANGE 1L",
    "question": "Qual é o preço do Licor Jägermeister Orange 1 L?",
    "answer": "No card?pio Baita, Licor Jägermeister Orange 1 L est? cadastrado por R$ 259,90. Item de catálogo para maiores de idade. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "destilados-licor-jagermeister-orange-1l",
    "copy_slug": "copy-baita-pilot-17-licor-jagermeister-orange-1l",
    "faq_slug": "faq-baita-pilot-17-licor-jagermeister-orange-1l"
  },
  {
    "index": 18,
    "kind": "product",
    "parent": "VINHO GATO NEGRO CABERNET SAUV / CARMENERE / MALBEC / MERLOT 750ML",
    "question": "Quais vinhos Gato Negro 750 ml estão no cardápio e qual o preço?",
    "answer": "No card?pio Baita, Vinho Gato Negro 750 ml nas variações Cabernet Sauvignon, Carmenere, Malbec e Merlot est? cadastrado por R$ 44,90. Item de catálogo para maiores de idade. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "espumantes-e-vinhos-vinho-gato-negro-cabernet-sauv-carmenere-malbec-merlot-750ml",
    "copy_slug": "copy-baita-pilot-18-vinho-gato-negro-cabernet-sauv-carmenere-malbec-merlot-750ml",
    "faq_slug": "faq-baita-pilot-18-vinho-gato-negro-cabernet-sauv-carmenere-malbec-merlot-750ml"
  },
  {
    "index": 19,
    "kind": "product",
    "parent": "AMENDOIM JAPONES 145G",
    "question": "Qual é o preço do amendoim japonês 145 g?",
    "answer": "No card?pio Baita, amendoim japonês 145 g est? cadastrado por R$ 8,49. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "salgadinhos-amendoim-japones-145g",
    "copy_slug": "copy-baita-pilot-19-amendoim-japones-145g",
    "faq_slug": "faq-baita-pilot-19-amendoim-japones-145g"
  },
  {
    "index": 20,
    "kind": "product",
    "parent": "SEDA BEM BOLADO BROWN 1 1/4 LARGE",
    "question": "Qual é o preço da Seda Bem Bolado Brown 1 1/4 Large?",
    "answer": "No card?pio Baita, Seda Bem Bolado Brown 1 1/4 Large est? cadastrado por R$ 6. Item de catálogo para maiores de idade. Estoque, pedido e disponibilidade s?o confirmados pelo atendimento.",
    "parent_slug": "sedas-seda-bem-bolado-brown-1-1-4-large",
    "copy_slug": "copy-baita-pilot-20-seda-bem-bolado-brown-1-1-4-large",
    "faq_slug": "faq-baita-pilot-20-seda-bem-bolado-brown-1-1-4-large"
  }
]
```
