# Midia de produtos Tock Fatal

Fonte aprovada pelo operador em 2026-08-26. Os quatro arquivos foram copiados
sem transformacao do diretorio informado pelo operador. O `manifest.json`
registra o SHA-256 e a associacao de cada nome visivel na imagem ao produto ja
publicado no catalogo.

Essas imagens nao comprovam preco, estoque, cor disponivel, tamanho disponivel
ou prazo. Seu unico papel publicado e `primary_product_media`.

O bundle v11 mantem a Gallery como terminal e cria, para cada arquivo, a cadeia
`product -> asset -> Gallery`. O envio conversacional e solicitado pelo modelo,
mas resolvido e limitado pelo backend a no maximo 20 itens, em lote atomico e
sequencial. Nenhuma imagem e enviada durante validacao interna.
