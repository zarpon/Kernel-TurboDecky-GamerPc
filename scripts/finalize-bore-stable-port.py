#!/usr/bin/env python3
"""Reassert the reviewed BORE port after all dynamic source rewrites."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_STABLE = Path(__file__).with_name("apply-latest-stable-series.py")
SPEC = importlib.util.spec_from_file_location("latest_stable_series", LATEST_STABLE)
if SPEC is None or SPEC.loader is None:
    raise SystemExit(f"unable to load stable-series rewriter from {LATEST_STABLE}")
stable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stable)


class FinalizeError(RuntimeError):
    pass


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    compiled = re.compile(pattern, re.MULTILINE)
    matches = list(compiled.finditer(text))
    if len(matches) != 1:
        raise FinalizeError(f"{label}: expected one match, found {len(matches)}")
    return compiled.sub(replacement, text, count=1)


def validate_port(path: Path, kernel_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    subject = f"Subject: [PATCH] sched: port BORE {stable.BORE_VERSION} to Linux {kernel_version}"
    if subject not in text:
        raise FinalizeError(f"resolved BORE port has the wrong subject: {path}")
    if "restart_burst_bore(p);" not in text:
        raise FinalizeError("resolved BORE port lost the burst restart hook")
    if kernel_version == "7.1.5":
        match = re.search(
            r"^@@[^\n]*@@ static bool dequeue_task_fair\([^\n]+\)\n(.*?)(?=^@@ |^diff --git )",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is None:
            raise FinalizeError("Linux 7.1.5 dequeue_task_fair port hunk is missing")
        hunk = match.group(1)
        if "util_est_update(" in hunk:
            raise FinalizeError("Linux 7.1.5 port still references removed util_est_update()")
        if "if (dequeue_entities(rq, &p->se, flags) < 0)" not in hunk:
            raise FinalizeError("Linux 7.1.5 port lost the dequeue_entities boundary")


def rewrite_core(path: Path, port: Path, kernel_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    relative = port.relative_to(ROOT).as_posix()
    text = replace_regex_once(
        text,
        r'^BORE_PATCH=.*$',
        f'BORE_PATCH="$ROOT/{relative}"',
        "BORE patch assignment",
    )
    text = replace_regex_once(
        text,
        r"grep -Fq 'sched: port BORE 6\.8\.0-rc1 to Linux [^']+' \"\$BORE_PATCH\"",
        f"grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux {kernel_version}' \"$BORE_PATCH\"",
        "BORE subject assertion",
    )
    text = replace_regex_once(
        text,
        r"Applying the reviewed BORE 6\.8\.0-rc1 Linux [0-9.]+ port",
        f"Applying the reviewed BORE 6.8.0-rc1 Linux {kernel_version} port",
        "BORE apply label",
    )
    text = replace_regex_once(
        text,
        r"BORE 6\.8\.0-rc1 for Linux [0-9.]+",
        f"BORE 6.8.0-rc1 for Linux {kernel_version}",
        "BORE reject label",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: finalize-bore-stable-port.py <generated-core-script>")
    kernel_version = os.environ.get("KERNEL_VERSION")
    if not kernel_version:
        raise SystemExit("KERNEL_VERSION must be resolved before finalizing BORE")
    port = stable.materialize_bore_port(kernel_version)
    validate_port(port, kernel_version)
    core = Path(sys.argv[1])
    rewrite_core(core, port, kernel_version)
    print(
        f"Finalized BORE {stable.BORE_VERSION} port for Linux {kernel_version}: "
        f"{port.relative_to(ROOT)}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except FinalizeError as exc:
        raise SystemExit(f"BORE stable-port finalization failed: {exc}") from exc
