#!/usr/bin/env bash
set -Eeuo pipefail

# kmod's depmod requires the release argument to start with a digit. The
# public TurboDecky identity intentionally starts with "linux.", so build
# package mode gives depmod a temporary numeric alias that points at the real
# module directory. The generated depmod files are therefore written into the
# final linux.* directory without changing uname -r, vermagic, or package
# names.

if (($# == 0)); then
  echo "depmod-turbodecky: missing kernel release" >&2
  exit 2
fi

args=("$@")
last=$(( ${#args[@]} - 1 ))
release="${args[$last]}"

if [[ "$release" != linux.* ]]; then
  real_depmod="${TURBODECKY_REAL_DEPMOD:-$(command -v depmod || true)}"
  if [[ -z "$real_depmod" ]]; then
    echo "depmod-turbodecky: depmod was not found" >&2
    exit 127
  fi
  exec "$real_depmod" "${args[@]}"
fi

base_dir="/"
for ((index = 0; index < last; index++)); do
  if [[ "${args[$index]}" == "-b" ]]; then
    if ((index + 1 >= last)); then
      echo "depmod-turbodecky: -b has no base directory" >&2
      exit 2
    fi
    base_dir="${args[$((index + 1))]}"
    break
  fi
done

module_root="$base_dir/lib/modules"
real_dir="$module_root/$release"
alias_release="1"
alias_dir="$module_root/$alias_release"

if [[ ! -d "$real_dir" ]]; then
  echo "depmod-turbodecky: module directory does not exist: $real_dir" >&2
  exit 1
fi
if [[ -e "$alias_dir" || -L "$alias_dir" ]]; then
  echo "depmod-turbodecky: temporary alias already exists: $alias_dir" >&2
  exit 1
fi

ln -s "$release" "$alias_dir"
cleanup() {
  rm -f -- "$alias_dir"
}
trap cleanup EXIT

args[$last]="$alias_release"
real_depmod="${TURBODECKY_REAL_DEPMOD:-$(command -v depmod || true)}"
if [[ -z "$real_depmod" ]]; then
  echo "depmod-turbodecky: depmod was not found" >&2
  exit 127
fi

set +e
"$real_depmod" "${args[@]}"
status=$?
set -e
exit "$status"
