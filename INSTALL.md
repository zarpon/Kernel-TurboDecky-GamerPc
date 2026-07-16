# Instalação da última Release

O instalador `scripts/install-latest-release.sh` consulta a última GitHub
Release não preliminar, localiza o asset ZIP `kernelnote-linux-*.zip`, valida o
arquivo, descompacta-o e instala todos os pacotes `.deb`. Ao final, corrige
dependências com `apt-get -f install` e atualiza o GRUB.

## Comando rápido

O repositório é público e o token não é necessário:

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernelnote/main/scripts/install-latest-release.sh" \
  | sh
```

O instalador aceita somente sistemas Debian/Ubuntu `amd64`. Ele usa `sudo`
quando não é executado como root. Para revisar o script antes de executá-lo,
baixe-o sem o pipe:

```bash
curl -fL \
  "https://raw.githubusercontent.com/zarpon/Kernelnote/main/scripts/install-latest-release.sh" \
  -o install-kernelnote.sh
less install-kernelnote.sh
sh install-kernelnote.sh
```

## Fork privado

Para um fork privado, exporte um token do GitHub com permissão de leitura do
conteúdo antes de executar o mesmo script:

```bash
export GITHUB_TOKEN='SEU_TOKEN_COM_LEITURA_DO_REPOSITORIO'
export KERNELNOTE_REPOSITORY='seu-usuario/Kernelnote'
curl -fsSL \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github.raw+json" \
  "https://raw.githubusercontent.com/zarpon/Kernelnote/main/scripts/install-latest-release.sh" \
  | sh
```

`GH_TOKEN` também é aceito. O token é usado pelo script para consultar a API e
baixar o asset da Release.

## Após instalar

Mantenha o kernel anterior no menu do GRUB, reinicie e confirme o kernel em
execução:

```bash
uname -r
dpkg -l 'linux-*zarpon*'
```

O pacote `kernelnote-tuning` pode aplicar políticas de sysctl, zram, THP e
GRUB. Em particular, `mitigations=off nowatchdog` favorece desempenho, mas
reduz proteções de segurança e desativa o watchdog do kernel. Revise essa
política antes de usar o kernel em máquinas expostas ou de produção.
