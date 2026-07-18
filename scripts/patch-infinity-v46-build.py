#!/usr/bin/env python3
"""Rewrite generated build assertions for Infinity v4.6-gpu CPU/RT only."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class RewriteError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RewriteError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def rewrite(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    replacements = [
        (
            "# Correct Infinity scheduler v3 patch for Linux 7.1. This is the single\n"
            "# cumulative patch from the upstream v3/stable/linux-7.1-infinity tree; it\n"
            "# includes the CPU, futex and RT hooks. No separate Infinity GPU series is used.\n",
            "# Infinity v4.6-gpu CPU/RT subset for Linux 7.1. The resolver combines only\n"
            "# upstream patches 0001-0003 from patches/arch/7.1 at the branch HEAD.\n"
            "# DRM/GPU scheduler patches 0004-0006 are deliberately excluded.\n",
            "Infinity source policy comment",
        ),
        (
            '  echo "==> Fetching the pinned correct Infinity CPU scheduler patch locally"',
            '  echo "==> Fetching build-locked Infinity v4.6-gpu CPU/RT patches 0001-0003"',
            "Infinity fetch message",
        ),
        (
            "  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' \"$INFINITY_PATCH\"",
            "  grep -Fq 'requeue_task_rt' \"$INFINITY_PATCH\"",
            "Infinity source RT marker",
        ),
        (
            "  grep -Fq 'Subject: [PATCH] infinity-scheduler v3' \"$INFINITY_PATCH\"",
            "  grep -Fq 'Subject: [PATCH 1/6] v4.5: core Infinity scheduler infrastructure' \"$INFINITY_PATCH\"\n"
            "  grep -Fq 'Subject: [PATCH 2/6] v4.5: Infinity CPU scheduling on CFS/EEVDF' \"$INFINITY_PATCH\"\n"
            "  grep -Fq 'Subject: [PATCH 3/6] v4.5: Infinity RT scheduling' \"$INFINITY_PATCH\"\n"
            "  ! grep -Fq 'Subject: [PATCH 4/6]' \"$INFINITY_PATCH\"\n"
            "  ! grep -Fq 'drivers/gpu/drm' \"$INFINITY_PATCH\"\n"
            "  ! grep -Fq 'INFINITY_GPU_' \"$INFINITY_PATCH\"",
            "Infinity mbox series validation",
        ),
        (
            '    echo "Component: Infinity scheduler v3"',
            '    echo "Component: Infinity scheduler v4.6-gpu CPU/RT subset"',
            "Infinity provenance component",
        ),
        (
            '  echo "==> Applying the correct Infinity v3 CPU/RT scheduler patch"',
            '  echo "==> Applying Infinity v4.6-gpu CPU/RT patches 0001-0003"',
            "Infinity apply message",
        ),
        (
            "  grep -Fq 'infinity_slice' kernel/sched/fair.c",
            "  grep -Fq 'infinity_update_weight' kernel/sched/fair.c",
            "Infinity fair validation",
        ),
        (
            "  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' include/uapi/linux/sched.h",
            "  grep -Fq 'INFINITY_RT_DEMOTE_THRESHOLD' kernel/sched/infinity_sched.h",
            "Infinity applied RT validation",
        ),
        (
            '  echo "==> Correct Infinity v3 CPU/RT scheduler patch applied successfully"',
            '  echo "==> Infinity v4.6-gpu CPU/RT patches applied successfully"',
            "Infinity success message",
        ),
    ]
    for old, new, label in replacements:
        text = replace_once(text, old, new, label)

    if 'INFINITY_BRANCH="v4.6-gpu"' not in text:
        raise RewriteError("dynamic resolver did not select Infinity branch v4.6-gpu")
    if "patches/turbodecky/linux-" not in text:
        raise RewriteError("combined Infinity synthetic patch path was not injected")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-infinity-v46-build.py <generated-core>")
    core = Path(sys.argv[1])
    try:
        rewrite(core)
        # Full generated build scripts contain the package/validate mode block.
        # Small unit-test fixtures intentionally exercise only Infinity rewriting;
        # module coverage has its own fail-closed unit tests.
        if 'if [[ "$MODE" == "package" ]]' in core.read_text(encoding="utf-8"):
            module_rewriter = Path(__file__).with_name("apply-validation-modules.py")
            subprocess.run([sys.executable, str(module_rewriter), str(core)], check=True)
    except RewriteError as exc:
        raise SystemExit(f"Infinity build rewrite failed: {exc}") from exc


if __name__ == "__main__":
    main()
