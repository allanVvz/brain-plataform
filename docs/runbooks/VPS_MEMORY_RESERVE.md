# Reserva de memória da VPS

Operação de host separada de imagens, schema e serviços. A reserva de 2 GiB
reduz a exposição a OOM; não resolve o consumo que atingiu aproximadamente
7,7 GiB de memória anônima. Trackon foi a vítima observada, não uma causa
comprovada. Não reiniciar serviços nem alterar seus limites nesta operação.

Usar o workflow **VPS memory reserve**, com `source_sha` completo revisado e
ação `audit` primeiro. O host precisa de filesystem ext4 ou XFS e espaço livre
superior a 3 GiB, com ocupação projetada abaixo de 50%. A auditoria registra MemAvailable/SwapUsed, PSI, latência HTTP,
restarts/start times dos containers e `memory.swap.max/current`. Cgroups com
swap.max=0 não recebem esta capacidade; nenhum limite é modificado pelo script.

Após revisão do resultado e autorização, executar `dry-run` e `apply` no mesmo
SHA. O workflow repete audit/dry-run, verifica os bytes enviados e o fingerprint
SSH fixado. O arquivo dedicado é `/var/lib/brain-memory-reserve/swapfile`,
2 GiB escritos completamente, root:0600, protegido por diretório root:0700 e
marca de propriedade/inode. Arquivos/diretórios existentes não gerenciados,
symlinks e entradas conflitantes no fstab são recusados. Interrupções durante
alocação são recuperáveis por reaplicar o mesmo procedimento. Nunca usar o
script legado `ensure-swap.sh` em paralelo.

O script salva o fstab antes da primeira persistência e adiciona apenas sua
linha marcada. Confere inode, atributos e checksum antes de substituir o fstab;
alteração concorrente observada aborta a gravação. Operadores que editam fstab
devem coordenar pela trava `/run/lock/brain-memory-reserve.lock` durante a janela.
Verificar swap ativo com 2 GiB, fstab único, PSI/latência e ausência
de novos restarts nos logs antes/depois; observar novamente sob carga normal.
Health HTTP não comprova readiness conversacional. Não declarar o incidente
resolvido apenas pela instalação da reserva.

Rollback é um dispatch explícito com o mesmo SHA, após auditoria. Só permite
swapoff quando **MemAvailable > SwapUsed total + 512 MiB**. Se houver pressão ou
swapoff falhar, mantém arquivo e persistência e termina com erro; não força nem
executa rollback automático. Confirma desativação antes de apagar somente seu
arquivo e retirar somente sua linha do fstab, preservando alterações de outros
operadores. Backup/marca ficam no diretório como evidência; reaplicar recria o
arquivo. Não remover swap de terceiros, volumes, backups ou imagens.
