# Kernelnote

Kernel experimental para o notebook HP 240 G4 com Intel Core i3-5005U, destinado ao Linux Mint Debian Edition.

## Identidade final do kernel

O kernel compilado usa exatamente o identificador solicitado:

```text
Linux.7.1.3.KernelZarpon
```

Esse valor é passado diretamente ao Kbuild como `KERNELRELEASE` e será usado em:

- `uname -r`;
- `/boot/vmlinuz-Linux.7.1.3.KernelZarpon`;
- `/lib/modules/Linux.7.1.3.KernelZarpon`;
- `vermagic` dos módulos;
- descrições e metadados da compilação.

Os nomes internos dos pacotes Debian são normalizados para minúsculas, por exemplo `linux-image-linux.7.1.3.kernelzarpon`, porque identificadores de pacotes `.deb` não aceitam letras maiúsculas. Isso não altera o nome instalado nem o resultado de `uname -r`.

## Composição atual

- Linux 7.1.3 / Liquorix `v7.1.3-lqx1`
- BORE 6.8.0-rc1 sobre CFS/EEVDF
- POC Selector 2.6.2r2, usando o patch estável nativo para Linux 7.1
- NAP CPUIdle 0.5.0, portado do patch estável Linux 6.18.3 porque não existe revisão nativa para Linux 7.1
- REFLEX CPUFreq 0.3.1, usando o patch nativo para Linux 7.1 e selecionado como governador padrão
- Marie LRU 0.7.7 da árvore `testing`
- ZRAM-IR 1.2 para Linux 7.1
- ADIOS 3.2.0 como scheduler de I/O padrão
- Clang/LLVM com ThinLTO
- LMDE 7 / Debian 13 Trixie, amd64

## Padrões do kernel

- `KERNELRELEASE=Linux.7.1.3.KernelZarpon`
- `CONFIG_LOCALVERSION=""`
- `CONFIG_SCHED_BORE=y`
- `CONFIG_SCHED_POC_SELECTOR=y`
- `CONFIG_CPU_IDLE_GOV_NAP=y`
- `CONFIG_CPU_FREQ_GOV_SCHEDUTIL=y`
- `CONFIG_CPU_FREQ_GOV_REFLEX=y`
- `CONFIG_CPU_FREQ_DEFAULT_GOV_REFLEX=y`
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
- `intel_pstate=disable amd_pstate=disable`, permitindo que um driver CPUFreq externo compatível use o REFLEX
- PDS/BMQ desativados para que o BORE opere sobre CFS/EEVDF

`mitigations=off` reduz a proteção contra vulnerabilidades de CPU e `nowatchdog` remove os detectores de soft-lockup e hard-lockup. São escolhas deliberadas de desempenho.

## REFLEX como governador padrão

O patch REFLEX 0.3.1 adiciona o governador `reflex` e implementa `cpufreq_default_governor()` condicionado a `CONFIG_CPU_FREQ_DEFAULT_GOV_REFLEX`. A documentação upstream orienta habilitar esse símbolo para torná-lo padrão, mas o patch Linux 7.1 não adiciona a opção à escolha Kconfig de governador padrão. O build completa essa integração antes do `olddefconfig`, compila o REFLEX embutido e valida que somente `CONFIG_CPU_FREQ_DEFAULT_GOV_REFLEX=y` permaneceu selecionado.

O REFLEX combina uma subida imediata de frequência nas transições de ocioso para ocupado com o escalonamento proporcional baseado em PELT do `schedutil`. A contribuição de alta frequência decai progressivamente, permitindo resposta rápida a interações curtas sem manter uma frequência mínima artificial durante cargas sustentadas.

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

## Desenvolvedores, origem e benefícios

- **Liquorix / Zen Kernel** — mantido por [Steven Barrett (`damentz`)](https://github.com/damentz), com fontes no [Zen Kernel](https://github.com/zen-kernel/zen-kernel) e empacotamento no [liquorix-package](https://github.com/damentz/liquorix-package). Fornece a base voltada a desktops, com preempção e ajustes de latência orientados à responsividade.
- **BORE — Burst-Oriented Response Enhancer** — desenvolvido por [Masahito Suzuki (`firelzrd`)](https://github.com/firelzrd) no [bore-scheduler](https://github.com/firelzrd/bore-scheduler). Mede a característica de rajada das tarefas e favorece cargas interativas e I/O-bound quando competem com trabalhos CPU-bound longos.
- **POC Selector — Piece-Of-Cake CPU Selector** — desenvolvido por [Masahito Suzuki](https://github.com/firelzrd) no [poc-selector](https://github.com/firelzrd/poc-selector), inspirado no [scx_cake de RitzDaCat](https://github.com/RitzDaCat/scx_cake). Usa bitmaps por LLC para localizar CPUs ociosas em tempo aproximadamente constante, preservando afinidade, topologia de cache e preferência por núcleos físicos.
- **NAP — Neural Adaptive Predictor CPUIdle** — desenvolvido por [Masahito Suzuki](https://github.com/firelzrd) no [nap](https://github.com/firelzrd/nap). Aprende online o estado de idle adequado por CPU, buscando equilibrar economia de energia e latência de despertar em cargas irregulares.
- **REFLEX CPUFreq** — desenvolvido por [Masahito Suzuki](https://github.com/firelzrd) no [reflex](https://github.com/firelzrd/reflex). Combina resposta imediata a transições idle→busy com o escalonamento proporcional do `schedutil`, evitando tanto ramp-up lento quanto frequência alta presa por tempo excessivo.
- **Marie LRU — Multi-graded Adaptive Reclaim & Independent Eviction** — desenvolvido por [Masahito Suzuki](https://github.com/firelzrd) no [lru_marie](https://github.com/firelzrd/lru_marie). Implementa reclaim global voltado a desktop, proteção de working set, aging independente de anon/file e compressão assíncrona para reduzir thrashing e stalls sob pressão de memória.
- **ADIOS — Adaptive Deadline I/O Scheduler** — desenvolvido por [Masahito Suzuki](https://github.com/firelzrd) no [adios](https://github.com/firelzrd/adios). Aprende a latência do dispositivo e ajusta deadlines e lotes dinamicamente, priorizando operações síncronas e responsividade sob I/O intenso.
- **ZRAM-IR — ZRAM Immediate Recompression** — desenvolvido por [Masahito Suzuki](https://github.com/firelzrd) no [zram-ir](https://github.com/firelzrd/zram-ir). Tenta compressores em sequência por página; nesta configuração, usa a velocidade do LZ4 e recorre ao ZSTD quando isso evita armazenar uma página pouco comprimida ou sem compressão.

Revisões fixadas pelo build:

- Marie LRU: [`4d57ede4`](https://github.com/firelzrd/lru_marie/commit/4d57ede4ab9b2000ae9ddc25714b8ac219671d35)
- BORE: [`16bf5bae`](https://github.com/firelzrd/bore-scheduler/commit/16bf5baebbb42cdba393c501ba9c2af5f84e4749)
- POC Selector: [`f2e9d602`](https://github.com/firelzrd/poc-selector/commit/f2e9d6027ec8a9167365acd828016da9c8bd28e1)
- NAP: [`b4ca3378`](https://github.com/firelzrd/nap/commit/b4ca3378854a067bb639c60d9d8175ecc0a804bf)
- REFLEX: [`a7a7774b`](https://github.com/firelzrd/reflex/commit/a7a7774b059a1f913521ffbfc52eeda72bdbb14c)
- ADIOS: [`08bf078a`](https://github.com/firelzrd/adios/commit/08bf078aac99075a0bef73c2b2497574a82e4c41)
- ZRAM-IR: [`e348391d`](https://github.com/firelzrd/zram-ir/commit/e348391dcf54bc42904f227f5ee83d2790f28f52)

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
8. REFLEX CPUFreq 0.3.1 para Linux 7.1, seguido pela integração da escolha Kconfig padrão
9. política de nome `Linux.7.1.3.KernelZarpon` e normalização dos identificadores Debian

Todos os patches de terceiros obtidos por checkout Git local são fixados por commit, caminho e SHA-256. O workflow registra rejeitos completos e interrompe antes da compilação quando um port não pode ser resolvido com segurança.

A branch continua experimental até a aplicação de todos os patches, `olddefconfig`, link ThinLTO, geração dos `.deb` e publicação da Release concluírem com sucesso.
