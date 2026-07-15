# Kernelnote

Kernel experimental para o notebook HP 240 G4 com Intel Core i3-5005U, destinado ao Linux Mint Debian Edition.

## Composição atual

- Linux 7.1.3 / Liquorix `v7.1.3-lqx1`
- BORE 6.8.0-rc1 sobre CFS/EEVDF
- POC Selector 2.6.2r2, usando o patch estável nativo para Linux 7.1
- NAP CPUIdle 0.5.0, portado do patch estável Linux 6.18.3 porque não existe revisão nativa para Linux 7.1
- Marie LRU 0.7.7 da árvore `testing`
- ZRAM-IR 1.2 para Linux 7.1
- ADIOS 3.2.0 como scheduler de I/O padrão
- Clang/LLVM com ThinLTO
- LMDE 7 / Debian 13 Trixie, amd64

## Padrões do kernel

- `CONFIG_SCHED_BORE=y`
- `CONFIG_SCHED_POC_SELECTOR=y`
- `CONFIG_CPU_IDLE_GOV_NAP=y`
- `CONFIG_LRU_MARIE=y`
- `CONFIG_MQ_IOSCHED_ADIOS=y`
- `CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y`
- `CONFIG_ZRAM=m`
- `CONFIG_ZRAM_MULTI_COMP=y`
- `CONFIG_ZRAM_BACKEND_LZ4=y`
- `CONFIG_ZRAM_BACKEND_ZSTD=y`
- `CONFIG_ZRAM_DEF_COMP_LZ4=y`
- `CONFIG_LTO_CLANG_THIN=y`
- linha de comando embutida: `mitigations=off nowatchdog cpuidle.governor=nap`
- `CONFIG_CMDLINE_OVERRIDE` desativado, preservando `root=`, `resume=`, `console=` e demais parâmetros do bootloader
- PDS/BMQ desativados para que o BORE opere sobre CFS/EEVDF

`mitigations=off` reduz a proteção contra vulnerabilidades de CPU e `nowatchdog` remove os detectores de soft-lockup e hard-lockup. São escolhas deliberadas de desempenho.

## ZRAM-IR padrão

Quando uma zram é criada, o pacote de ajustes configura, antes de `disksize`:

1. `lz4` como compressor primário, prioridade 0;
2. `zstd` como compressor secundário, prioridade 1;
3. `vm.zram_recomp_immediate=1`.

No ZRAM-IR 1.2, o valor `1` faz cada gravação testar as prioridades 0 e 1. O pacote não cria ou ativa zram; ele apenas aplica a política quando o sistema usa o dispositivo.

## Pacote de ajustes

O modo `package` gera também `kernelnote-tuning_1.2.0_all.deb`, contendo:

- `vm.swappiness = 1`
- `vm.page-cluster = 0`
- ADIOS automático nos discos compatíveis
- ZRAM-IR `lz4 → zstd`
- drop-in do GRUB com `mitigations=off nowatchdog`
- política THP via `systemd-tmpfiles`:
  - `enabled = madvise`
  - `defrag = defer+madvise`
  - `shmem_enabled = advise`
  - `khugepaged/defrag = 0`
  - `khugepaged/max_ptes_none = 409`
  - `khugepaged/max_ptes_swap = 8`

## CI e tempo de compilação

O host do GitHub Actions segue a configuração validada no `linux-charcoal-TD`:

```text
zswap compressor       = zstd
zswap max_pool_percent = 90
zswap shrinker_enabled = 1
zswap enabled          = 1
swap em disco           = 16 GiB
```

Para evitar que o pacote ultrapasse o limite do runner:

- o timeout explícito foi elevado para 360 minutos;
- DWARF, BTF e o pacote de símbolos de depuração foram desativados em `validate` e `package`;
- ThinLTO, módulos, headers, imagem instalável e símbolos de runtime permanecem;
- o cache do Clang/ccache usa modo de dependências e reaproveita caches anteriores;
- a limpeza do runner foi reduzida ao método usado pelo Charcoal, evitando remoções desnecessariamente lentas.

## Ordem dos patches

1. Liquorix `v7.1.3-lqx1`
2. Marie LRU 0.7.7
3. BORE 6.8.0-rc1
4. POC Selector 2.6.2r2 para Linux 7.1
5. ADIOS 3.2.0
6. ZRAM-IR 1.2
7. port do NAP 0.5.0

Todos os patches de terceiros obtidos por checkout Git local são fixados por commit, caminho e SHA-256. O workflow registra rejeitos completos e interrompe antes da compilação quando um port não pode ser resolvido com segurança.

A branch continua experimental até a aplicação de todos os patches, `olddefconfig`, link ThinLTO, geração dos `.deb` e publicação da Release concluírem com sucesso.
