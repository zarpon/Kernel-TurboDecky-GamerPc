#!/bin/sh
# Download and install every Debian package from the latest TurboDecky release.
set -eu

umask 022

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

curl_common() {
  if [ -n "$TOKEN" ]; then
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 \
      -H "Authorization: Bearer $TOKEN" "$@"
  else
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 "$@"
  fi
}

api_release_manifest() {
  output="$1"
  json="$TMP_DIR/release.json"
  curl_common \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$RELEASE_API" -o "$json" || return 1

  python3 - "$json" >"$output" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)

tag = release.get("tag_name") or release.get("name") or "latest"
assets = release.get("assets") or []
preferred = [
    item for item in assets
    if item.get("name", "").startswith("turbodecky-linux-")
    and item.get("name", "").lower().endswith(".zip")
]
selected = (preferred or [
    item for item in assets if item.get("name", "").lower().endswith(".zip")
])[:1]

if not selected:
    raise SystemExit("nenhum asset ZIP foi encontrado na última Release")

item = selected[0]
name = item.get("name", "")
url = item.get("browser_download_url") or item.get("url", "")
if not name or not url:
    raise SystemExit("o asset ZIP selecionado não possui nome ou URL")
if name != os.path.basename(name) or any(char in name for char in "\\/\r\n\t"):
    raise SystemExit(f"nome de asset ZIP inválido: {name!r}")

print(tag)
print(name)
print(url)
PY
}

public_release_manifest() {
  output="$1"
  latest_headers="$TMP_DIR/latest.headers"
  latest_url="https://github.com/${REPOSITORY}/releases/latest"

  curl_common --head "$latest_url" -o "$latest_headers" || return 1
  tag="$(python3 - "$latest_headers" "$REPOSITORY" <<'PY'
import re
import sys
from urllib.parse import unquote

headers = open(sys.argv[1], encoding="iso-8859-1").read()
repository = re.escape(sys.argv[2])
matches = re.findall(
    rf"(?im)^location:\s*https://github\.com/{repository}/releases/tag/([^\s]+)\s*$",
    headers,
)
if not matches:
    raise SystemExit(1)
print(unquote(matches[-1]))
PY
)" || return 1

  assets_html="$TMP_DIR/assets.html"
  curl_common "https://github.com/${REPOSITORY}/releases/expanded_assets/${tag}" \
    -o "$assets_html" || return 1

  python3 - "$assets_html" "$REPOSITORY" "$tag" >"$output" <<'PY'
import html
import os
import re
import sys
from urllib.parse import urljoin

page = html.unescape(open(sys.argv[1], encoding="utf-8").read())
repository = sys.argv[2]
tag = sys.argv[3]
hrefs = re.findall(r'href=["\']([^"\']+)["\']', page)
candidates = []
for href in hrefs:
    name = os.path.basename(href.split("?", 1)[0])
    if name.startswith("turbodecky-linux-") and name.lower().endswith(".zip"):
        candidates.append((name, urljoin("https://github.com", href)))

if not candidates:
    for href in hrefs:
        name = os.path.basename(href.split("?", 1)[0])
        if name.lower().endswith(".zip"):
            candidates.append((name, urljoin("https://github.com", href)))

if not candidates:
    raise SystemExit("nenhum asset ZIP foi encontrado na página pública da Release")

name, url = candidates[0]
if name != os.path.basename(name) or any(char in name for char in "\\/\r\n\t"):
    raise SystemExit(f"nome de asset ZIP inválido: {name!r}")

print(tag)
print(name)
print(url)
PY
}

need curl
need python3
need unzip
need find
need dpkg
need dpkg-deb
need apt-get
need sed
need wc
need tr
need mktemp
need sha256sum

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
chmod 755 "$TMP_DIR"

MANIFEST="$TMP_DIR/release-manifest.txt"
if ! api_release_manifest "$MANIFEST"; then
  echo "turbodecky: API do GitHub indisponível; usando a página pública da Release." >&2
  public_release_manifest "$MANIFEST" ||
    die "não foi possível localizar a última Release pública de $REPOSITORY; confira a conexão ou exporte GITHUB_TOKEN/GH_TOKEN para repositório privado"
fi

RELEASE_TAG="$(sed -n '1p' "$MANIFEST")"
ASSET_NAME="$(sed -n '2p' "$MANIFEST")"
ASSET_URL="$(sed -n '3p' "$MANIFEST")"
[ -n "$RELEASE_TAG" ] || die "identificador da Release vazio"
[ -n "$ASSET_NAME" ] || die "nome do asset ZIP vazio"
[ -n "$ASSET_URL" ] || die "URL do asset ZIP vazia"

ZIP_PATH="$TMP_DIR/$ASSET_NAME"
DEB_DIR="$TMP_DIR/packages"
mkdir -p "$DEB_DIR"
chmod 755 "$DEB_DIR"

echo "Release selecionada: $RELEASE_TAG"
echo "Baixando ZIP: $ASSET_NAME"
curl_common "$ASSET_URL" -o "$ZIP_PATH" || die "falha ao baixar o asset ZIP"
chmod 644 "$ZIP_PATH"
unzip -tq "$ZIP_PATH" || die "o ZIP baixado está inválido"
unzip -q "$ZIP_PATH" -d "$DEB_DIR"

find "$DEB_DIR" -type d -exec chmod 755 {} +
find "$DEB_DIR" -type f -name '*.deb' -exec chmod 644 {} +

if [ -f "$DEB_DIR/SHA256SUMS" ]; then
  (
    cd "$DEB_DIR"
    sha256sum --check SHA256SUMS
  ) || die "a verificação SHA-256 dos pacotes falhou"
fi

DEB_COUNT="$(find "$DEB_DIR" -type f -name '*.deb' | wc -l | tr -d '[:space:]')"
[ "$DEB_COUNT" -gt 0 ] || die "nenhum pacote .deb foi encontrado"
echo "Pacotes encontrados: $DEB_COUNT"

PACKAGE_LIST="$TMP_DIR/packages.txt"
find "$DEB_DIR" -type f -name '*.deb' -print | sort >"$PACKAGE_LIST"

# apt instala o conjunto local, resolve a ordem interna e baixa somente
# dependências externas necessárias.
set --
while IFS= read -r package; do
  [ -n "$package" ] || continue
  package_arch="$(dpkg-deb -f "$package" Architecture)"
  [ "$package_arch" = all ] || [ "$package_arch" = "$ARCH" ] ||
    die "arquitetura incompatível em $(basename "$package"): $package_arch"
  set -- "$@" "$package"
done <"$PACKAGE_LIST"

[ "$#" -gt 0 ] || die "nenhum pacote válido foi encontrado"
run_privileged apt-get install -y "$@"

if command -v update-grub >/dev/null 2>&1; then
  run_privileged update-grub
fi

echo "Instalação concluída. Reinicie e confirme com: uname -r"
