#!/usr/bin/env python3
"""Enable and validate CONFIG_ZEN_INTERACTIVE in the generated build."""

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
    marker = 'scripts/config --enable ZEN_INTERACTIVE\n'
    assertion = 'assert_config "CONFIG_ZEN_INTERACTIVE=y"\n'

    if marker in source and assertion in source:
        return
    if marker in source or assertion in source:
        raise SystemExit("partial Zen interactive integration detected")

    source = replace_once(
        source,
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n',
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n'
        '\n'
        '# Enable the Zen/Liquorix responsiveness policy. The post-olddefconfig\n'
        '# assertion below deliberately fails if the selected source stack no longer\n'
        '# exposes the symbol, preventing a silently ignored configuration request.\n'
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
