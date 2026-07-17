# Gerenciamento de VRAM por cgroup

Esta integração adiciona ao TurboDecky a política de alocação e despejo de
memória de GPU desenvolvida por pixelcluster para o controlador `dmem` e o
TTM. O objetivo é permitir que uma aplicação em primeiro plano, normalmente um
jogo, receba proteção de VRAM por cgroup enquanto buffers de aplicações de
fundo são escolhidos primeiro para despejo.

## Componentes

### Kernel

O build usa como fonte de procedência o patch agregado do CachyOS, fixado no
commit `ea739d734ec179864b21446856315bc49f7c52fa`, arquivo
`7.0/misc/0001-cgroup-vram.patch`. Esse agregado reúne os seis commits originais:

- `9d928b2c5af078304205c12c71fec4904860d8cc`
- `9a02490c9f7938a4ed8950f0d61bcf677f67c07b`
- `1f24ddd4ffd04f47a04bd84987f36dc545bc7421`
- `f6bde8345b0c66e9cd81fa368343d4438ac9b3b0`
- `68f051af747220ac7d1d74bec8d79f2cb3a58304`
- `9260440455cd61f2c90cca172bc9d3e83bf1206d`

O patch altera o TTM e o controlador de memória de dispositivos para:

- separar a cobrança do cgroup da alocação física do recurso;
- considerar `dmem.min` e `dmem.low` na seleção dos buffers a despejar;
- preservar primeiro buffers protegidos e procurar buffers não protegidos;
- calcular corretamente a proteção entre cgroups irmãos por ancestral comum;
- tentar liberar VRAM para uma alocação protegida antes de aceitar um domínio
  de memória mais lento.

`CONFIG_CGROUPS=y` e `CONFIG_CGROUP_DMEM=y` são forçados e verificados no
`final.config`.

O patch agregado foi preparado para Linux 7.0. Em Linux 7.1.3, a API TTM já
possui diferenças no tratamento de `-EAGAIN`. O TurboDecky tenta o patch bruto
somente quando o `dry-run` é limpo. Caso contrário, usa
`scripts/port-vram-cgroup.py`, que aplica as mesmas alterações por âncoras
semânticas únicas e falha diante de qualquer fonte ambígua. Não é usado
`patch --fuzz`.

O port também corrige o caminho de erro de
`dmem_cgroup_get_common_ancestor()`: se a criação do pool falhar depois de
`css_get()`, a referência CSS é liberada antes do retorno.

### Espaço de usuário

O pacote adicional `turbodecky-vram` contém:

- `dmemcg-booster` 0.1.2;
- `dmemcg-booster-system.service`, habilitado por padrão;
- `dmemcg-booster-user.service`, habilitado globalmente por padrão;
- delegação da hierarquia do usuário por `Delegate=yes`;
- `turbodecky-vram-run`, um lançador de escopo systemd para aplicações.

O build prefere a tag oficial `0.1.2` do repositório Valve/SteamOS. Se esse
servidor estiver indisponível, usa o port C auditável fixado no commit
`95162bdd9be9c4bd89d65cb558acb858c35f8bf6` de
`DistrictD64/dmemcg-booster`. Nenhum binário externo pré-compilado é publicado:
o executável é sempre compilado durante o workflow.

Dependências de compilação instaladas no runner:

- `cargo` e `rustc` para a fonte oficial;
- `gcc`, `make`, `pkg-config` e `libdbus-1-dev` para o fallback C;
- `libdrm-dev`;
- `git` e certificados CA.

Dependências do pacote instalado:

- `libc6`;
- `libdbus-1-3`;
- `libdrm2`;
- `systemd`;
- `dbus-user-session`.

`gamescope` é recomendado porque versões recentes conseguem identificar o jogo
e aplicar a proteção de primeiro plano. No Plasma, o pacote específico
`plasma-foreground-booster-dmemcg` pode ser usado como alternativa. Ele não é
uma dependência obrigatória do kernel genérico porque puxaria Qt 6, Plasma
Workspace e várias bibliotecas KDE para instalações Cinnamon, GNOME e outros
desktops.

## Uso

Os serviços são instalados e habilitados automaticamente. Para verificar:

```bash
systemctl status dmemcg-booster-system.service
systemctl --user status dmemcg-booster-user.service
cat /sys/fs/cgroup/cgroup.controllers
```

A lista de controladores deve conter `dmem`. Para executar uma aplicação em um
escopo systemd próprio:

```bash
turbodecky-vram-run comando argumentos
```

Como opção de inicialização da Steam:

```text
turbodecky-vram-run %command%
```

A criação do escopo organiza o processo no cgroup. A priorização efetiva da
aplicação em primeiro plano requer integração do compositor/launcher, como
`gamescope` recente ou `plasma-foreground-booster-dmemcg`.

## Hardware e efeito esperado

O benefício principal é para GPUs AMD que usam TTM/AMDGPU e enfrentam pressão
de VRAM, especialmente modelos com 4 a 8 GiB. A política não aumenta a
capacidade física da placa e não melhora FPS quando há VRAM livre; ela procura
reduzir alocações indesejadas em GTT e stutter causado por decisões ruins de
despejo.

Em uma máquina somente com Intel HD, como o HP 240 G4 com i3-5005U, a parte TTM
não oferece ganho direto. Ela permanece compilada para que o mesmo kernel seja
genérico e funcione em computadores com GPU AMD dedicada ou integrada.

## Validação

Antes do envio ao GitHub foram executados localmente:

- compilação Python dos integradores;
- validação `bash -n` dos scripts;
- geração e segunda aplicação idempotente do wrapper de build;
- aplicação semântica sobre uma base Linux 7.1 simulada;
- compilação com `-Werror` dos objetos portados `ttm_bo.o`,
  `ttm_resource.o` e `dmem.o` em um harness de API;
- montagem e inspeção do pacote Debian, incluindo serviços, links de ativação,
  dependências e permissões.

A validação local não substitui o link ThinLTO completo. O workflow de teste é
o teste final da árvore integral e do pacote real do `dmemcg-booster`.
