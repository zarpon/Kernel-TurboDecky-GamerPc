#!/usr/bin/env python3
"""Make PR validation compile every configured loadable kernel module."""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_validation(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    old = '''else
  echo "==> Validating built-in kernel and Clang ThinLTO link with $JOBS parallel jobs"
  "${MAKE[@]}" -j"$JOBS" bzImage
  test -s arch/x86/boot/bzImage
  test -s vmlinux
  file arch/x86/boot/bzImage vmlinux | tee "$LOGDIR/build-products.txt"
fi
'''
    new = '''else
  echo "==> Validating built-in kernel and Clang ThinLTO link with $JOBS parallel jobs"
  "${MAKE[@]}" -j"$JOBS" bzImage
  test -s arch/x86/boot/bzImage
  test -s vmlinux
  file arch/x86/boot/bzImage vmlinux | tee "$LOGDIR/build-products.txt"

  echo "==> Validating every configured loadable module"
  "${MAKE[@]}" -j"$JOBS" modules 2>&1 | tee "$LOGDIR/modules-build.log"
  module_products=(
    drivers/block/zram/zram.ko
    drivers/gpu/drm/ttm/ttm.ko
    drivers/gpu/drm/amd/amdgpu/amdgpu.ko
    net/mac80211/mac80211.ko
    drivers/net/wireless/ath/ath11k/ath11k.ko
    drivers/net/wireless/ath/ath11k/ath11k_ahb.ko
    drivers/net/wireless/ath/ath11k/ath11k_pci.ko
  )
  for module in "${module_products[@]}"; do
    test -s "$module"
  done
  file "${module_products[@]}" | tee "$LOGDIR/modules-products.txt"
  find . -type f \\( -name '*.rej' -o -name '*.orig' \\) -print -quit | grep -q . && {
    echo "Patch reject/original files remain after module validation" >&2
    exit 1
  }
fi
'''
    source = replace_once(source, old, new, "loadable module validation")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-validation-modules.py <generated-core>")
    patch_validation(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
