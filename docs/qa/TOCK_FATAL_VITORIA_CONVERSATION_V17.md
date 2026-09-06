# Roteiro manual — Vitória v17

Use somente o WA Validator direto/interno. Não execute este roteiro por um
número real de WhatsApp. Antes do teste, confirme que a publicação candidata e
o template canônico do n8n foram sincronizados no ambiente autorizado.

## 1. Abertura, nome e visita à loja

Inicie uma sessão nova de varejo e envie:

1. `Oi, quero ver conjuntos para usar no dia a dia.`
2. Quando Vitória perguntar como chamar você, responda `Pode me chamar de Caio.`
3. `Estou comparando as opções.`
4. `Prefiro visitar a loja física.`
5. Faça mais uma pergunta sobre um conjunto e observe se o nome é solicitado de novo.

Esperado:

- a primeira resposta apresenta “Vitória” e diz que ela é uma IA/assistente virtual;
- a apresentação não se repete;
- no máximo uma pergunta útil por resposta;
- o nome é perguntado uma vez, persistido e não volta a ser solicitado;
- não aparecem “grupo de produtos”, “serviço”, “branch”, “node” ou “retrieval”;
- a conversa reconhece o que foi dito antes de avançar.

## 2. Foto com evidência aprovada

Em uma nova sessão de varejo, envie:

`Oi, quero a Blusa em POÁ para uso próprio. Você tem uma foto?`

Esperado:

- Vitória se apresenta como IA;
- a resposta usa a FAQ/asset da peça exata e pode sugerir o envio da foto;
- a evidência cita a FAQ de foto aprovada da Blusa em POÁ;
- a mesma oferta de foto não é repetida nos turnos seguintes;
- o Validator não produz outbound real.

## 3. Foto sem evidência aprovada

Em outra sessão, envie:

`Oi, quero a Básica lisa para uso próprio. Você pode me mandar uma foto?`

Esperado:

- Vitória não afirma que possui ou que ela mesma enviará a foto;
- informa que um atendente poderá continuar e enviar uma imagem;
- o aviso ao cliente vem antes do handoff, na mesma resposta;
- a sessão falha se o encaminhamento for silencioso.

## 4. Frete

Em nova sessão, envie:

`Oi, quero algumas peças para uso próprio. Quanto fica o frete?`

Esperado:

- não há valor, prazo em dias ou estimativa inventada;
- Vitória explica que um atendente/especialista confirmará conforme o destino;
- a preferência `envio` pode ser registrada sem confirmar o preço do frete.

## 5. Revenda e isolamento de branch

Execute `sdr_sales_branch_switch` e depois uma sessão `sdr_sales_reseller`.

Esperado:

- uso próprio e revenda permanecem separados;
- a nova intenção explícita troca o branch sem carregar condições incompatíveis;
- cada inbound gera no máximo uma decisão e um outbound;
- proof e ledger ficam válidos e o branch persiste.

## 6. Critérios de bloqueio

Não aprove a retomada se ocorrer qualquer um destes pontos:

- nome solicitado duas vezes;
- apresentação como IA ausente no primeiro turno ou repetida depois;
- descrição, lista ou oferta de foto repetida;
- linguagem interna do grafo;
- foto oferecida sem asset aprovado da peça exata;
- valor/prazo de frete confirmado pela IA;
- handoff silencioso;
- mistura entre varejo e revenda;
- duplicidade de decisão/outbound ou outbound sem proof.
