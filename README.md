# Kernelnote

Kernel experimental para o notebook HP 240 G4 com Intel Core i3-5005U, destinado ao Linux Mint Debian Edition.

## Composição atual

- Base oficial: Linux 7.1.3 stable
- Fonte Liquorix: tag `v7.1.3-lqx1`
- Scheduler interativo: BORE 6.8.0-rc1
- Gerenciamento de memória: Marie LRU 0.7.7
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
- scheduler alternativo PDS/BMQ do Liquorix desativado para que o BORE atue sobre CFS/EEVDF

A compilação usa obrigatoriamente `LLVM=1 LLVM_IAS=1`. O workflow falha se o Kconfig selecionar GCC, BFD, `LTO_NONE` ou Full LTO.

## Pacote de ajustes

O modo `package` também gera `kernelnote-tuning_1.0.0_all.deb`, contendo:

- `vm.swappiness = 1`
- `vm.page-cluster = 0`
- regra udev que seleciona `adios` em todos os discos que exponham esse scheduler

Dispositivos `loop`, `ram` e `zram` são excluídos da regra. Dispositivos que não oferecem ADIOS são ignorados.

## Validação

O workflow aplica os patches na seguinte ordem:

1. fonte oficial Liquorix `v7.1.3-lqx1`
2. BORE 6.8.0-rc1
3. Marie LRU 0.7.7
4. ADIOS 3.2.0

Depois executa `olddefconfig` com LLVM, confirma ThinLTO e compila `bzImage` e módulos. O modo manual `package` gera pacotes Debian usando o mesmo toolchain ThinLTO.

> BORE 6.8.0-rc1 é a revisão mais recente para Linux 7.1, mas ainda pertence à árvore `testing`. Esta branch não deve ser mesclada na `main` antes da compilação e dos testes de inicialização no notebook.
