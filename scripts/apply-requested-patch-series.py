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
    "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/patch/?id=d70f79fef65810faf64dbae1f3a1b5623cdb2345" \
    "https://github.com/torvalds/linux/commit/d70f79fef65810faf64dbae1f3a1b5623cdb2345.patch"

  fetch_candidate_patch "Clear Linux performance patches" \
    "$REQUESTED_SERIES_DIR/09-clear.patch" "09-clear" \
    "https://raw.githubusercontent.com/Frogging-Family/linux-tkg/489513b1a3b9339d40d9e4718c7eb4e90c2e2723/linux-tkg-patches/7.1/0002-clear-patches.patch" \
    "https://raw.githubusercontent.com/Frogging-Family/linux-tkg/d837d80398a62ea884caabad36530093f9711d49/linux-tkg-patches/6.16/0002-clear-patches.patch"

  fetch_candidate_patch "fsync FUTEX_WAIT_MULTIPLE compatibility" \
    "$REQUESTED_SERIES_DIR/10-fsync-futex-waitv.patch" "10-fsync" \
    "https://raw.githubusercontent.com/Frogging-Family/linux-tkg/489513b1a3b9339d40d9e4718c7eb4e90c2e2723/linux-tkg-patches/7.1/0007-v7.1-fsync1_via_futex_waitv.patch" \
    "https://raw.githubusercontent.com/Frogging-Family/linux-tkg/d837d80398a62ea884caabad36530093f9711d49/linux-tkg-patches/6.11/0007-v6.11-fsync1_via_futex_waitv.patch"

  fetch_candidate_patch "Optimize harder O3" \
    "$REQUESTED_SERIES_DIR/11-o3.patch" "11-o3" \
    "https://raw.githubusercontent.com/Frogging-Family/linux-tkg/489513b1a3b9339d40d9e4718c7eb4e90c2e2723/linux-tkg-patches/7.1/0013-optimize_harder_O3.patch" \
    "https://raw.githubusercontent.com/Frogging-Family/linux-tkg/d837d80398a62ea884caabad36530093f9711d49/linux-tkg-patches/6.16/0013-optimize_harder_O3.patch"

  fetch_candidate_patch "Bluetooth SSP key-size check" \
    "$REQUESTED_SERIES_DIR/12-bt-ssp-key-size.patch" "12-bt-ssp" \
    "https://dev.gentoo.org/~alicef/genpatches/trunk/7.1/2000_BT-Check-key-sizes-only-if-Secure-Simple-Pairing-enabled.patch" \
    "https://dev.gentoo.org/~alicef/genpatches/trunk/6.16/2000_BT-Check-key-sizes-only-if-Secure-Simple-Pairing-enabled.patch"

  fetch_candidate_patch "libbpf Wmaybe-uninitialized workaround" \
    "$REQUESTED_SERIES_DIR/13-libbpf-uninitialized.patch" "13-libbpf-uninitialized" \
    "https://dev.gentoo.org/~alicef/genpatches/trunk/7.1/2990_libbpf-v2-workaround-Wmaybe-uninitialized-false-pos.patch" \
    "https://dev.gentoo.org/~alicef/genpatches/trunk/6.16/2990_libbpf-v2-workaround-Wmaybe-uninitialized-false-pos.patch"

  fetch_candidate_patch "Universal x86 CPU optimizations" \
    "$REQUESTED_SERIES_DIR/14-cpu-optimizations.patch" "14-cpu-optimizations" \
    "https://dev.gentoo.org/~alicef/genpatches/trunk/7.1/5010_enable-cpu-optimizations-universal.patch" \
    "https://dev.gentoo.org/~alicef/genpatches/trunk/6.16/5010_enable-cpu-optimizations-universal.patch"

  fetch_candidate_patch "Clang DKMS compatibility" \
    "$REQUESTED_SERIES_DIR/15-dkms-clang.patch" "15-dkms-clang" \
    "https://raw.githubusercontent.com/CachyOS/kernel-patches/refs/heads/master/7.1/misc/dkms-clang.patch" \
    "https://raw.githubusercontent.com/CachyOS/kernel-patches/refs/heads/master/6.16/misc/dkms-clang.patch"

  fetch_candidate_patch "Clang Polly support" \
    "$REQUESTED_SERIES_DIR/16-clang-polly.patch" "16-clang-polly" \
    "https://raw.githubusercontent.com/CachyOS/kernel-patches/refs/heads/master/7.1/misc/0001-clang-polly.patch" \
    "https://raw.githubusercontent.com/CachyOS/kernel-patches/refs/heads/master/6.16/misc/0001-clang-polly.patch"

  fetch_candidate_patch "Always print firmware file name" \
    "$REQUESTED_SERIES_DIR/17-firmware-name.patch" "17-firmware-name" \
    "https://732852.bugs.gentoo.org/attachment.cgi?id=649432"

  fetch_candidate_patch "mac80211 minstrel fraction fix" \
    "$REQUESTED_SERIES_DIR/18-minstrel-frac.patch" "18-minstrel-frac" \
    "https://git.openwrt.org/openwrt/openwrt/plain/package/kernel/mac80211/patches/subsys/302-mac80211-minstrel_ht-fix-MINSTREL_FRAC-macro.patch?id=0ff1553bd731c0db28043fc9caab90bdc32587f3"

  fetch_candidate_patch "mac80211 minstrel fluctuation reduction" \
    "$REQUESTED_SERIES_DIR/19-minstrel-fluctuation.patch" "19-minstrel-fluctuation" \
    "https://git.openwrt.org/openwrt/openwrt/plain/package/kernel/mac80211/patches/subsys/303-mac80211-minstrel_ht-reduce-fluctuations-in-rate-pro.patch?id=0ff1553bd731c0db28043fc9caab90bdc32587f3"

  fetch_candidate_patch "mac80211 minstrel rate downgrade rework" \
    "$REQUESTED_SERIES_DIR/20-minstrel-downgrade.patch" "20-minstrel-downgrade" \
    "https://git.openwrt.org/openwrt/openwrt/plain/package/kernel/mac80211/patches/subsys/304-mac80211-minstrel_ht-rework-rate-downgrade-code-and-.patch?id=0ff1553bd731c0db28043fc9caab90bdc32587f3"

  fetch_candidate_patch "ath11k remapped CE 64-bit fix" \
    "$REQUESTED_SERIES_DIR/21-ath11k-remapped-ce.patch" "21-ath11k-remapped-ce" \
    "https://git.openwrt.org/openwrt/openwrt/plain/package/kernel/mac80211/patches/ath11k/910-ath11k-fix-remapped-ce-accessing-issue-on-64bit-OS.patch?id=0ff1553bd731c0db28043fc9caab90bdc32587f3"
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
        'download "$LIQUORIX_CONFIG_URL" "$WORKDIR/liquorix-amd64.config"\n',
        '''download "$LIQUORIX_CONFIG_URL" "$WORKDIR/liquorix-amd64.config"
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
