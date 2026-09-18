# Fila unificada de mensagens e reativação contextual

Status: em execução — a tela de lotes foi substituída por uma fila global operacional de `lead_buffer`. Ela mostra somente mensagens ativas: pendentes em vermelho, previews prontos e mensagens enviadas em verde até a próxima resposta da lead. Histórico e filtro por lead não fazem parte desta tela.

`lead_buffer` é o buffer canônico; `messages` fornece a linha do tempo e `conversation_turn_proofs` prova somente a resposta normal ao inbound canônico. Mensagens proativas terão identidade e proof próprios e nunca reutilizarão o inbound.

O reprocessamento de uma falha técnica não reenvia um outbound antigo: ele reclama o inbound canônico sem proof, gera uma nova resposta `preview_ready` com proof e só a ação explícita `Enviar preview` a libera. Pausar, retomar e gerar/enviar preview não pedem motivo; cada ação continua auditada em `system_events`.

Próximas etapas: publicar por persona a regra e copies de horário no GraphBundle, tornar o runtime consumidor apenas desses nodes publicados e validar aviso único/reativação no WA Validator interno antes de ativar envio proativo.
