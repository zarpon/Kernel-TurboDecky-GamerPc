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

curl_download() {
  url="$1"
  output="$2"
  accept="${3:-application/octet-stream}"
  if [ -n "$TOKEN" ]; then
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 \
      -H "Accept: $accept" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -H "Authorization: Bearer $TOKEN" \
      "$url" -o "$output"
  else
    curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 \
      -H "Accept: $accept" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "$url" -o "$output"
  fi
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

RELEASE_JSON="$TMP_DIR/release.json"
if ! curl_download "$RELEASE_API" "$RELEASE_JSON" "application/vnd.github+json"; then
  die "não foi possível consultar a última Release de $REPOSITORY; confira a conexão ou, em um fork privado, exporte GITHUB_TOKEN ou GH_TOKEN"
fi

ASSET_MANIFEST="$TMP_DIR/assets.tsv"
if ! python3 - "$RELEASE_JSON" >"$ASSET_MANIFEST" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)

assets = release.get("assets", [])
tag = release.get("tag_name") or release.get("name") or "latest"

preferred = [
    item for item in assets
    if item.get("name", "").startswith("turbodecky-linux-")
    and item.get("name", "").lower().endswith(".zip")
]
zip_assets = preferred or [
    item for item in assets if item.get("name", "").lower().endswith(".zip")
]

if zip_assets:
    selected = zip_assets[0]
    name = selected.get("name", "")
    url = selected.get("url") or selected.get("browser_download_url", "")
    if not name or not url:
        raise SystemExit("o asset ZIP selecionado não possui nome ou URL")
    if name != os.path.basename(name) or any(char in name for char in "\\/\r\n\t"):
        raise SystemExit(f"nome de asset ZIP inválido: {name!r}")
    print("zip")
    print(tag)
    print(name)
    print(url)
    raise SystemExit(0)

deb_assets = [
    item for item in assets if item.get("name", "").lower().endswith(".deb")
]
if not deb_assets:
    raise SystemExit("nenhum asset ZIP ou pacote DEB foi encontrado na última Release")

seen = set()
validated = []
for item in deb_assets:
    name = item.get("name", "")
    url = item.get("url") or item.get("browser_download_url", "")
    if not name or not url:
        raise SystemExit("um asset DEB não possui nome ou URL")
    if name != os.path.basename(name) or any(char in name for char in "\\/\r\n\t"):
        raise SystemExit(f"nome de asset DEB inválido: {name!r}")
    if name in seen:
        raise SystemExit(f"asset DEB duplicado: {name}")
    seen.add(name)
    validated.append((name, url))

print("deb")
print(tag)
for name, url in sorted(validated):
    print(f"{name}\t{url}")
PY
then
  die "não foi possível identificar os assets instaláveis da última Release"
fi

ASSET_MODE="$(sed -n '1p' "$ASSET_MANIFEST")"
RELEASE_TAG="$(sed -n '2p' "$ASSET_MANIFEST")"
[ -n "$RELEASE_TAG" ] || die "identificador da Release vazio"

DEB_DIR="$TMP_DIR/packages"
mkdir -p "$DEB_DIR"
chmod 755 "$DEB_DIR"

echo "Release selecionada: $RELEASE_TAG"

case "$ASSET_MODE" in
  zip)
    ASSET_NAME="$(sed -n '3p' "$ASSET_MANIFEST")"
    ASSET_URL="$(sed -n '4p' "$ASSET_MANIFEST")"
    [ -n "$ASSET_NAME" ] || die "nome do asset ZIP vazio"
    [ -n "$ASSET_URL" ] || die "URL do asset ZIP vazia"

    ZIP_PATH="$TMP_DIR/$ASSET_NAME"
    echo "Baixando ZIP: $ASSET_NAME"
    curl_download "$ASSET_URL" "$ZIP_PATH" || die "falha ao baixar o asset ZIP"
    chmod 644 "$ZIP_PATH"
    unzip -tq "$ZIP_PATH" || die "o ZIP baixado está inválido"
    unzip -q "$ZIP_PATH" -d "$DEB_DIR"
    ;;
  deb)
    DEB_MANIFEST="$TMP_DIR/deb-assets.tsv"
    sed '1,2d' "$ASSET_MANIFEST" >"$DEB_MANIFEST"
    while IFS='	' read -r ASSET_NAME ASSET_URL; do
      [ -n "$ASSET_NAME" ] || continue
      [ -n "$ASSET_URL" ] || die "URL vazia para o asset $ASSET_NAME"
      echo "Baixando DEB: $ASSET_NAME"
      curl_download "$ASSET_URL" "$DEB_DIR/$ASSET_NAME" || die "falha ao baixar o asset $ASSET_NAME"
      chmod 644 "$DEB_DIR/$ASSET_NAME"
    done <"$DEB_MANIFEST"
    ;;
  *)
    die "modo de asset desconhecido: $ASSET_MODE"
    ;;
esac

# Diretórios precisam ser atravessáveis pelo processo privilegiado; pacotes DEB
# são arquivos de dados e não devem receber bit de execução.
find "$DEB_DIR" -type d -exec chmod 755 {} +
find "$DEB_DIR" -type f -name '*.deb' -exec chmod 644 {} +

DEB_COUNT="$(find "$DEB_DIR" -type f -name '*.deb' | wc -l | tr -d '[:space:]')"
[ "$DEB_COUNT" -gt 0 ] || die "nenhum pacote .deb foi encontrado"
echo "Pacotes encontrados: $DEB_COUNT"

INSTALL_ORDER="$TMP_DIR/install-order.txt"
if ! python3 - "$DEB_DIR" "$ARCH" >"$INSTALL_ORDER" <<'PY'
import collections
import os
import re
import subprocess
import sys

root = sys.argv[1]
host_arch = sys.argv[2]
paths = []
for current_root, _, filenames in os.walk(root):
    for filename in filenames:
        if filename.lower().endswith(".deb"):
            paths.append(os.path.join(current_root, filename))
paths.sort()

if not paths:
    raise SystemExit("nenhum pacote DEB para ordenar")

def field(path, name):
    result = subprocess.run(
        ["dpkg-deb", "-f", path, name],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()

def dependency_names(value):
    groups = []
    for group in value.split(","):
        alternatives = []
        for item in group.split("|"):
            item = re.sub(r"\([^)]*\)", "", item)
            item = re.sub(r"\[[^]]*\]", "", item)
            item = re.sub(r"<[^>]*>", "", item).strip()
            if not item:
                continue
            name = item.split()[0].split(":", 1)[0]
            if name:
                alternatives.append(name)
        if alternatives:
            groups.append(alternatives)
    return groups

def priority(package):
    if package.startswith("linux-headers-") and (package.endswith("-common") or "common" in package):
        return 10
    if package == "linux-libc-dev" or package.startswith("linux-libc-dev-"):
        return 20
    if package.startswith("linux-headers-"):
        return 30
    if package.startswith("linux-modules-extra-"):
        return 45
    if package.startswith("linux-modules-"):
        return 40
    if package.startswith("linux-image-") and package.endswith("-dbg"):
        return 60
    if package.startswith("linux-image-"):
        return 50
    if package.startswith("linux-tools-"):
        return 70
    if package.startswith("turbodecky-"):
        return 80
    return 90

packages = {}
metadata = {}
providers = collections.defaultdict(set)
for path in paths:
    package = field(path, "Package")
    architecture = field(path, "Architecture")
    if not package:
        raise SystemExit(f"pacote sem campo Package: {path}")
    if architecture not in ("all", host_arch):
        raise SystemExit(
            f"arquitetura incompatível em {os.path.basename(path)}: "
            f"{architecture}; esperado {host_arch} ou all"
        )
    if package in packages:
        raise SystemExit(f"mais de um DEB fornece o pacote {package}")
    packages[package] = path
    provides = field(path, "Provides")
    for provided in dependency_names(provides):
        for name in provided:
            providers[name].add(package)
    metadata[package] = {
        "depends": dependency_names(
            ",".join(filter(None, [field(path, "Pre-Depends"), field(path, "Depends")]))
        )
    }

edges = collections.defaultdict(set)
indegree = {package: 0 for package in packages}
for package, data in metadata.items():
    for alternatives in data["depends"]:
        dependency = next((name for name in alternatives if name in packages), None)
        if dependency is None:
            for name in alternatives:
                candidates = sorted(providers.get(name, ()), key=lambda p: (priority(p), p))
                if candidates:
                    dependency = candidates[0]
                    break
        if dependency and dependency != package and package not in edges[dependency]:
            edges[dependency].add(package)
            indegree[package] += 1

ready = sorted(
    (package for package, count in indegree.items() if count == 0),
    key=lambda p: (priority(p), p, packages[p]),
)
ordered = []
while ready:
    package = ready.pop(0)
    ordered.append(package)
    for dependent in sorted(edges[package], key=lambda p: (priority(p), p, packages[p])):
        indegree[dependent] -= 1
        if indegree[dependent] == 0:
            ready.append(dependent)
            ready.sort(key=lambda p: (priority(p), p, packages[p]))

# Ciclos de dependência não impedem o dpkg de desempacotar o conjunto. Mantém-se
# uma ordem determinística e deixa-se a configuração final para apt-get -f.
remaining = sorted(
    (package for package in packages if package not in ordered),
    key=lambda p: (priority(p), p, packages[p]),
)
ordered.extend(remaining)

for package in ordered:
    print(packages[package])
PY
then
  die "não foi possível validar e ordenar os pacotes DEB"
fi

DPKG_STATUS=0
while IFS= read -r PACKAGE_PATH; do
  [ -n "$PACKAGE_PATH" ] || continue
  echo "Instalando: $(dpkg-deb -f "$PACKAGE_PATH" Package)"
  run_privileged dpkg -i "$PACKAGE_PATH" || DPKG_STATUS=$?
done <"$INSTALL_ORDER"

# Resolve dependências externas, configura pacotes que ficaram pendentes e
# conclui ciclos que o dpkg não conseguiu configurar na primeira passagem.
run_privileged apt-get -f install -y

if command -v update-grub >/dev/null 2>&1; then
  run_privileged update-grub
fi

if [ "$DPKG_STATUS" -ne 0 ]; then
  echo "dpkg precisou de uma segunda passagem; as dependências foram corrigidas pelo apt." >&2
fi

echo "Instalação concluída. Reinicie e confirme com: uname -r"
