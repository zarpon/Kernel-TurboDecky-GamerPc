# Kernelnote

Kernel experimental para o notebook HP 240 G4 com Intel Core i3-5005U, destinado ao Linux Mint Debian Edition.

## Composição atual

- Base oficial: Linux 7.1.3 stable
- Fonte Liquorix: tag `v7.1.3-lqx1`
- Scheduler interativo: BORE 6.8.0-rc1
- Gerenciamento de memória: Marie LRU 0.7.7 da árvore `testing`, patch nativo para Linux 7.1 fixado em commit
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
- `CONFIG_LTO=y`
- `CONFIG_LTO_CLANG=y`
- `CONFIG_LTO_CLANG_THIN=y`
- `CONFIG_CPU_MITIGATIONS=y`
- linha de comando embutida inclui `mitigations=off nowatchdog`
- `CONFIG_CMDLINE_OVERRIDE` permanece desativado para preservar argumentos do bootloader
- scheduler alternativo PDS/BMQ do Liquorix desativado para que o BORE atue sobre CFS/EEVDF

A compilação usa obrigatoriamente `LLVM=1 LLVM_IAS=1`. O workflow falha se o Kconfig selecionar GCC, BFD, `LTO_NONE`, Full LTO ou remover os argumentos de desempenho solicitados.

> `mitigations=off` desativa mitigações opcionais de vulnerabilidades de CPU e `nowatchdog` desativa os detectores de soft-lockup e hard-lockup. Essas opções reduzem proteção e capacidade de diagnóstico em troca de menor sobrecarga.

## Pacote de ajustes

O modo `package` também gera `kernelnote-tuning_1.1.0_all.deb`, contendo:

- `vm.swappiness = 1`
- `vm.page-cluster = 0`
- regra udev que seleciona `adios` em todos os discos que exponham esse scheduler
- drop-in do GRUB que acrescenta `mitigations=off nowatchdog` sem substituir os argumentos existentes
- política persistente de Transparent Hugepages via `systemd-tmpfiles`:
  - `enabled = madvise`
  - `defrag = defer+madvise`
  - `shmem_enabled = advise`
  - `khugepaged/defrag = 0`
  - `khugepaged/max_ptes_none = 409`
  - `khugepaged/max_ptes_swap = 8`

O arquivo tmpfiles usa linhas `w-`: elas escrevem apenas quando o nó sysfs existe e não tornam a inicialização ou instalação fatal em kernels que não exponham algum controle. `w!` seria válido, mas restringiria a execução a chamadas de `systemd-tmpfiles` com `--boot`, impedindo a aplicação imediata no `postinst`.

Dispositivos `loop`, `ram` e `zram` são excluídos da regra. Dispositivos que não oferecem ADIOS são ignorados.

## Validação

O workflow aplica os patches na seguinte ordem:

1. fonte oficial Liquorix `v7.1.3-lqx1`
2. Marie LRU 0.7.7 da árvore `testing`, obtido por checkout Git parcial local do commit fixado
3. BORE 6.8.0-rc1
4. ADIOS 3.2.0

Depois executa `olddefconfig` com LLVM, confirma ThinLTO, valida a linha de comando embutida e, no modo de validação, compila e verifica `vmlinux` e `bzImage`. O modo `package` mantém a configuração completa, gera os pacotes Debian e publica os arquivos com checksums em uma GitHub Release.

> BORE 6.8.0-rc1 e Marie 0.7.7 pertencem às árvores `testing`. Esta branch não deve ser mesclada na `main` antes da compilação e dos testes de inicialização no notebook.
