#!/usr/bin/env python3
"""Configure native upstream DMEM support and retain its userspace package."""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "# TurboDecky VRAM/DMEM integration"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply-vram-cgroup.py <build-kernelnote.sh>")

    path = Path(sys.argv[1])
    wrapper = path.read_text(encoding="utf-8")
    if MARKER in wrapper:
        print("VRAM/DMEM build integration already present")
        return

    injection = r"""
# TurboDecky VRAM/DMEM integration
replace_once(
    'scripts/config --enable LRU_MARIE\n',
    '''scripts/config --enable CGROUPS
scripts/config --enable CGROUP_DMEM
scripts/config --enable LRU_MARIE
'''
)

replace_once(
    'assert_config "CONFIG_LRU_MARIE=y"\n',
    '''assert_config "CONFIG_CGROUP_DMEM=y"
assert_config "CONFIG_LRU_MARIE=y"
'''
)

replace_once(
    'if [[ "$MODE" == "package" ]]; then\n',
    '''bash "$ROOT/scripts/build-vram-package.sh" "$MODE"

if [[ "$MODE" == "package" ]]; then
'''
)
"""

    anchor = 'output.write_text(source, encoding="utf-8")\n'
    wrapper = replace_once(wrapper, anchor, injection + "\n" + anchor, "VRAM wrapper injection")
    path.write_text(wrapper, encoding="utf-8")
    print("Configured native upstream DMEM and userspace integration")


if __name__ == "__main__":
    main()
