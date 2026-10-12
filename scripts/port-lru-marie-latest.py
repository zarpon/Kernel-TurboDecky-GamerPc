#!/usr/bin/env python3
"""Adapt the locked latest LRU Marie patch to the selected Linux source.

The upstream Linux 7.3-rc1 patch adds lru_marie.h beside buffer_head.h.
Linux 7.3-rc7 inserted kvm_types.h in that same include block. Rewrite only
that exact hunk, and fail closed for every unknown source or patch shape.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


UPSTREAM_HUNK = (
    "@@ -33,6 +33,7 @@\n"
    " #include <linux/page_idle.h>\n"
    " #include <linux/local_lock.h>\n"
    " #include <linux/buffer_head.h>\n"
    "+#include <linux/lru_marie.h>\n"
    " \n"
    ' #include "internal.h"\n'
    ' #include "page_alloc.h"\n'
)

PORTED_HUNK = (
    "@@ -33,7 +33,8 @@\n"
    " #include <linux/page_idle.h>\n"
    " #include <linux/local_lock.h>\n"
    " #include <linux/buffer_head.h>\n"
    " #include <linux/kvm_types.h>\n"
    "+#include <linux/lru_marie.h>\n"
    " \n"
    ' #include "internal.h"\n'
    ' #include "page_alloc.h"\n'
)

UPSTREAM_CONTEXT = """#include <linux/page_idle.h>
#include <linux/local_lock.h>
#include <linux/buffer_head.h>

#include "internal.h"
#include "page_alloc.h"
"""

PORTED_CONTEXT = """#include <linux/page_idle.h>
#include <linux/local_lock.h>
#include <linux/buffer_head.h>
#include <linux/kvm_types.h>

#include "internal.h"
#include "page_alloc.h"
"""


class PortError(RuntimeError):
    pass


def adapt(patch_path: Path, folio_path: Path) -> str:
    patch = patch_path.read_text(encoding="utf-8")
    folio = folio_path.read_text(encoding="utf-8")

    if patch.count(PORTED_HUNK) == 1 and UPSTREAM_HUNK not in patch:
        return "already-ported"

    count = patch.count(UPSTREAM_HUNK)
    if count != 1:
        raise PortError(
            "expected exactly one reviewed LRU Marie mm/folio.c include hunk; "
            f"found {count}"
        )

    if PORTED_CONTEXT in folio:
        patch_path.write_text(
            patch.replace(UPSTREAM_HUNK, PORTED_HUNK, 1), encoding="utf-8"
        )
        return "ported-linux-7.3-kvm-types-context"

    if UPSTREAM_CONTEXT in folio:
        return "upstream-hunk-compatible"

    raise PortError(
        "Linux mm/folio.c include context is neither the reviewed 7.3-rc1 "
        "shape nor the reviewed 7.3-rc7 kvm_types.h shape"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("patch", type=Path)
    parser.add_argument("folio", type=Path)
    args = parser.parse_args()
    try:
        result = adapt(args.patch, args.folio)
    except (OSError, UnicodeError, PortError) as exc:
        print(f"LRU Marie port error: {exc}", file=sys.stderr)
        return 2
    print(f"LRU Marie compatibility adapter: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
