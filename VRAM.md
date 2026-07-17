# Proteção de VRAM por cgroups de memória de dispositivo

Esta branch integra a série de seis correções TTM/dmem descrita por Pixelcluster e distribuída pelo CachyOS como um patch consolidado e reproduzível.

## Kernel

O build busca somente o arquivo `7.0/misc/0001-cgroup-vram.patch` do commit fixado `ea739d734ec179864b21446856315bc49f7c52fa` em `CachyOS/kernel-patches`. A aplicação exige ausência de rejeitos e valida as alterações em TTM e no controlador dmem.

A configuração final força:

```text
CONFIG_CGROUPS=y
CONFIG_CGROUP_DMEM=y
CONFIG_DRM_AMDGPU=m
```

O patch faz com que alocações protegidas por `dmem.low`/`dmem.min` possam remover da VRAM buffers não protegidos antes de cair para GTT. Isso é principalmente útil sob contenção de VRAM em GPUs dedicadas AMD e em outros drivers TTM que implementam dmem.

## Userspace ativo por padrão

O build também gera `turbodecky-vram_0.1.2-1_amd64.deb`. O pacote compila a tag oficial `0.1.2` do `dmemcg-booster` da Valve e instala:

- `/usr/bin/dmemcg-booster`;
- serviço systemd global;
- serviço systemd do usuário;
- presets para habilitar ambos automaticamente;
- `turbodecky-vram-status` para diagnóstico.

O daemon exige systemd, cgroups v2, D-Bus e as bibliotecas de runtime declaradas no pacote. As dependências de compilação são instaladas automaticamente no runner quando necessário.

## Aplicativo em primeiro plano

O daemon propaga e habilita o controlador dmem, mas uma integração de primeiro plano precisa marcar o jogo protegido. Em desktops não KDE, use uma versão do Gamescope que contenha o commit Valve `62b49b030cf76a0946292dd8379a87dcd16979ee` ou implementação posterior equivalente. No KDE Plasma, `plasma-foreground-booster` pode exercer essa função.

O pacote recomenda `gamescope`, mas não substitui automaticamente o pacote da distribuição porque uma compilação completa do Gamescope adicionaria uma segunda pilha gráfica e dependências não relacionadas ao kernel.

Após instalar e reiniciar no kernel TurboDecky:

```bash
turbodecky-vram-status
```
