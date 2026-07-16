# linux.7.1.3.zarpon.r1

Kernel experimental para o HP 240 G4 com Intel Core i3-5005U, destinado ao LMDE 7 / Debian 13. Esta branch usa a árvore **upstream stable Linux 7.1.3**, sem Zen/Liquorix, e mantém os patches e políticas de desempenho da branch TurboLQX.

## Identidade e fonte

```text
KERNELRELEASE=linux.7.1.3.zarpon.r1
```

O mesmo identificador será usado por `uname -r`, `vermagic`, `/boot/vmlinuz-linux.7.1.3.zarpon.r1` e `/lib/modules/linux.7.1.3.zarpon.r1`.

Fonte: [Linux stable](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git), tag `v7.1.3`.

## Arquitetura mínima do notebook

O alvo é fixo e não depende da CPU do runner:

- Intel Core i3-5005U, Broadwell-U;
- x86-64, um socket, dois núcleos e quatro threads;
- `CONFIG_MBROADWELL=y`, fornecido pelo patch universal de otimização de CPU;
- `CONFIG_NR_CPUS=4`;
- NUMA, paginação de cinco níveis, MAXSMP e plataformas x86 de servidor/hipervisor não usadas desativadas;
- suporte exclusivo a AMD, Hygon, Centaur e Zhaoxin desativado;
- microcode e MCE Intel preservados;
- `CONFIG_X86_NATIVE_CPU` desativado: `-march=native` miraria o host do GitHub, não o notebook.

Drivers de armazenamento, Intel iGPU, ACPI, USB, entrada, rede, áudio, sistemas de arquivos, initramfs, módulos e headers são preservados até existir um inventário completo do hardware real.

## Patches herdados da TurboLQX

- **BORE 6.8.0-rc1** — [Masahito Suzuki / firelzrd](https://github.com/firelzrd/bore-scheduler): favorece responsividade de tarefas em rajadas sobre CFS/EEVDF.
- **POC Selector 2.6.2r2** — [firelzrd/poc-selector](https://github.com/firelzrd/poc-selector): seleção eficiente de CPU ociosa considerando LLC e topologia.
- **NAP CPUIdle 0.5.0** — [firelzrd/nap](https://github.com/firelzrd/nap): predição adaptativa do estado de idle, portada da revisão estável 6.18.3.
- **REFLEX CPUFreq 0.3.1** — [firelzrd/reflex](https://github.com/firelzrd/reflex): resposta rápida idle→busy combinada com PELT; fica ativo como governador padrão.
- **Marie LRU 0.7.7** — [firelzrd/lru_marie](https://github.com/firelzrd/lru_marie): reclaim adaptativo voltado a desktop e redução de thrashing.
- **ADIOS 3.2.0** — [firelzrd/adios](https://github.com/firelzrd/adios): scheduler de I/O adaptativo, embutido e padrão.
- **ZRAM-IR 1.2** — [firelzrd/zram-ir](https://github.com/firelzrd/zram-ir): LZ4 primário e ZSTD prioridade 1 com recompressão imediata.

Também permanecem Clang/LLVM ThinLTO, `mitigations=off`, `nowatchdog`, `cpuidle.governor=nap`, THP em `madvise/defer+madvise`, `vm.swappiness=1`, `vm.page-cluster=0` e o pacote `kernelnote-tuning`.

## Série adicional solicitada

O build procura primeiro uma revisão para Linux 7.1. Se ela não existir, usa a fonte indicada e executa um port controlado. Cada patch recebe log, URL selecionada, SHA-256, tentativa limpa, detecção de código já integrado, fuzz máximo 3 e relatório integral de rejeitos.

- **C23 libbpf** — [Mikhail Gavrilov e mantenedores BPF](https://github.com/torvalds/linux/commit/d70f79fef65810faf64dbae1f3a1b5623cdb2345): corrige qualificadores `const` exigidos pelo C23. A mudança pode já estar integrada no Linux 7.1.3; nesse caso o build valida e registra o estado.
- **Clear Linux performance series** — [Arjan van de Ven / Clear Linux, via linux-tkg](https://github.com/Frogging-Family/linux-tkg): reduz wakeups, ajusta limites TCP, spinning de rwsem, paraleliza inicialização ATA/GPU e inclui fila LIFO para `accept()`.
- **fsync via FUTEX_WAIT_MULTIPLE** — [André Almeida](https://github.com/Frogging-Family/linux-tkg/blob/d837d80398a62ea884caabad36530093f9711d49/linux-tkg-patches/6.11/0007-v6.11-fsync1_via_futex_waitv.patch): compatibilidade com versões antigas do Proton que usam o opcode futex 31.
- **Optimize harder O3** — [Frogging-Family / damachine](https://github.com/Frogging-Family/linux-tkg): adiciona `CONFIG_CC_OPTIMIZE_FOR_PERFORMANCE_O3=y` e passes adicionais de loop.
- **Bluetooth SSP key-size check** — [Gentoo genpatches](https://dev.gentoo.org/~alicef/genpatches/trunk/6.16/2000_BT-Check-key-sizes-only-if-Secure-Simple-Pairing-enabled.patch): limita a verificação de tamanho de chave ao caminho Secure Simple Pairing.
- **libbpf warning workaround** — [Gentoo genpatches](https://dev.gentoo.org/~alicef/genpatches/trunk/6.16/2990_libbpf-v2-workaround-Wmaybe-uninitialized-false-pos.patch): evita falso positivo de compilador nas ferramentas libbpf.
- **Universal CPU optimizations** — [graysky](https://github.com/graysky2/kernel_compiler_patch), empacotado pelo [Gentoo](https://dev.gentoo.org/~alicef/genpatches/trunk/6.16/5010_enable-cpu-optimizations-universal.patch): adiciona seleção explícita Broadwell e `-march=broadwell`.
- **DKMS-Clang compatibility** — [Eric Naim / CachyOS](https://github.com/CachyOS/kernel-patches): remove alguns `-Werror` que quebram módulos externos em kernels compilados por Clang.
- **Clang Polly** — [Peter Jung e Username404-59 / CachyOS](https://github.com/CachyOS/kernel-patches): ativa o otimizador poliédrico de loops. O workflow instala e valida `LLVMPolly.so` antes de habilitar `CONFIG_POLLY_CLANG=y`.
- **Firmware filename diagnostics** — [Gentoo bug 732852](https://732852.bugs.gentoo.org/attachment.cgi?id=649432): inclui sempre o nome do firmware nas mensagens relevantes.
- **minstrel_ht 302/303/304** — [OpenWrt](https://git.openwrt.org/openwrt/openwrt/): corrige a macro de fração, reduz flutuações de taxa e reorganiza o downgrade de rate control.
- **ath11k remapped CE 64-bit** — [OpenWrt](https://git.openwrt.org/openwrt/openwrt/): corrige acesso a Copy Engine remapeado em sistemas 64-bit.
- **ath11k DISABLE_KEY revert** — [CodeLinaro QSDK](https://git.codelinaro.org/clo/qsdk/oss/system/feeds/wlan-open): restaura o comportamento exigido pela árvore WLAN indicada.
- **ath11k upstream Qualcomm** — [Reshma Rajkumar / Qualcomm](https://lore.kernel.org/all/20260319065608.2408179-1-reshma.rajkumar@oss.qualcomm.com/): série upstream adicional fornecida para o driver.

## Configurações obrigatórias

```text
CONFIG_MBROADWELL=y
CONFIG_NR_CPUS=4
CONFIG_CC_OPTIMIZE_FOR_PERFORMANCE_O3=y
CONFIG_POLLY_CLANG=y
CONFIG_LTO_CLANG_THIN=y
CONFIG_SCHED_BORE=y
CONFIG_SCHED_POC_SELECTOR=y
CONFIG_CPU_IDLE_GOV_NAP=y
CONFIG_CPU_FREQ_DEFAULT_GOV_REFLEX=y
CONFIG_LRU_MARIE=y
CONFIG_MQ_IOSCHED_DEFAULT_ADIOS=y
CONFIG_ZRAM_MULTI_COMP=y
```

## CI e publicação

A branch possui workflow, cache e grupo de concorrência próprios; ela não cancela nem altera a compilação TurboLQX. O modo `package` gera imagem, headers, módulos, pacote de ajustes e `SHA256SUMS`, publica o artefato `linux.7.1.3.zarpon.r1-debs` e cria uma Release intitulada `linux.7.1.3.zarpon.r1`.

A branch permanece experimental até que todos os patches sejam aplicados ou confirmados como já integrados, o `olddefconfig` preserve as configurações, o link ThinLTO termine e os `.deb` e a Release sejam verificados.
