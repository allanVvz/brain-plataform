# Edição e publicação de conhecimento

## Uso diário

1. Escolha a persona no seletor global.
2. Abra **Grafo** e selecione **Editar grafo**. A aplicação cria ou reutiliza o
   draft aberto da persona.
3. Edite nodes e relações. Persona, Embedded e Gallery são protegidos.
4. Quando um fato mudar, confira o aviso de FAQs afetadas. Elas voltam para
   revisão; mover nodes não gera conteúdo nem custo.
5. Abra **Base de conhecimento**, edite as FAQs e aprove ou rejeite em lote.
6. Use **Revisar alterações → Publicar revisão**. O documento e o checksum
   revisados são exatamente os usados por stage e activate.
7. Confira publicação, executor e credencial mascarada no drawer do SDR.

Em **Mensagens**, o painel preserva conhecimento histórico, publicação,
checksum e evidências do turno. **Corrigir no rascunho** altera o mesmo draft e
nunca reescreve a conversa passada.

## FAQ e Embedded

FAQ nova ou alterada nasce `pending_validation`. Aprovar exige fonte válida,
muda o estado para `validated` e cria uma única edge `publishes_to` para o
Embedded. Rejeitar remove somente essa projeção. Entry e chunk são criados no
stage apenas para FAQ aprovada; embedding é reutilizado somente com checksum,
modelo e dimensão idênticos.

## Agente SDR

O drawer e Configurações leem a mesma resolução. Verifique papel, estado,
executor, workflow, provider/modelo, prompt efetivo, publicação e referência
mascarada da credencial. Uma integração cadastrada mas não ligada ao executor é
mostrada como indisponível, com o motivo.

Em `n8n_agents`, cada agente usa uma instância do template canônico. Alterar a
chave ou integração afeta somente o agente selecionado. Segredos nunca são
carregados no grafo ou devolvidos ao navegador.

## Falhas e conflitos

- `409`: a interface recarrega revisão e checksum atuais sem expor outra
  persona. Reaplique a alteração sobre essa revisão.
- FAQ impactada: revise pergunta/resposta e aprove novamente.
- Stage concluído e resposta interrompida: repita Publicar; a mesma chave retoma
  o mesmo `publication_id` e apenas executa activate.
- CAS da publicação ativa: o draft é preservado para revisão contra a nova
  publicação; nunca force o swap.
- Telemetria antiga incompleta: mostre “evidência não registrada”; não substitua
  pelo conhecimento atual.

## Telemetria posterior

WA Validator é uma origem de telemetria interna, não aprovação do grafo. Cada
turno distingue conteúdo recuperado, citado e autorizado pelo proof e registra
inbound canônico, persona, agente, executor, workflow/modelo, publicação,
checksum, decision/proof e no máximo um outbound. Nenhum teste envia WhatsApp
real.

## Release técnica

Edição de conhecimento não usa deploy. Para código, template ou migration:

1. execute auditoria read-only e dry-run oficial;
2. confirme SHA, manifesto vivo, serviços afetados e digests;
3. para migration, valide plano checksummed, backup data-only e restore;
4. somente após PASS e gates, aplique pausa global, drene claims e faça o
   blue/green;
5. em falha posterior, restaure automaticamente slots e rotas;
6. em sucesso ou rollback, mantenha transportes e IAs pausados.

Retomada exige autorização posterior separada. Não executar Docker local,
limpeza, resync geral, WhatsApp real ou conteúdo adicional nesta release.
