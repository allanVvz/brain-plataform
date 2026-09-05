# Midia de produtos Tock Fatal

Fonte aprovada pelo operador em 2026-08-26. Os quatro arquivos foram copiados
sem transformacao do diretorio informado pelo operador. O `manifest.json`
registra o SHA-256 e a associacao de cada nome visivel na imagem ao produto ja
publicado no catalogo.

Essas imagens nao comprovam preco, estoque, cor disponivel, tamanho disponivel
ou prazo. Seu unico papel publicado e `primary_product_media`.

O bundle v16 mantem a Gallery como terminal e cria, para cada arquivo, a cadeia
`product -> asset -> Gallery`. O modelo pode selecionar imagens elegiveis, e o
backend valida escopo, publicacao e disponibilidade antes de aceitar no maximo
tres anexos por resposta. Nenhuma imagem e enviada durante validacao interna.
