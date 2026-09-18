# Fila unificada de mensagens e reativação contextual

Status: em execução — primeira entrega substitui a tela de lotes pela fila global de `lead_buffer`, com preview, filtros, histórico e controles auditáveis por item/lote.

`lead_buffer` é o buffer canônico; `messages` fornece a linha do tempo e `conversation_turn_proofs` prova somente a resposta normal ao inbound canônico. Mensagens proativas terão identidade e proof próprios e nunca reutilizarão o inbound.

Próximas etapas: publicar por persona a regra e copies de horário no GraphBundle, tornar o runtime consumidor apenas desses nodes publicados e validar aviso único/reativação no WA Validator interno antes de ativar envio proativo.
