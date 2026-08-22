# Backlog conhecido — revisão Lia/Aurora

- Mensagens com várias perguntas podem ter somente uma FAQ escolhida de forma
  determinística pelo runtime atual.
- O fast lane não pula campos condicionalmente com base no momento de compra.
- Agenda, preços, promoções, endereço e disponibilidade não são dinâmicos.
- Pacotes podem ser sugeridos, mas a Lia não calcula preço nem desconto.
- Fotos e vídeos apoiam a triagem, mas não garantem diagnóstico visual completo.
- Follow-ups e mensagem de ausência permanecem copy publicada, sem disparo
  automático nesta entrega.
- Áudio recebido pode ser transcrito; não há asset nem integração autorizados
  para áudio padrão de saída.
- A migração da Aurora para GraphBundle continua bloqueada pelo item 6 do roadmap
  e pelo P0 ainda aberto.
- As transcrições do Briefing, PDF e prints dependem do reenvio dos arquivos.
- Validação E2E depende de publicação válida e de autorização separada; deve usar
  somente o WA Validator direto, nunca WhatsApp real.
