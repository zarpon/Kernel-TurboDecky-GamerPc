#!/usr/bin/env python3
"""Set the Linux Crypto API ZSTD default to level 1, without modifying ZRAM."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFINITION = re.compile(
    r"^(?P<prefix>#define[ \t]+ZSTD_DEF_LEVEL[ \t]+)(?P<value>[^\s]+)(?P<suffix>[ \t]*)$",
    re.MULTILINE,
)


def set_default(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    matches = list(DEFINITION.finditer(source))
    if len(matches) != 1:
        raise ValueError(
            f"{path}: expected exactly one ZSTD_DEF_LEVEL definition, found {len(matches)}"
        )
    match = matches[0]
    if match.group("value") != "3":
        raise ValueError(
            f"{path}: upstream ZSTD_DEF_LEVEL changed from expected 3 "
            f"to {match.group('value')}; refusing an unreviewed override"
        )
    updated = source[: match.start("value")] + "1" + source[match.end("value") :]
    path.write_text(updated, encoding="utf-8")
    print(f"Linux Crypto API ZSTD default: 3 -> 1 ({path})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="path to Linux crypto/zstd.c")
    args = parser.parse_args()
    if args.source.as_posix().split("/")[-2:] != ["crypto", "zstd.c"]:
        parser.error("expected the kernel source file crypto/zstd.c")
    set_default(args.source)


if __name__ == "__main__":
    main()
