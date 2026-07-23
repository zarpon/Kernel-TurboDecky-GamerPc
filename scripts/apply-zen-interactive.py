#!/usr/bin/env python3
"""Enable and verify CONFIG_ZEN_INTERACTIVE in the generated kernel build."""
from __future__ import annotations

import argparse
from pathlib import Path


class RewriteError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RewriteError(f"expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def rewrite(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    config_old = (
        'scripts/config --enable SCHED_BORE\n'
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n'
    )
    config_new = (
        'scripts/config --enable SCHED_BORE\n'
        'scripts/config --set-val MIN_BASE_SLICE_NS 2000000\n'
        'scripts/config --enable ZEN_INTERACTIVE\n'
    )
    if config_new not in text:
        text = replace_once(text, config_old, config_new, "Zen config")

    assert_old = 'assert_config "CONFIG_SCHED_BORE=y"\n'
    assert_new = (
        'assert_config "CONFIG_SCHED_BORE=y"\n'
        'assert_config "CONFIG_ZEN_INTERACTIVE=y"\n'
    )
    if assert_new not in text:
        text = replace_once(text, assert_old, assert_new, "Zen assertion")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_core", type=Path)
    args = parser.parse_args()
    try:
        rewrite(args.build_core)
    except RewriteError as exc:
        raise SystemExit(f"Zen interactive rewrite failed: {exc}") from exc


if __name__ == "__main__":
    main()
