# Instalação da última Release

O instalador `scripts/install-latest-release.sh` consulta a última GitHub
Release não preliminar, localiza automaticamente o asset ZIP
`kernelnote-linux-*.zip`, descompacta-o e instala todos os pacotes `.deb` que
encontrar. Ao final, corrige dependências com `apt-get -f install` e atualiza o
GRUB.

## Repositório público

O repositório é público; o token não é necessário:

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/zarpon/Kernelnote/experimental/linux-7.1.3-generic-zarpon/scripts/install-latest-release.sh" \
  | sh
```

## Fork privado

Para um fork privado, exporte um token do GitHub com permissão de leitura do
conteúdo antes de executar o mesmo comando:

```bash
export GITHUB_TOKEN='SEU_TOKEN_COM_LEITURA_DO_REPOSITORIO'
curl -fsSL \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github.raw+json" \
  "https://raw.githubusercontent.com/zarpon/Kernelnote/experimental/linux-7.1.3-generic-zarpon/scripts/install-latest-release.sh" \
  | sh
```

O mesmo `GITHUB_TOKEN` será usado pelo script para consultar e baixar o asset
da Release. `GH_TOKEN` também é aceito. Para selecionar o fork:

```bash
export KERNELNOTE_REPOSITORY='seu-usuario/Kernelnote'
```

Mantenha o kernel anterior instalado até confirmar o boot com `uname -r`. O
pacote `kernelnote-tuning` pode alterar configurações de sysctl, zram e GRUB;
em particular, pode aplicar `mitigations=off nowatchdog`, que aumenta o
desempenho mas reduz proteções de segurança e o watchdog do kernel.
