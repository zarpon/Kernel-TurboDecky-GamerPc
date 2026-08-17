#!/usr/bin/env python3
"""Wire the strict Linux 7.2 CPU-optimization adapter into the generated build."""
from __future__ import annotations

import sys
from pathlib import Path


OLD = r'''  if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
    report_requested_rejects "$label" "$prefix"
    return 1
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
'''

NEW = r'''  if ((status != 0)) || find "$KERNELDIR" -name '*.rej' -print -quit | grep -q .; then
    if [[ "$prefix" == "14-cpu-optimizations" ]]; then
      mapfile -t cpu_rejects < <(find "$KERNELDIR" -name '*.rej' -type f | sort)
      if ((${#cpu_rejects[@]} == 1)) && \
          [[ "${cpu_rejects[0]}" == "$KERNELDIR/arch/x86/Kconfig.cpu.rej" ]]; then
        echo "==> Applying deterministic Linux 7.2 CPU optimization Kconfig adapter"
        python3 "$ROOT/scripts/port-cpu-optimizations-7.2.py" \
          "$KERNELDIR/arch/x86/Kconfig.cpu" \
          "$KERNELDIR/arch/x86/Kconfig.cpu.rej" \
          "$KERNEL_VERSION" \
          | tee "$LOGDIR/${prefix}-semantic-port.log"
        find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
        normalize_changed_whitespace
        git diff --check | tee "$LOGDIR/${prefix}-diff-check.log"
        grep -Fq 'config GENERIC_CPU' arch/x86/Kconfig.cpu
        grep -Fq 'config X86_64_VERSION' arch/x86/Kconfig.cpu
        grep -Fq 'config MDIAMONDRAPIDS' arch/x86/Kconfig.cpu
        grep -Fq 'ifdef CONFIG_GENERIC_CPU' arch/x86/Makefile
        if grep -Fq -- '-march=native' arch/x86/Makefile && \
            ! grep -Fq 'ifdef CONFIG_X86_NATIVE_CPU' arch/x86/Makefile; then
          echo "Unexpected unconditional -march=native after CPU optimization port" >&2
          return 1
        fi
        echo "ported Linux 7.2 semantic adapter; X86_TSC upstream semantics preserved" \
          | tee "$LOGDIR/${prefix}-result.txt"
        return 0
      fi
    fi
    report_requested_rejects "$label" "$prefix"
    return 1
  fi

  find "$KERNELDIR" \( -name '*.rej' -o -name '*.orig' \) -delete
'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-cpu-optimizations-7.2-port.py <generated-core>")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(
            f"CPU optimization fallback injection: expected exactly one anchor, found {count}"
        )
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
