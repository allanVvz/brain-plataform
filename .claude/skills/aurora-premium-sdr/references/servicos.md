# Catálogo real da Aurora

Fonte: `api/scripts/fixtures/aurora_graph_v2.json` (nós `service`/`product`
sob `aurora-services`), publicação ativa em produção. Todo produto tem
`price_qualifier: "quote_only"` — o preço nunca é dito pela IA, sempre
depende de avaliação/orçamento pela Equipe Aurora.

## Branches de serviço (não são produtos agendáveis — encaminham para humano)

### Atendimento com um humano (`atendimento-humano`)
Cliente pede explicitamente para falar com um atendente humano, sem querer
seguir a qualificação automática de um serviço.
- Aliases: atendente humano, falar com humano, falar com uma pessoa,
  atendente, pessoa de verdade, suporte humano, sac humano, falar com alguem.
- Campo obrigatório: só `nome_cliente`. Encaminha assim que o nome é
  conhecido, sem exigir qualificação de veículo/serviço.

### Reclamação ou problema com um serviço (`reclamacao`)
Cliente relata um problema ou insatisfação com um serviço **já realizado**
e quer registrar uma reclamação.
- Aliases: reclamação, reclamar, problema, insatisfeito, não gostei,
  reclame aqui, tive um problema.
- Campos obrigatórios: `nome_cliente` + `reclamacao_relato`.
- Regra: "Reclamação é sempre assunto de humano ... A IA acolhe com
  empatia, registra o relato e o nome, e encaminha -- nunca tenta resolver,
  justificar ou oferecer desconto sozinha."
- **Importante**: essa branch só deve ser selecionada quando o cliente
  efetivamente menciona um problema/insatisfação real. Um bug de produção
  (2026-08-14) fez a Aurora entrar nessa branch sem o cliente ter dito nada
  do tipo — ver `exemplos-de-conversas.md`.

## Produtos agendáveis (todos exigem avaliação/orçamento humano)

| Produto | Slug | O que é |
|---|---|---|
| Avaliação presencial | `avaliacao-inicial` | Avaliação do veículo, rápida e sem custo, para a Equipe Aurora montar o orçamento. |
| Lavagem detalhada | `lavagem-detalhada` | Lavagem técnica: frisos, cantinhos, emblemas, caixas de rodas, portas, consoles e painel, com aspiração e produto revitalizador nos plásticos. |
| Higienização interna | `higienizacao-interna` | Higienização interna completa, do teto ao carpete, com hidratação quando o banco é de couro. |
| Polimento técnico | `polimento-tecnico` | Correção mais detalhada da pintura, feita após avaliação e medição do verniz. Remove/reduz riscos, hologramas, manchas e marcas de lavagem. |
| Vitrificação | `vitrificacao` | Mesmo processo do polimento técnico, com aplicação final do vitrificador como camada de proteção química. |
| PPF (película de proteção física) | `ppf` | Proteção contra pequenos impactos, pedras, marcas de chuva ácida e fezes de pássaros. |
| Polimento de vidros | `polimento-de-vidros` | Reduz manchas minerais, marcas de chuva ácida e pequenas imperfeições no vidro. |
| Chapeação | `chapeacao` | Processo explicado pela Equipe Aurora. |
| Pintura | `pintura` | Processo explicado pela Equipe Aurora. |
| Polimento comercial | `polimento-comercial` | Processo rápido pra recuperar brilho e reduzir marcas leves. Preço mais acessível, não remove riscos profundos. |
| Polimento de uma etapa | `polimento-uma-etapa` | Corte leve e acabamento em uma única etapa. Pinturas com poucos defeitos. |
| Polimento em múltiplas etapas | `polimento-multiplas-etapas` | Etapas separadas de corte, refino e lustro. Pinturas mais danificadas ou acabamento superior. |
| Polimento localizado | `polimento-localizado` | Aplicado só numa peça/região específica (porta, capô, área riscada). |
| Polimento de acabamento (lustro) | `polimento-acabamento` | Melhora o brilho, remove pequenas marcas/hologramas, pouca ou nenhuma correção profunda. |
| Restauração de faróis | `restauracao-de-farois` | Recupera faróis amarelados/opacos, geralmente com proteção UV depois. |

**Atenção às variações de "polimento"**: existem 6 produtos diferentes com
"polimento" no nome/descrição (`polimento-tecnico`, `polimento-de-vidros`,
`polimento-comercial`, `polimento-uma-etapa`, `polimento-multiplas-etapas`,
`polimento-localizado`, `polimento-acabamento` — na verdade 7). Uma resposta
genérica do cliente como "quero polimento" é ambígua entre vários — é
exatamente esse tipo de caso que deveria disparar um esclarecimento (ver
`SKILL.md`), não uma seleção no achismo.

## Campos de qualificação (nível persona, compartilhados entre produtos)

`nome_cliente`, `servico`, `objective`, `can_visit_in_person`,
`modelo_veiculo`, `vehicle_year`, `condicao` (obrigatórios), `vehicle_color`
(condicional — só para `polimento-tecnico`, `vitrificacao`, `chapeacao`,
`pintura`).
