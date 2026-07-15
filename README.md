# Kernelnote

Kernel experimental para o notebook HP 240 G4 com Intel Core i3-5005U, destinado ao Linux Mint Debian Edition.

## Composição atual

- Base oficial: Linux 7.1.3 stable
- Fonte Liquorix: tag `v7.1.3-lqx1`
- Scheduler interativo: BORE 6.8.0-rc1
- Gerenciamento de memória: Marie LRU 0.7.7 `testing`, patch nativo para Linux 7.1
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
2. Marie LRU 0.7.7 `testing`, revisão `4d57ede4ab9b2000ae9ddc25714b8ac219671d35`, patch nativo `linux7.1-rc5`
3. BORE 6.8.0-rc1
4. ADIOS 3.2.0

O repositório do Marie é obtido por checkout Git parcial e fixado no commit acima. O patch é extraído para o workspace e aplicado como arquivo local; o build não depende de uma URL `raw` para o patch do Marie. O workflow registra o caminho, commit e SHA-256 usados.

A aplicação tenta primeiro sem fuzz. Em caso de diferenças pequenas da árvore Liquorix, repete com fuzz limitado, registra todos os rejeitos e normaliza somente problemas de whitespace introduzidos por deslocamentos do patch. Rejeitos de código permanecem fatais.

Depois executa `olddefconfig` com LLVM, confirma ThinLTO e, no modo de validação, compila e verifica `vmlinux` e `bzImage`. O modo manual `package` mantém a configuração completa e gera os pacotes Debian e todos os módulos.

> Marie LRU 0.7.7 e BORE 6.8.0-rc1 pertencem às respectivas árvores `testing`. Esta branch não deve ser mesclada na `main` antes da compilação e dos testes de inicialização no notebook.
