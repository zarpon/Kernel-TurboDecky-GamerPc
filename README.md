# Kernel TurboDecky GamerPc

Kernel Linux experimental otimizado para entusiastas que querem alto
desempenho em multimídia e jogos nas distribuições Debian, Ubuntu e derivados.
O repositório `Kernel-TurboDecky-GamerPc` acompanha a versão estável mais
recente publicada pelo kernel.org.

O projeto é experimental. O resultado varia conforme CPU, GPU, firmware,
driver gráfico, temperatura, jogo e carga de trabalho. Mantenha um kernel
anterior instalado até validar o primeiro boot.

## Compatibilidade de hardware

O pacote publicado é destinado a:

- Debian, Ubuntu e derivados que usem `.deb`, `dpkg` e `apt`;
- desktops, computadores portáteis e workstations x86-64/amd64;
- CPUs Intel, AMD e demais famílias x86-64 habilitadas pela configuração
  upstream;
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

- **Responsividade e jogos:** Infinity CPU/EEVDF e POC Selector favorecem
  tarefas interativas, controlam o orçamento de CPU por EMA e escolhem CPUs
  ociosas considerando a topologia de cache, o que pode melhorar a latência
  percebida e a consistência do frame time.
- **Tarefas RT e espera:** Infinity v3 também adiciona hooks de EMA para
  SCHED_FIFO/SCHED_RR e bypass seguro da proteção de fatia para tarefas que
  estão entrando em espera futex; isso não transforma o kernel em PREEMPT_RT.
- **Resposta de frequência:** REFLEX acelera a transição de ocioso para ativo,
  enquanto NAP escolhe estados de idle de forma adaptativa.
- **I/O e carregamento:** ADIOS ajusta deadlines e lotes conforme a latência
  do dispositivo, favorecendo operações síncronas durante acesso intenso a
  disco.
- **Memória:** Marie LRU reduz reclaim agressivo e thrashing; ZRAM-IR usa LZ4
  e ZSTD para manter mais páginas úteis sob pressão de memória.
- **Gerenciamento de VRAM:** o controlador `dmem` e o port TTM priorizam o
  despejo de buffers não protegidos e respeitam `dmem.low` e `dmem.min`. Em
  GPUs AMD sob pressão de VRAM, isso pode reduzir migrações indesejadas para
  GTT, travamentos curtos e variações de frame time.
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

Durante `bindeb-pkg`, o `depmod` do kmod exige que o argumento de versão comece
por um dígito. Como a identidade pública começa por `linux.`, o workflow cria
um alias numérico temporário somente para gerar os mapas de dependências e o
remove ao terminar; o `uname -r`, os módulos instalados e os pacotes mantêm o
nome TurboDecky completo.

Fonte: [Linux stable](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git).
O build clona a tag `v<versão>` e confirma a versão pelo Makefile antes de
aplicar qualquer patch.

## Patchset de desempenho

- **Infinity scheduler v3** — [branch v3 / patch stable/linux-7.1-infinity/0001](https://github.com/galpt/infinity-scheduler/blob/v3/patches/stable/linux-7.1-infinity/0001-infinity-scheduler.patch): scheduler de CPU integrado ao CFS/EEVDF, modulação de vruntime e fatias por EMA, bypass futex e hooks de RT. O patch não inclui DRM/GPU; o scheduler DRM upstream é mantido.
- **POC Selector 2.6.2r2** — [firelzrd/poc-selector](https://github.com/firelzrd/poc-selector): seleção eficiente de CPU ociosa considerando LLC e topologia.
- **NAP CPUIdle 0.5.0** — [firelzrd/nap](https://github.com/firelzrd/nap): predição adaptativa do estado de idle.
- **REFLEX CPUFreq 0.3.1** — [firelzrd/reflex](https://github.com/firelzrd/reflex): resposta rápida idle→busy combinada com PELT.
- **Marie LRU 0.7.7** — [firelzrd/lru_marie](https://github.com/firelzrd/lru_marie): reclaim adaptativo para desktops.
- **ADIOS 3.2.0** — [firelzrd/adios](https://github.com/firelzrd/adios): scheduler de I/O adaptativo, embutido e padrão.
- **ZRAM-IR 1.2** — [firelzrd/zram-ir](https://github.com/firelzrd/zram-ir): LZ4 primário e ZSTD como segunda prioridade.
- **VRAM por cgroup / TTM** — política derivada dos patches de pixelcluster,
  agregada e fixada no commit
  [`ea739d734ec179864b21446856315bc49f7c52fa`](https://github.com/CachyOS/kernel-patches/tree/ea739d734ec179864b21446856315bc49f7c52fa/7.0/misc).
  O port habilita `CONFIG_CGROUP_DMEM=y`, separa a cobrança do cgroup da
  alocação TTM, considera proteção `low/min` durante despejo e seleciona
  buffers não protegidos antes dos buffers do jogo.

O workflow também resolve e registra C23 libbpf, Clear Linux, fsync via
`FUTEX_WAIT_MULTIPLE`, O3, Bluetooth SSP, workaround libbpf, otimizações
universais de CPU sem selecioná-las para um modelo específico, compatibilidade
DKMS-Clang, Polly, diagnósticos de firmware, três correções minstrel_ht e
correções ath11k. As quatro fontes OpenWrt do commit
[`0ff1553b`](https://github.com/openwrt/openwrt/tree/0ff1553bd731c0db28043fc9caab90bdc32587f3)
ficam versionadas em `patches/openwrt-0ff1553/`; o rework de downgrade possui
um port com contexto Linux 7.1. Cada patch tem fonte, commit ou URL, SHA-256,
tentativa de aplicação, detecção de integração prévia e relatório de rejeitos.

## Gerenciamento de VRAM por cgroup

A integração de VRAM não aumenta a capacidade física da placa e não reserva
uma quantidade fixa de memória para todos os jogos. Ela fornece ao TTM e ao
controlador `dmem` informações de prioridade por cgroup para tomar decisões
melhores quando a VRAM está próxima do limite.

### O que muda

- a cobrança da memória do dispositivo é associada ao cgroup da aplicação;
- `dmem.low` fornece proteção de melhor esforço;
- `dmem.min` fornece proteção mais forte;
- buffers não protegidos são considerados primeiro para despejo;
- uma alocação protegida pode tentar recuperar VRAM antes de cair em um domínio
  mais lento, como GTT;
- a proteção entre cgroups irmãos considera o ancestral comum;
- o port para Linux 7.1 é aplicado por âncoras semânticas e não usa
  `patch --fuzz`.

O pacote `turbodecky-vram` acompanha a Release e instala:

- `dmemcg-booster` 0.1.2;
- `dmemcg-booster-system.service`;
- `dmemcg-booster-user.service`;
- delegação de cgroup com `Delegate=yes`;
- o lançador `turbodecky-vram-run`.

Os serviços de sistema e usuário são habilitados por padrão durante a
instalação. Um reinício após instalar a Release é recomendado para garantir que
o novo kernel, a delegação do serviço de usuário e os controladores de cgroup
estejam ativos.

### Ativação automática e manual

Depois de instalar todos os pacotes `.deb` da Release, verifique os serviços:

```bash
systemctl status dmemcg-booster-system.service
systemctl --user status dmemcg-booster-user.service
```

Caso estejam desativados, habilite-os manualmente:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dmemcg-booster-system.service

systemctl --user daemon-reload
systemctl --user enable --now dmemcg-booster-user.service
```

Confirme que o kernel expõe o controlador de memória de dispositivos:

```bash
cat /sys/fs/cgroup/cgroup.controllers
```

A saída deve conter `dmem`. Uma verificação direta pode ser feita com:

```bash
tr ' ' '\n' < /sys/fs/cgroup/cgroup.controllers | grep '^dmem$'
```

Se `dmem` não aparecer, confirme que o sistema iniciou com o kernel
TurboDecky:

```bash
uname -r
```

O resultado deve seguir o formato
`linux.<versão>.turbodecky.release`.

### Steam

Para colocar um jogo da Steam em um escopo systemd próprio, use nas opções de
inicialização:

```text
turbodecky-vram-run %command%
```

Com gamescope:

```text
turbodecky-vram-run gamescope -f -- %command%
```

Adicione ao gamescope as opções de resolução, taxa de atualização e upscaling
adequadas ao computador. Versões recentes do gamescope podem identificar o
jogo em primeiro plano e complementar a proteção do cgroup.

### Jogos fora da Steam

Execute o jogo ou launcher pelo wrapper:

```bash
turbodecky-vram-run /caminho/para/o/jogo
```

Também é possível envolver um launcher:

```bash
turbodecky-vram-run heroic
turbodecky-vram-run lutris
```

O wrapper cria um escopo systemd separado. Para que a proteção seja ajustada
dinamicamente conforme a janela em primeiro plano, use uma integração
compatível do compositor ou launcher.

### KDE Plasma

No Plasma, `plasma-foreground-booster-dmemcg` pode complementar o
`dmemcg-booster` e atualizar a proteção conforme a janela ativa. Ele é
opcional e não é instalado pelo pacote genérico, porque adicionaria
dependências do Plasma e Qt a sistemas Cinnamon, GNOME e outros desktops.

### Compatibilidade e limitações

O benefício principal é esperado em GPUs AMD que usam AMDGPU e TTM,
especialmente modelos com 4 a 8 GiB de VRAM e jogos que ultrapassam ou se
aproximam do limite disponível.

- em uma GPU Intel sem TTM/AMDGPU, não há benefício direto da política de
  despejo de VRAM;
- o driver proprietário da NVIDIA não usa esta integração;
- quando existe VRAM livre, a diferença pode ser nula;
- a otimização procura reduzir stutter e decisões ruins de despejo, não garantir
  aumento de FPS médio;
- lançar o jogo em um escopo separado não substitui uma integração real de
  detecção da aplicação em primeiro plano.

Detalhes técnicos, procedência dos patches e informações de validação estão em
[VRAM.md](VRAM.md).

## Instalação automática da última Release

A última Release pode ser instalada pelo script versionado em
[`scripts/install-latest-release.sh`](scripts/install-latest-release.sh):

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernel-TurboDecky-GamerPc/main/scripts/install-latest-release.sh" \
  | sh
```

O script consulta `/releases/latest` e prefere o asset
`turbodecky-linux-*.zip`. Se a Release não tiver nenhum ZIP, ele baixa todos os
assets `.deb`, incluindo `turbodecky-vram`. Em ambos os modos, valida os
pacotes e a arquitetura, normaliza permissões, calcula a ordem de instalação
pelas dependências declaradas, usa `dpkg`, corrige dependências externas com
`apt-get -f install` e atualiza o GRUB.

Após a instalação, reinicie o computador e confirme o kernel com `uname -r`.
As instruções completas estão em [INSTALL.md](INSTALL.md).
