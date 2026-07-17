# Instalação da última Release

O instalador `scripts/install-latest-release.sh` consulta a última GitHub
Release não preliminar e procura primeiro o asset ZIP
`turbodecky-linux-*.zip`. Quando não existe nenhum ZIP, ele localiza e baixa
todos os assets `.deb` publicados na mesma Release.

Antes da instalação, o script valida a arquitetura declarada nos pacotes,
rejeita nomes inválidos ou pacotes duplicados, aplica permissões `0755` aos
diretórios temporários e `0644` aos arquivos `.deb`, e calcula a ordem de
instalação usando os campos `Pre-Depends`, `Depends` e `Provides`. Ao final,
corrige dependências externas com `apt-get -f install` e atualiza o GRUB.

## Comando rápido

O repositório público é `zarpon/Kernel-TurboDecky-GamerPc` e o token não é
necessário:

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernel-TurboDecky-GamerPc/main/scripts/install-latest-release.sh" \
  | sh
```

O instalador aceita somente sistemas Debian/Ubuntu `amd64` e não impõe limite
de CPUs. Ele usa `sudo` quando não é executado como root. Para revisar o
script antes de executá-lo:

```bash
curl -fL \
  "https://raw.githubusercontent.com/zarpon/Kernel-TurboDecky-GamerPc/main/scripts/install-latest-release.sh" \
  -o install-turbodecky.sh
less install-turbodecky.sh
sh install-turbodecky.sh
```

## Fork privado

Para um fork privado, exporte um token do GitHub com permissão de leitura do
conteúdo:

```bash
export GITHUB_TOKEN='SEU_TOKEN_COM_LEITURA_DO_REPOSITORIO'
export TURBODECKY_REPOSITORY='seu-usuario/Kernel-TurboDecky-GamerPc'
curl -fsSL \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github.raw+json" \
  "https://raw.githubusercontent.com/zarpon/Kernel-TurboDecky-GamerPc/main/scripts/install-latest-release.sh" \
  | sh
```

`GH_TOKEN` também é aceito. O token é usado para consultar a API e baixar os
assets da Release pela API do GitHub.

## Após instalar

Mantenha o kernel anterior no menu do GRUB, reinicie e confirme o kernel em
execução:

```bash
uname -r
dpkg -l 'linux-*turbodecky*'
```

O pacote `turbodecky-tuning` pode aplicar políticas de sysctl, zram, THP e
GRUB. Em particular, `mitigations=off nowatchdog` favorece desempenho, mas
reduz proteções de segurança e desativa o watchdog do kernel. Revise essa
política antes de usar o kernel em máquinas expostas ou de produção.
