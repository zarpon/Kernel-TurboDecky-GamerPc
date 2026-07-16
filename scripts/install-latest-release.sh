#!/bin/sh
# Download and install every Debian package from the latest TurboDecky release.
set -eu

REPOSITORY="${TURBODECKY_REPOSITORY:-${KERNELNOTE_REPOSITORY:-zarpon/Kernel-TurboDecky-GamerPc}}"
RELEASE_API="${TURBODECKY_RELEASE_API:-${KERNELNOTE_RELEASE_API:-https://api.github.com/repos/${REPOSITORY}/releases/latest}}"
TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

die() {
  echo "turbodecky: $*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "comando obrigatório não encontrado: $1"
}

curl_download() {
  url="$1"
  output="$2"
  if [ -n "$TOKEN" ]; then
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -H "Authorization: Bearer $TOKEN" \
      "$url" -o "$output"
  else
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "$url" -o "$output"
  fi
}

need curl
need python3
need unzip
need find
need dpkg
need apt-get
need sed
need wc
need tr
need mktemp

ARCH="$(dpkg --print-architecture)"
[ "$ARCH" = amd64 ] || die "esta Release fornece pacotes amd64; arquitetura detectada: $ARCH"

if [ "$(id -u)" -eq 0 ]; then
  run_privileged() { "$@"; }
else
  need sudo
  run_privileged() { sudo "$@"; }
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/turbodecky-install.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

RELEASE_JSON="$TMP_DIR/release.json"
if ! curl_download "$RELEASE_API" "$RELEASE_JSON"; then
  die "não foi possível consultar a última Release de $REPOSITORY; confira a conexão ou, em um fork privado, exporte GITHUB_TOKEN ou GH_TOKEN"
fi

if ! RELEASE_INFO="$(python3 - "$RELEASE_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)

assets = release.get("assets", [])
preferred = [
    item for item in assets
    if item.get("name", "").startswith("turbodecky-linux-")
    and item.get("name", "").endswith(".zip")
]
candidates = preferred or [
    item for item in assets if item.get("name", "").endswith(".zip")
]
if not candidates:
    raise SystemExit("nenhum asset ZIP foi encontrado na última Release")

asset = candidates[0]
url = asset.get("browser_download_url")
if not url:
    raise SystemExit("o asset ZIP não possui browser_download_url")

print(release.get("tag_name") or release.get("name") or "latest")
print(asset["name"])
print(url)
PY
)"; then
  die "não foi possível identificar o asset ZIP da última Release"
fi

RELEASE_TAG="$(printf '%s\n' "$RELEASE_INFO" | sed -n '1p')"
ASSET_NAME="$(printf '%s\n' "$RELEASE_INFO" | sed -n '2p')"
ASSET_URL="$(printf '%s\n' "$RELEASE_INFO" | sed -n '3p')"
[ -n "$ASSET_NAME" ] || die "nome do asset ZIP vazio"
[ -n "$ASSET_URL" ] || die "URL do asset ZIP vazia"

ZIP_PATH="$TMP_DIR/$ASSET_NAME"
EXTRACT_DIR="$TMP_DIR/extracted"
mkdir -p "$EXTRACT_DIR"

echo "Release selecionada: $RELEASE_TAG"
echo "Baixando: $ASSET_NAME"
curl_download "$ASSET_URL" "$ZIP_PATH" || die "falha ao baixar o asset ZIP"
unzip -tq "$ZIP_PATH" || die "o ZIP baixado está inválido"
unzip -q "$ZIP_PATH" -d "$EXTRACT_DIR"

DEB_COUNT="$(find "$EXTRACT_DIR" -type f -name '*.deb' | wc -l | tr -d '[:space:]')"
[ "$DEB_COUNT" -gt 0 ] || die "nenhum pacote .deb foi encontrado no ZIP"
echo "Pacotes encontrados: $DEB_COUNT"

DPKG_STATUS=0
if [ "$(id -u)" -eq 0 ]; then
  find "$EXTRACT_DIR" -type f -name '*.deb' -exec dpkg -i {} + || DPKG_STATUS=$?
else
  find "$EXTRACT_DIR" -type f -name '*.deb' -exec sudo dpkg -i {} + || DPKG_STATUS=$?
fi

# Resolve dependências do pacote de tuning e eventuais atualizações de headers.
run_privileged apt-get -f install -y

if command -v update-grub >/dev/null 2>&1; then
  run_privileged update-grub
fi

if [ "$DPKG_STATUS" -ne 0 ]; then
  echo "dpkg precisou de uma segunda passagem; as dependências foram corrigidas pelo apt." >&2
fi

echo "Instalação concluída. Reinicie e confirme com: uname -r"
