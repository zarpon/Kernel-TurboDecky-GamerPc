#!/usr/bin/env python3
"""Finalize generated validation/build integrations before kernel execution."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def patch_validation(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    matched = None
    for lto_mode in ("Full LTO", "ThinLTO"):
        candidate = f'''else
  echo "==> Validating built-in kernel and Clang {lto_mode} link with $JOBS parallel jobs"
  "${{MAKE[@]}}" -j"$JOBS" bzImage
  test -s arch/x86/boot/bzImage
  test -s vmlinux
  file arch/x86/boot/bzImage vmlinux | tee "$LOGDIR/build-products.txt"
fi
'''
        if candidate in source:
            if matched is not None:
                raise SystemExit("loadable module validation: multiple build-mode anchors found")
            matched = (lto_mode, candidate)

    if matched is None:
        raise SystemExit(
            "loadable module validation: expected exactly one anchor "
            "(Full LTO or ThinLTO build), found 0"
        )

    lto_mode, old = matched
    new = f'''else
  echo "==> Validating built-in kernel and Clang {lto_mode} link with $JOBS parallel jobs"
  "${{MAKE[@]}}" -j"$JOBS" bzImage
  test -s arch/x86/boot/bzImage
  test -s vmlinux
  file arch/x86/boot/bzImage vmlinux | tee "$LOGDIR/build-products.txt"

  echo "==> Validating every configured loadable module"
  "${{MAKE[@]}}" -j"$JOBS" modules 2>&1 | tee "$LOGDIR/modules-build.log"
  module_products=(
    drivers/block/zram/zram.ko
    drivers/gpu/drm/ttm/ttm.ko
    drivers/gpu/drm/amd/amdgpu/amdgpu.ko
    net/mac80211/mac80211.ko
    drivers/net/wireless/ath/ath11k/ath11k.ko
    drivers/net/wireless/ath/ath11k/ath11k_ahb.ko
    drivers/net/wireless/ath/ath11k/ath11k_pci.ko
  )
  for module in "${{module_products[@]}}"; do
    test -s "$module"
  done
  file "${{module_products[@]}}" | tee "$LOGDIR/modules-products.txt"
  find . -type f \\( -name '*.rej' -o -name '*.orig' \\) -print -quit | grep -q . && {{
    echo "Patch reject/original files remain after module validation" >&2
    exit 1
  }}
fi
'''
    if source.count(old) != 1:
        raise SystemExit(f"loadable module validation: expected exactly one anchor for {lto_mode} build")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def patch_cpu_optimization_fallback(path: Path) -> None:
    helper = Path(__file__).with_name("apply-cpu-optimizations-7.2-port.py")
    subprocess.run([sys.executable, str(helper), str(path)], check=True)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-validation-modules.py <generated-core>")
    path = Path(sys.argv[1])
    patch_validation(path)
    patch_cpu_optimization_fallback(path)


if __name__ == "__main__":
    main()
