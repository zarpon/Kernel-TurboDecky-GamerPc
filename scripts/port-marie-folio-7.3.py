#!/usr/bin/env python3
"""Port the exact newest upstream Marie 7.3 r2 include/localversion hunks.

All other upstream hunks are preserved byte-for-byte. Fail closed on drift.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SUBJECT = 'Subject: [PATCH] linux7.3-rc1-lru_marie-0.12.0r2\n'
ORIGINAL_INCLUDE = '''@@ -33,6 +33,7 @@
 #include <linux/page_idle.h>
 #include <linux/local_lock.h>
 #include <linux/buffer_head.h>
+#include <linux/lru_marie.h>
 
 #include "internal.h"
 #include "page_alloc.h"
'''
PORTED_INCLUDE = '''@@ -33,7 +33,8 @@
 #include <linux/page_idle.h>
 #include <linux/local_lock.h>
 #include <linux/buffer_head.h>
 #include <linux/kvm_types.h>
+#include <linux/lru_marie.h>
 
 #include "internal.h"
 #include "page_alloc.h"
'''
TARGET_INCLUDE = '''#include <linux/page_idle.h>
#include <linux/local_lock.h>
#include <linux/buffer_head.h>
#include <linux/kvm_types.h>

#include "internal.h"
#include "page_alloc.h"
'''
ORIGINAL_LOCALVERSION = r'''diff --git a/localversion b/localversion
deleted file mode 100644
index 456553120f..0000000000
--- a/localversion
+++ /dev/null
@@ -1 +0,0 @@
--marie
\ No newline at end of file
'''


class PortError(RuntimeError):
    pass


def port(upstream: str, tree: Path, version: str) -> str:
    if not re.fullmatch(r'7\.3(?:-rc\d+|\.\d+)?', version):
        raise PortError(f'unreviewed kernel version: {version}')
    # An earlier, separately reviewed adapter may already have carried the
    # Linux 7.3 kvm_types.h include into this same upstream patch. Accept
    # exactly one original OR one already-ported hunk, never two or neither.
    original = upstream.count(ORIGINAL_INCLUDE)
    preported = upstream.count(PORTED_INCLUDE)
    if upstream.count(SUBJECT) != 1 or original + preported != 1:
        raise PortError('upstream Marie revision or folio include hunk drifted')
    if upstream.count(ORIGINAL_LOCALVERSION) != 1:
        raise PortError('upstream localversion deletion hunk drifted')
    folio = (tree / 'mm/folio.c').read_text(encoding='utf-8')
    if folio.count(TARGET_INCLUDE) != 1 or '#include <linux/lru_marie.h>' in folio:
        raise PortError('target folio includes differ from reviewed Linux 7.3 layout')
    patched = upstream.replace(ORIGINAL_INCLUDE, PORTED_INCLUDE, 1) if original else upstream
    if (tree / 'localversion').exists():
        content = (tree / 'localversion').read_text(encoding='utf-8')
        if content != '-marie':
            raise PortError('localversion present with unreviewed contents')
    else:
        # The target tree has no file; the upstream deletion is satisfied.
        patched = patched.replace(ORIGINAL_LOCALVERSION, '', 1)
    return patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('upstream_patch', type=Path)
    parser.add_argument('output_patch', type=Path)
    parser.add_argument('kernel_tree', type=Path)
    parser.add_argument('kernel_version')
    args = parser.parse_args()
    original = args.upstream_patch.read_text(encoding='utf-8')
    args.output_patch.write_text(
        port(original, args.kernel_tree, args.kernel_version), encoding='utf-8'
    )
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, PortError) as exc:
        print(f'Marie 7.3 port refused: {exc}', file=sys.stderr)
        raise SystemExit(2)
