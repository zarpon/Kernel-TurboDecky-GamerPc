#!/usr/bin/env python3
"""Rewrite generated build assertions for the complete Infinity v4.6-gpu series."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
class RewriteError(RuntimeError): pass

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RewriteError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)

def rewrite(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    replacements = [
      ("# Correct Infinity scheduler v3 patch for Linux 7.1. This is the single\n# cumulative patch from the upstream v3/stable/linux-7.1-infinity tree; it\n# includes the CPU, futex and RT hooks. No separate Infinity GPU series is used.\n",
       "# Complete Infinity v4.6-gpu series for Linux 7.1. The resolver combines\n# upstream patches 0001-0006: CPU/EEVDF, RT and DRM/GPU virtual-time scheduling.\n", "policy comment"),
      ('  echo "==> Fetching the pinned correct Infinity CPU scheduler patch locally"', '  echo "==> Fetching build-locked Infinity v4.6-gpu patches 0001-0006"', "fetch"),
      ("  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' \"$INFINITY_PATCH\"", "  grep -Fq 'requeue_task_rt' \"$INFINITY_PATCH\"", "rt marker"),
      ("  grep -Fq 'Subject: [PATCH] infinity-scheduler v3' \"$INFINITY_PATCH\"",
       "  for n in 1 2 3 4 5 6; do grep -Fq \"Subject: [PATCH $n/6]\" \"$INFINITY_PATCH\"; done\n  grep -Fq 'drm_sched_entity_calc_vtime' \"$INFINITY_PATCH\"\n  grep -Fq 'drm_sched_rq_select_entity_infinity' \"$INFINITY_PATCH\"\n  grep -Fq 'INFINITY_GPU_EMA_CLIMB_NS' \"$INFINITY_PATCH\"", "series validation"),
      ('    echo "Component: Infinity scheduler v3"', '    echo "Component: Infinity scheduler v4.6-gpu full CPU/RT/DRM/GPU series"', "provenance"),
      ('  echo "==> Applying the correct Infinity v3 CPU/RT scheduler patch"', '  echo "==> Applying Infinity v4.6-gpu patches 0001-0006"', "apply"),
      ("  grep -Fq 'infinity_slice' kernel/sched/fair.c", "  grep -Fq 'infinity_update_weight' kernel/sched/fair.c", "fair"),
      ("  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' include/uapi/linux/sched.h", "  grep -Fq 'INFINITY_RT_DEMOTE_THRESHOLD' kernel/sched/infinity_sched.h\n  grep -Fq 'cached_gpu_vtime' include/drm/gpu_scheduler.h\n  grep -Fq 'drm_sched_rq_select_entity_infinity' drivers/gpu/drm/scheduler/sched_main.c", "applied markers"),
      ('  echo "==> Correct Infinity v3 CPU/RT scheduler patch applied successfully"', '  echo "==> Infinity v4.6-gpu full series applied successfully"', "success"),
    ]
    for old,new,label in replacements: text=replace_once(text,old,new,label)
    if 'INFINITY_BRANCH="v4.6-gpu"' not in text: raise RewriteError("v4.6-gpu branch not selected")
    if "patches/turbodecky/linux-" not in text: raise RewriteError("synthetic patch path not injected")
    path.write_text(text, encoding="utf-8")

def main():
    if len(sys.argv)!=2: raise SystemExit("usage: patch-infinity-v46-build.py <generated-core>")
    core=Path(sys.argv[1])
    try:
        rewrite(core)
        if 'if [[ "$MODE" == "package" ]]' in core.read_text(encoding="utf-8"):
            subprocess.run([sys.executable, str(Path(__file__).with_name("apply-validation-modules.py")), str(core)], check=True)
    except RewriteError as exc: raise SystemExit(f"Infinity build rewrite failed: {exc}") from exc
if __name__=="__main__": main()
