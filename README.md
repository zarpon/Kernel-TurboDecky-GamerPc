# Kernel TurboDecky GamerPc

Kernel Linux experimental otimizado para entusiastas que querem alto
desempenho em multimídia e jogos nas distribuições Debian, Ubuntu e derivados.
O repositório `Kernel-TurboDecky-GamerPc` acompanha a versão estável mais
recente publicada pelo kernel.org e mantém uma configuração genérica para PCs
gamers amd64, sem limitar a compilação a um modelo de CPU ou a quatro CPUs.

O projeto é experimental. O resultado varia conforme CPU, GPU, firmware,
driver gráfico, temperatura, jogo e carga de trabalho. Mantenha um kernel
anterior instalado até validar o primeiro boot.

## Compatibilidade de hardware

O pacote publicado é destinado a:

- Debian, Ubuntu e derivados que usem `.deb`, `dpkg` e `apt`;
- desktops, computadores portáteis e workstations x86-64/amd64;
- CPUs Intel, AMD e demais famílias x86-64 habilitadas pela configuração
  upstream, sem `CONFIG_NR_CPUS=4` e sem uma seleção de microarquitetura
  Broadwell obrigatória;
- máquinas com qualquer quantidade de núcleos e threads suportada pelo kernel
  upstream e pelos recursos disponíveis no sistema.

A configuração conserva os drivers upstream para gráficos Intel e AMD,
armazenamento SATA/NVMe, USB, Ethernet, Wi-Fi, Bluetooth, áudio HDA/USB,
câmeras UVC/V4L2 e sistemas de arquivos usados em Debian e Ubuntu. Hardware
específico ainda depende de o respectivo driver upstream estar disponível na
versão estável escolhida pelo workflow.

Arquiteturas ARM/ARM64, 32 bits e sistemas que não executem pacotes Debian
`amd64` não são alvos desta Release. O driver proprietário da NVIDIA não é
incluído; seu módulo DKMS precisa ser recompilado para o novo `uname -r`. Com
Secure Boot ativo, a imagem e os módulos personalizados precisam ser assinados
ou a verificação deve ser desativada.

## Benefícios esperados

- **Responsividade e jogos:** BORE e POC Selector favorecem tarefas
  interativas e escolhem CPUs ociosas considerando a topologia de cache, o que
  pode melhorar a latência percebida e a consistência do frame time.
- **Resposta de frequência:** REFLEX acelera a transição de ocioso para ativo,
  enquanto NAP escolhe estados de idle de forma adaptativa.
- **I/O e carregamento:** ADIOS ajusta deadlines e lotes conforme a latência
  do dispositivo, favorecendo operações síncronas durante acesso intenso a
  disco.
- **Memória:** Marie LRU reduz reclaim agressivo e thrashing; ZRAM-IR usa LZ4
  e ZSTD para manter mais páginas úteis sob pressão de memória.
- **Multimídia:** os drivers upstream de vídeo, áudio, câmera, armazenamento e
  rede permanecem disponíveis sem a poda que existia no perfil de uma única
  máquina.
- **Otimização de compilação:** Clang/LLVM, ThinLTO, Polly e O3 reduzem parte
  do custo de chamadas e loops do kernel sem usar `-march=native` do runner.

Não há promessa de aumento fixo de FPS. O resultado depende também do driver
da GPU, do compositor, do governor do espaço de usuário e da aplicação. A
política de desempenho inclui `mitigations=off` e `nowatchdog`; isso pode
reduzir latência, mas diminui proteções contra vulnerabilidades de CPU e
desativa watchdogs. Avalie esse trade-off antes de usar o kernel em uma
máquina exposta ou de produção.

## Política de versão e identidade

O workflow consulta [`releases.json`](https://www.kernel.org/releases.json),
aceita somente uma entrada `stable` não EOL e rejeita mainline, release
candidates e versões malformadas.

O identificador produzido é:

```text
KERNELRELEASE=linux.<versão>.turbodecky.release
```

Esse valor é usado por `uname -r`, `vermagic`, `/boot/vmlinuz-*`,
`/lib/modules/*` e pelos nomes dos pacotes Debian. A versão, série, tag, data
e origem da fonte ficam registradas nos logs e nas notas da Release.

Fonte: [Linux stable](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git).
O build clona a tag `v<versão>` e confirma a versão pelo Makefile antes de
aplicar qualquer patch.

## Patchset de desempenho

- **BORE 6.8.0-rc1** — [firelzrd/bore-scheduler](https://github.com/firelzrd/bore-scheduler): favorece responsividade de tarefas em rajadas sobre CFS/EEVDF.
- **POC Selector 2.6.2r2** — [firelzrd/poc-selector](https://github.com/firelzrd/poc-selector): seleção eficiente de CPU ociosa considerando LLC e topologia.
- **NAP CPUIdle 0.5.0** — [firelzrd/nap](https://github.com/firelzrd/nap): predição adaptativa do estado de idle.
- **REFLEX CPUFreq 0.3.1** — [firelzrd/reflex](https://github.com/firelzrd/reflex): resposta rápida idle→busy combinada com PELT.
- **Marie LRU 0.7.7** — [firelzrd/lru_marie](https://github.com/firelzrd/lru_marie): reclaim adaptativo para desktops.
- **ADIOS 3.2.0** — [firelzrd/adios](https://github.com/firelzrd/adios): scheduler de I/O adaptativo, embutido e padrão.
- **ZRAM-IR 1.2** — [firelzrd/zram-ir](https://github.com/firelzrd/zram-ir): LZ4 primário e ZSTD como segunda prioridade.

O workflow também resolve e registra C23 libbpf, Clear Linux, fsync via
`FUTEX_WAIT_MULTIPLE`, O3, Bluetooth SSP, workaround libbpf, otimizações
universais de CPU sem selecioná-las para um modelo específico, compatibilidade
DKMS-Clang, Polly, diagnósticos de firmware, três correções minstrel_ht e
correções ath11k. Cada patch tem fonte, commit ou URL, SHA-256, tentativa de
aplicação, detecção de integração prévia e relatório de rejeitos.

## Configurações relevantes

```text
CONFIG_64BIT=y
CONFIG_X86_64=y
CONFIG_SMP=y
CONFIG_CPU_SUP_INTEL=y
CONFIG_CPU_SUP_AMD=y
CONFIG_GENERIC_CPU=y
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

Não há `CONFIG_NR_CPUS=4`, `CONFIG_MBROADWELL=y` ou desativação forçada de
famílias AMD no perfil publicado.

## CI e publicação

O workflow compila a partir da branch `main`, usa Clang/LLD, cache de
compilação e swap temporário no runner. O modo `package` gera imagem, headers,
módulos, `turbodecky-tuning` e `SHA256SUMS`.

```text
identidade: linux.<versão>.turbodecky.release
artefato:   linux.<versão>.turbodecky.release-debs
Release:    linux.<versão>.turbodecky.release
```

O monitor verifica periodicamente se o kernel.org publicou uma versão estável
mais nova, recompila e repete os ports necessários até a Release ser validada.

## Instalação automática da última Release

A última Release pode ser instalada pelo script versionado em
[`scripts/install-latest-release.sh`](scripts/install-latest-release.sh):

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernel-TurboDecky-GamerPc/main/scripts/install-latest-release.sh" \
  | sh
```

O script consulta `/releases/latest`, escolhe o asset
`turbodecky-linux-*.zip`, valida e descompacta todos os `.deb`, instala-os com
`dpkg`, corrige dependências com `apt-get -f install` e atualiza o GRUB. As
instruções completas estão em [INSTALL.md](INSTALL.md).
