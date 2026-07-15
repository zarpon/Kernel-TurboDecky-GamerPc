# Kernelnote

Kernel experimental para o notebook HP 240 G4 com Intel Core i3-5005U, destinado ao Linux Mint Debian Edition.

## Composição atual

- Base oficial: Linux 7.1.3 stable
- Fonte Liquorix: tag `v7.1.3-lqx1`
- Scheduler interativo: BORE 6.8.0-rc1
- Gerenciamento de memória: Marie LRU 0.7.7 da árvore `testing`, patch nativo para Linux 7.1 fixado em commit
- ZRAM: ZRAM Immediate Recompression 1.2, patch Linux 7.1 fixado no commit `e348391dcf54bc42904f227f5ee83d2790f28f52`
- Scheduler de disco: ADIOS 3.2.0
- Compilador: Clang/LLVM
- Otimização de link: ThinLTO
- Distribuição alvo: LMDE 7 / Debian 13 Trixie
- Arquitetura: amd64

## Padrões do kernel

- `CONFIG_SCHED_BORE=y`
- `CONFIG_LRU_MARIE=y`
- `CONFIG_MQ_IOSCHED_ADIOS=y`
- `CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y`
- `CONFIG_ZRAM=m`
- `CONFIG_ZRAM_MULTI_COMP=y`
- `CONFIG_ZRAM_BACKEND_LZ4=y`
- `CONFIG_ZRAM_BACKEND_ZSTD=y`
- `CONFIG_ZRAM_DEF_COMP_LZ4=y`
- `CONFIG_LTO=y`
- `CONFIG_LTO_CLANG=y`
- `CONFIG_LTO_CLANG_THIN=y`
- `CONFIG_CPU_MITIGATIONS=y`
- linha de comando embutida inclui `mitigations=off nowatchdog`
- `CONFIG_CMDLINE_OVERRIDE` permanece desativado para preservar argumentos do bootloader
- scheduler alternativo PDS/BMQ do Liquorix desativado para que o BORE atue sobre CFS/EEVDF

A compilação usa obrigatoriamente `LLVM=1 LLVM_IAS=1`. O workflow falha se o Kconfig selecionar GCC, BFD, `LTO_NONE`, Full LTO, remover os argumentos de desempenho ou desativar os backends LZ4/ZSTD exigidos pelo ZRAM-IR.

> `mitigations=off` desativa mitigações opcionais de vulnerabilidades de CPU e `nowatchdog` desativa os detectores de soft-lockup e hard-lockup. Essas opções reduzem proteção e capacidade de diagnóstico em troca de menor sobrecarga.

## ZRAM-IR padrão

Quando uma nova zram é criada, a regra udev do pacote de ajustes configura, antes de `disksize`:

1. `lz4` como compressor primário, prioridade 0;
2. `zstd` como compressor secundário, prioridade 1;
3. `vm.zram_recomp_immediate=1`.

No ZRAM-IR 1.2, o valor `1` faz cada gravação tentar as prioridades 0 e 1. Assim, páginas que não atingem o limite de compressão com LZ4 são tentadas imediatamente com ZSTD. A configuração não cria nem ativa zram por conta própria; ela só é aplicada quando o sistema realmente carrega e usa o dispositivo.

Dispositivos já inicializados não são resetados ou interrompidos. A configuração completa entra em vigor na próxima criação do dispositivo, normalmente após reinicialização ou recarga segura do módulo.

## Pacote de ajustes

O modo `package` também gera `kernelnote-tuning_1.2.0_all.deb`, contendo:

- `vm.swappiness = 1`
- `vm.page-cluster = 0`
- regra udev que seleciona `adios` em todos os discos que exponham esse scheduler
- configuração automática ZRAM-IR `lz4 → zstd`
- drop-in do GRUB que acrescenta `mitigations=off nowatchdog` sem substituir os argumentos existentes
- política persistente de Transparent Hugepages via `systemd-tmpfiles`:
  - `enabled = madvise`
  - `defrag = defer+madvise`
  - `shmem_enabled = advise`
  - `khugepaged/defrag = 0`
  - `khugepaged/max_ptes_none = 409`
  - `khugepaged/max_ptes_swap = 8`

O arquivo tmpfiles usa linhas `w-`: elas escrevem apenas quando o nó sysfs existe e não tornam a inicialização ou instalação fatal em kernels que não exponham algum controle. `w!` seria válido, mas restringiria a execução a chamadas de `systemd-tmpfiles` com `--boot`, impedindo a aplicação imediata no `postinst`.

Dispositivos `loop`, `ram` e `zram` são excluídos da regra ADIOS. Dispositivos que não oferecem ADIOS são ignorados.

## Validação

O workflow aplica os patches na seguinte ordem:

1. fonte oficial Liquorix `v7.1.3-lqx1`
2. Marie LRU 0.7.7 da árvore `testing`, obtido por checkout Git parcial local do commit fixado
3. BORE 6.8.0-rc1
4. ADIOS 3.2.0
5. ZRAM-IR 1.2 para Linux 7.1, obtido por checkout Git parcial local do commit fixado

Depois executa `olddefconfig` com LLVM, confirma ThinLTO, valida a linha de comando embutida e os símbolos ZRAM multi-compressor e, no modo de validação, compila e verifica `vmlinux` e `bzImage`. O modo `package` mantém a configuração completa, gera os pacotes Debian e publica os arquivos com checksums em uma GitHub Release.

> BORE 6.8.0-rc1 e Marie 0.7.7 pertencem às árvores `testing`. Esta branch não deve ser mesclada na `main` antes da compilação e dos testes de inicialização no notebook.
