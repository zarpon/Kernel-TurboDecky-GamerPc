# Kernelnote Linux generic zarpon

Kernel Linux experimental otimizado para entusiastas que querem obter o
melhor desempenho possível em multimídia e jogos nas distribuições Debian e
Ubuntu. A branch `main` acompanha a versão estável mais recente publicada pelo
kernel.org e combina otimizações de escalonamento, CPU, memória e I/O com o
conjunto de drivers upstream para hardware amd64.

O projeto é experimental: os ganhos variam conforme a CPU, GPU, firmware,
driver gráfico, jogo e carga de trabalho. Mantenha um kernel anterior instalado
até validar o primeiro boot.

## Compatibilidade de hardware

O pacote publicado é destinado a:

- Debian, Ubuntu e derivados que usem pacotes `.deb`, `dpkg` e `apt`;
- sistemas `amd64`/x86-64 em desktops, computadores portáteis e
  workstations;
- CPUs Intel Broadwell ou posteriores e CPUs AMD x86-64 modernas com conjunto
  de instruções compatível com o baseline Broadwell usado pelo patch de
  otimização universal;
- máquinas com múltiplos núcleos e threads, sem limite artificial baseado em
  um modelo específico.

A configuração mantém os drivers upstream para os dispositivos mais comuns de
gráficos Intel e AMD, armazenamento SATA/NVMe, USB, Ethernet, Wi-Fi,
Bluetooth, áudio HDA/USB, câmeras UVC/V4L2 e sistemas de arquivos usados em
Debian e Ubuntu. Hardware muito antigo anterior ao baseline Broadwell,
arquiteturas de 32 bits, ARM/ARM64 e dispositivos exóticos não são alvos
suportados por estes `.deb`.

O driver proprietário da NVIDIA não é incluído. Em placas NVIDIA, o módulo
DKMS precisa ser recompilado para o novo `uname -r`; com Secure Boot ativo, a
imagem e os módulos personalizados também precisam ser assinados ou o kernel
precisa ser selecionado após desativar essa verificação.

## Benefícios esperados

- **Responsividade e jogos:** BORE e POC Selector priorizam tarefas
  interativas e escolhem CPUs ociosas com atenção à topologia de cache, o que
  pode melhorar latência percebida e consistência do frame time.
- **Resposta de frequência:** REFLEX acelera a transição de ocioso para ativo,
  enquanto NAP escolhe estados de idle de forma adaptativa.
- **I/O e carregamento:** ADIOS ajusta deadlines e lotes conforme a latência
  do dispositivo, favorecendo operações síncronas durante acesso intenso a
  disco.
- **Memória:** Marie LRU reduz reclaim agressivo e thrashing; ZRAM-IR usa LZ4
  e ZSTD para manter mais páginas úteis sob pressão de memória.
- **Multimídia:** a configuração genérica preserva o caminho de drivers
  upstream para vídeo, áudio, câmeras, armazenamento e rede, evitando a poda
  de dispositivos que existia no perfil de uma única máquina.
- **Otimização de compilação:** Clang/LLVM, ThinLTO, Polly e O3 reduzem parte
  do custo de chamadas e loops do kernel, sem usar `-march=native` do runner.

Esses mecanismos não prometem aumento fixo de FPS. O resultado depende também
do driver da GPU, do governor usado pelo espaço de usuário, da temperatura e
da própria aplicação. A política inclui `mitigations=off` e `nowatchdog` no
kernel/ajustes de desempenho; isso pode reduzir latência, mas diminui
proteções contra vulnerabilidades de CPU e desativa os watchdogs. Quem
prioriza segurança deve manter as mitigações ativas e evitar o pacote de
ajustes até revisar seu conteúdo.

## Política de versão e identidade

No início de cada execução, o workflow consulta
[`releases.json`](https://www.kernel.org/releases.json), aceita somente uma
entrada `stable` não EOL e rejeita mainline, release candidates e versões
malformadas. O nome é derivado automaticamente:

```text
KERNELRELEASE=linux.<versão-estável>.zarpon.r1
```

O mesmo identificador é usado por `uname -r`, `vermagic`,
`/boot/vmlinuz-*` e `/lib/modules/*`. A versão, série, tag, data e origem da
fonte ficam registradas nos logs e nas notas da Release.

Fonte: [Linux stable](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git).
O build clona a tag `v<versão-estável>` e confirma a versão pelo Makefile
antes de aplicar qualquer patch.

## Patchset de desempenho

- **BORE 6.8.0-rc1** — [Masahito Suzuki / firelzrd](https://github.com/firelzrd/bore-scheduler): favorece responsividade de tarefas em rajadas sobre CFS/EEVDF.
- **POC Selector 2.6.2r2** — [firelzrd/poc-selector](https://github.com/firelzrd/poc-selector): seleção eficiente de CPU ociosa considerando LLC e topologia.
- **NAP CPUIdle 0.5.0** — [firelzrd/nap](https://github.com/firelzrd/nap): predição adaptativa do estado de idle.
- **REFLEX CPUFreq 0.3.1** — [firelzrd/reflex](https://github.com/firelzrd/reflex): resposta rápida idle→busy combinada com PELT.
- **Marie LRU 0.7.7** — [firelzrd/lru_marie](https://github.com/firelzrd/lru_marie): reclaim adaptativo voltado a desktops.
- **ADIOS 3.2.0** — [firelzrd/adios](https://github.com/firelzrd/adios): scheduler de I/O adaptativo, embutido e padrão.
- **ZRAM-IR 1.2** — [firelzrd/zram-ir](https://github.com/firelzrd/zram-ir): LZ4 primário e ZSTD como segunda prioridade.

O workflow também resolve e registra a série adicional solicitada: C23
libbpf, Clear Linux, fsync via `FUTEX_WAIT_MULTIPLE`, O3, Bluetooth SSP,
workaround libbpf, otimizações universais de CPU, compatibilidade DKMS-Clang,
Polly, diagnósticos de firmware, três correções minstrel_ht e correções
ath11k. Cada patch tem fonte, commit ou URL, SHA-256, tentativa de aplicação,
detecção de integração prévia e relatório de rejeitos.

## Configurações relevantes

```text
CONFIG_64BIT=y
CONFIG_X86_64=y
CONFIG_SMP=y
CONFIG_CPU_SUP_INTEL=y
CONFIG_CPU_SUP_AMD=y
CONFIG_MBROADWELL=y
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

O workflow compila a partir da branch `main`, usa Clang/LLD, cache de
compilação e swap temporário no runner. O modo `package` gera imagem, headers,
módulos, pacote de ajustes e `SHA256SUMS`.

```text
artefato: linux.<versão-estável>.zarpon.r1-debs
Release:  linux.<versão-estável>.zarpon.r1
```

O monitor verifica periodicamente se o kernel.org publicou uma versão estável
mais nova. Quando isso ocorre, atualiza a referência observada, recompila e
repete os ports necessários até a Release ser validada.

## Instalação automática da última Release

A última Release pode ser instalada pelo script versionado em
[`scripts/install-latest-release.sh`](scripts/install-latest-release.sh):

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernelnote/main/scripts/install-latest-release.sh" \
  | sh
```

O script consulta `/releases/latest`, escolhe o asset
`kernelnote-linux-*.zip`, valida e descompacta todos os `.deb`, instala-os com
`dpkg`, corrige dependências com `apt-get -f install` e atualiza o GRUB. As
instruções completas estão em [INSTALL.md](INSTALL.md).
