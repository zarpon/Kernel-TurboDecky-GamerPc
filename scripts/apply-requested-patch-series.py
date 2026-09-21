#!/usr/bin/env python3
"""Inject the requested optimization, compatibility and wireless patch series."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)


def insert_requested_series_variable(text: str) -> str:
    preferred = re.compile(r"^PATCH_MARIE_VERSION=.*$", re.MULTILINE)
    fallback = re.compile(r"^MARIE_PATCH=.*$", re.MULTILINE)
    matches = list(preferred.finditer(text))
    if not matches:
        matches = list(fallback.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"requested series variables: expected one Marie variables anchor, "
            f"found {len(matches)}"
        )
    match = matches[0]
    return (
        text[: match.end()]
        + '\nREQUESTED_SERIES_DIR="$PATCHDIR/requested-series"'
        + text[match.end() :]
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-requested-patch-series.py <build-kernelnote-core.sh>")

    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    marker = 'REQUESTED_SERIES_DIR="$PATCHDIR/requested-series"'
    if marker in source:
        return

    source = insert_requested_series_variable(source)

    source = replace_once(
        source,
        'normalize_changed_whitespace() {\n',
        r'''fetch_candidate_patch() {
  local label="$1" output="$2" prefix="$3"
  shift 3
  local url candidate=0

  mkdir -p "$REQUESTED_SERIES_DIR"
  : > "$LOGDIR/${prefix}-fetch-attempts.log"
  for url in "$@"; do
    [[ -n "$url" ]] || continue
    candidate=$((candidate + 1))
    echo "Candidate $candidate: $url" | tee -a "$LOGDIR/${prefix}-fetch-attempts.log"
    if curl --fail --location --retry 3 --retry-all-errors --retry-delay 2 \
        --connect-timeout 30 --max-time 600 "$url" -o "$output.tmp" \
        >> "$LOGDIR/${prefix}-fetch-attempts.log" 2>&1 && \
        test -s "$output.tmp" && \
        grep -Eq '^(From [0-9a-f]{40} |From: |diff --git a/|--- (a/|/dev/null))' \
          "$output.tmp"; then
      mv "$output.tmp" "$output"
      {
        echo "Component: $label"
        echo "Selected URL: $url"
        echo "Candidate priority: $candidate"
        echo "SHA256: $(sha256sum "$output" | awk '{print $1}')"
        if ((candidate == 1)); then
          echo "Compatibility policy: Linux 7.1-specific or upstream-integrated source preferred"
        else
          echo "Compatibility policy: no usable Linux 7.1-specific source found; controlled port source selected"
        fi
      } | tee "$LOGDIR/${prefix}-provenance.txt"
      return 0
    fi
    echo "Rejected candidate: response is not a unified email/diff patch" \
      | tee -a "$LOGDIR/${prefix}-fetch-attempts.log"
    rm -f "$output.tmp"
  done

  echo "Unable to fetch any candidate for $label" >&2
  return 1
}

fetch_requested_patch_series() {
  echo "==> Resolving requested patch series, preferring Linux 7.1 revisions"

  fetch_candidate_patch "C23 libbpf fix" \
    "$REQUESTED_SERIES_DIR/08-c23-libbpf.patch" "08-c23-libbpf" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:c23_libbpf"

  fetch_candidate_patch "Clear Linux performance patches" \
    "$REQUESTED_SERIES_DIR/09-clear.patch" "09-clear" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:clear"

  fetch_candidate_patch "fsync FUTEX_WAIT_MULTIPLE compatibility" \
    "$REQUESTED_SERIES_DIR/10-fsync-futex-waitv.patch" "10-fsync" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:fsync"

  fetch_candidate_patch "Optimize harder O3" \
    "$REQUESTED_SERIES_DIR/11-o3.patch" "11-o3" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:o3"

  fetch_candidate_patch "Bluetooth SSP key-size check" \
    "$REQUESTED_SERIES_DIR/12-bt-ssp-key-size.patch" "12-bt-ssp" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:bt_ssp"

  fetch_candidate_patch "libbpf Wmaybe-uninitialized workaround" \
    "$REQUESTED_SERIES_DIR/13-libbpf-uninitialized.patch" "13-libbpf-uninitialized" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:libbpf_uninitialized"

  fetch_candidate_patch "Universal x86 CPU optimizations" \
    "$REQUESTED_SERIES_DIR/14-cpu-optimizations.patch" "14-cpu-optimizations" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:cpu_optimizations"

  fetch_candidate_patch "Clang DKMS compatibility" \
    "$REQUESTED_SERIES_DIR/15-dkms-clang.patch" "15-dkms-clang" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:dkms_clang"

  fetch_candidate_patch "Clang Polly support" \
    "$REQUESTED_SERIES_DIR/16-clang-polly.patch" "16-clang-polly" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:clang_polly"

  fetch_candidate_patch "Always print firmware file name" \
    "$REQUESTED_SERIES_DIR/17-firmware-name.patch" "17-firmware-name" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:firmware_name"

  fetch_candidate_patch "mac80211 minstrel fraction fix" \
    "$REQUESTED_SERIES_DIR/18-minstrel-frac.patch" "18-minstrel-frac" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:minstrel_frac"

  fetch_candidate_patch "mac80211 minstrel fluctuation reduction" \
    "$REQUESTED_SERIES_DIR/19-minstrel-fluctuation.patch" "19-minstrel-fluctuation" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:minstrel_fluctuation"

  fetch_candidate_patch "mac80211 minstrel rate downgrade rework" \
    "$REQUESTED_SERIES_DIR/20-minstrel-downgrade.patch" "20-minstrel-downgrade" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:minstrel_downgrade"

  fetch_candidate_patch "ath11k remapped CE 64-bit fix" \
    "$REQUESTED_SERIES_DIR/21-ath11k-remapped-ce.patch" "21-ath11k-remapped-ce" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:ath11k_remapped_ce"

  fetch_candidate_patch "ath11k DISABLE_KEY revert" \
    "$REQUESTED_SERIES_DIR/22-ath11k-disable-key.patch" "22-ath11k-disable-key" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:ath11k_disable_key"

  fetch_candidate_patch "ath11k Qualcomm upstream series" \
    "$REQUESTED_SERIES_DIR/23-ath11k-upstream.patch" "23-ath11k-upstream" \
    "__DYNAMIC_PATCH_LOCK_REQUIRED__:ath11k_upstream"
}

report_requested_rejects() {
  local label="$1" prefix="$2"
  {
    echo "==> Unresolved requested patch port: $label"
    find "$KERNELDIR" -name '*.rej' -printf '%P\n' | sort
    echo
    while IFS= read -r reject; do
      echo "### ${reject#$KERNELDIR/}"
      cat "$reject"
    done < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
  } | tee "$LOGDIR/${prefix}-port-rejects.log"
}

apply_requested_patch() {
  local label="$1" file="$2" prefix="$3"
  local strip status

  echo "==> Applying requested patch: $label"
  for strip in 1 0; do
    if patch --batch --forward --strip="$strip" --dry-run < "$file" \
        > "$LOGDIR/${prefix}.p${strip}.dry-run.log" 2>&1; then
      patch --batch --forward --strip="$strip" < "$file" \
        | tee "$LOGDIR/${prefix}.p${strip}.apply.log"
      find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
      normalize_changed_whitespace
      git diff --check | tee "$LOGDIR/${prefix}-diff-check.log"
      echo "applied strip=$strip" | tee "$LOGDIR/${prefix}-result.txt"
      return 0
    fi

    if patch --batch --reverse --strip="$strip" --dry-run < "$file" \
        > "$LOGDIR/${prefix}.p${strip}.reverse-dry-run.log" 2>&1; then
      echo "already integrated in Linux 7.1.3 or an earlier patch" \
        | tee "$LOGDIR/${prefix}-result.txt"
      find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
      return 0
    fi
  done

  echo "==> Clean application failed; attempting controlled port with fuzz <= 3"
  set +e
  patch --batch --forward --fuzz=3 --strip=1 < "$file" \
    > "$LOGDIR/${prefix}.fuzz-apply.log" 2>&1
  status=$?
  set -e
  cat "$LOGDIR/${prefix}.fuzz-apply.log"

  if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
    report_requested_rejects "$label" "$prefix"
    return 1
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
  normalize_changed_whitespace
  git diff --check | tee "$LOGDIR/${prefix}-diff-check.log"
  echo "ported strip=1 fuzz<=3" | tee "$LOGDIR/${prefix}-result.txt"
}

apply_requested_patch_series() {
  apply_requested_patch "C23 libbpf fix" "$REQUESTED_SERIES_DIR/08-c23-libbpf.patch" "08-c23-libbpf"
  apply_requested_patch "Clear Linux performance patches" "$REQUESTED_SERIES_DIR/09-clear.patch" "09-clear"
  apply_requested_patch "fsync FUTEX_WAIT_MULTIPLE compatibility" "$REQUESTED_SERIES_DIR/10-fsync-futex-waitv.patch" "10-fsync"
  apply_requested_patch "Optimize harder O3" "$REQUESTED_SERIES_DIR/11-o3.patch" "11-o3"
  apply_requested_patch "Bluetooth SSP key-size check" "$REQUESTED_SERIES_DIR/12-bt-ssp-key-size.patch" "12-bt-ssp"
  apply_requested_patch "libbpf Wmaybe-uninitialized workaround" "$REQUESTED_SERIES_DIR/13-libbpf-uninitialized.patch" "13-libbpf-uninitialized"
  apply_requested_patch "Universal x86 CPU optimizations" "$REQUESTED_SERIES_DIR/14-cpu-optimizations.patch" "14-cpu-optimizations"
  python3 "$ROOT/scripts/normalize-cpu-optimizations-generic.py" \
    "$KERNELDIR/arch/x86/Kconfig.cpu" "$KERNELDIR/arch/x86/Makefile" \
    | tee "$LOGDIR/14-cpu-optimizations-generic-normalization.log"
  ! grep -Fq 'depends on !X86_NATIVE_CPU' "$KERNELDIR/arch/x86/Kconfig.cpu"
  apply_requested_patch "Clang DKMS compatibility" "$REQUESTED_SERIES_DIR/15-dkms-clang.patch" "15-dkms-clang"
  apply_requested_patch "Clang Polly support" "$REQUESTED_SERIES_DIR/16-clang-polly.patch" "16-clang-polly"
  apply_requested_patch "Always print firmware file name" "$REQUESTED_SERIES_DIR/17-firmware-name.patch" "17-firmware-name"
  apply_requested_patch "mac80211 minstrel fraction fix" "$REQUESTED_SERIES_DIR/18-minstrel-frac.patch" "18-minstrel-frac"
  apply_requested_patch "mac80211 minstrel fluctuation reduction" "$REQUESTED_SERIES_DIR/19-minstrel-fluctuation.patch" "19-minstrel-fluctuation"
  apply_requested_patch "mac80211 minstrel rate downgrade rework" "$REQUESTED_SERIES_DIR/20-minstrel-downgrade.patch" "20-minstrel-downgrade"
  apply_requested_patch "ath11k remapped CE 64-bit fix" "$REQUESTED_SERIES_DIR/21-ath11k-remapped-ce.patch" "21-ath11k-remapped-ce"
  if grep -R -n -F 'ATH11K_CE_OFFSET' \
      "$KERNELDIR/drivers/net/wireless/ath/ath11k"; then
    echo "ath11k remapped CE port left ATH11K_CE_OFFSET references behind" >&2
    return 1
  fi
  apply_requested_patch "ath11k DISABLE_KEY revert" "$REQUESTED_SERIES_DIR/22-ath11k-disable-key.patch" "22-ath11k-disable-key"
  apply_requested_patch "ath11k Qualcomm upstream series" "$REQUESTED_SERIES_DIR/23-ath11k-upstream.patch" "23-ath11k-upstream"

  grep -Fq 'const char *res;' tools/lib/bpf/libbpf.c
  grep -Fq '#define FUTEX_WAIT_MULTIPLE' include/uapi/linux/futex.h
  grep -Fq 'config CC_OPTIMIZE_FOR_PERFORMANCE_O3' init/Kconfig
  grep -Fq 'config POLLY_CLANG' init/Kconfig
  echo "==> Requested patch series applied or confirmed integrated"
}

normalize_changed_whitespace() {
''',
        "requested series functions",
    )

    source = replace_once(
        source,
        'fetch_bore_sched_ext_source\n',
        '''fetch_bore_sched_ext_source
fetch_requested_patch_series
''',
        "requested series fetch call",
    )

    source = replace_once(
        source,
'''# Generic amd64 profile: keep the upstream platform, topology and driver
# choices instead of pruning the build for one computer model.
''',
        '''apply_requested_patch_series

# Generic amd64 profile: keep the upstream platform, topology and driver
# choices instead of pruning the build for one computer model.
''',
        "requested series apply call",
    )

    source = replace_once(
        source,
        '''# ThinLTO is mandatory for the final kernel. These symbols only survive
''',
        '''# Requested compiler and architecture optimizations.
scripts/config --disable CC_OPTIMIZE_FOR_PERFORMANCE
scripts/config --disable CC_OPTIMIZE_FOR_SIZE
scripts/config --enable CC_OPTIMIZE_FOR_PERFORMANCE_O3
# Keep the generic x86-64 Kconfig choice. The optional universal CPU patch is
# still applied for its other fixes, but it must not select one vendor/model.
scripts/config --disable MBROADWELL
scripts/config --enable GENERIC_CPU
scripts/config --enable POLLY_CLANG

# ThinLTO is mandatory for the final kernel. These symbols only survive
''',
        "requested series configuration",
    )

    source = replace_once(
        source,
        'assert_config "CONFIG_64BIT=y"\n',
        '''assert_config "CONFIG_CC_OPTIMIZE_FOR_PERFORMANCE_O3=y"
assert_config "CONFIG_POLLY_CLANG=y"
assert_disabled_or_absent CC_OPTIMIZE_FOR_PERFORMANCE
assert_disabled_or_absent CC_OPTIMIZE_FOR_SIZE
assert_config "CONFIG_GENERIC_CPU=y"
assert_disabled_or_absent MBROADWELL
assert_config "CONFIG_64BIT=y"
''',
        "requested series assertions",
    )

    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
