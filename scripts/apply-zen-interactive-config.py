#!/usr/bin/env python3
"""Port, enable and validate CONFIG_ZEN_INTERACTIVE in the generated build."""

from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected exactly one anchor, found {count}: {old[:120]!r}"
        )
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: apply-zen-interactive-config.py <build-kernelnote-core.sh>"
        )

    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    port_marker = 'apply-zen-interactive-source.py" "$KERNELDIR"\n'
    config_marker = 'scripts/config --enable ZEN_INTERACTIVE\n'
    assertion = 'assert_config "CONFIG_ZEN_INTERACTIVE=y"\n'
    present = tuple(marker in source for marker in (port_marker, config_marker, assertion))

    if all(present):
        return
    if any(present):
        raise SystemExit("partial Zen interactive integration detected")

    source = replace_once(
        source,
        "apply_requested_patch_series\n",
        "apply_requested_patch_series\n"
        "\n"
        "# Port the non-conflicting Zen 7.1.4 interactive defaults only after all\n"
        "# scheduler and memory patches are in place. The helper is fail-closed and\n"
        "# rejects upstream layout changes rather than applying fuzzy edits.\n"
        'python3 "$ROOT/scripts/apply-zen-interactive-source.py" "$KERNELDIR"\n'
        "grep -Fq 'config ZEN_INTERACTIVE' init/Kconfig\n",
        "Zen interactive source port",
    )
    source = replace_once(
        source,
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n',
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n'
        '\n'
        '# Enable the reviewed Zen responsiveness policy. The post-olddefconfig\n'
        '# assertion below fails if the source port no longer exposes the symbol.\n'
        'scripts/config --enable ZEN_INTERACTIVE\n',
        "Zen interactive configuration",
    )
    source = replace_once(
        source,
        'assert_config "CONFIG_SCHED_BORE=y"\n',
        'assert_config "CONFIG_SCHED_BORE=y"\n'
        'assert_config "CONFIG_ZEN_INTERACTIVE=y"\n',
        "Zen interactive assertion",
    )
    path.write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
