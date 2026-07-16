#!/usr/bin/env python3
"""Make requested patch lookup follow the dynamically resolved stable series."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-latest-stable-series.py <generated-core-script>")

    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")

    replacements = {
        "linux-tkg-patches/7.1/": "linux-tkg-patches/${KERNEL_SERIES}/",
        "0007-v7.1-fsync1_via_futex_waitv.patch": "0007-v${KERNEL_SERIES}-fsync1_via_futex_waitv.patch",
        "genpatches/trunk/7.1/": "genpatches/trunk/${KERNEL_SERIES}/",
        "kernel-patches/refs/heads/master/7.1/": "kernel-patches/refs/heads/master/${KERNEL_SERIES}/",
        "Compatibility policy: Linux 7.1-specific or upstream-integrated source preferred":
            "Compatibility policy: Linux $KERNEL_SERIES-specific or upstream-integrated source preferred",
        "Compatibility policy: no usable Linux 7.1-specific source found; controlled port source selected":
            "Compatibility policy: no usable Linux $KERNEL_SERIES-specific source found; controlled port source selected",
        "Resolving requested patch series, preferring Linux 7.1 revisions":
            "Resolving requested patch series, preferring Linux $KERNEL_SERIES revisions",
        "already integrated in Linux 7.1.3 or an earlier patch":
            "already integrated in Linux $KERNEL_VERSION or an earlier patch",
        "if curl --fail --location --retry 3 --retry-all-errors --retry-delay 2 \\\n":
            "if curl --user-agent 'TurboDecky-GamerPc-CI/1.0 (+https://github.com/zarpon/Kernel-TurboDecky-GamerPc)' --fail --location \\\n        --retry 3 --retry-all-errors --retry-delay 2 \\\n",
    }

    for old, new in replacements.items():
        if old not in source:
            raise SystemExit(f"latest-stable patch-series anchor missing: {old!r}")
        source = source.replace(old, new)

    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
