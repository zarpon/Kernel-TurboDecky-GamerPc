#!/usr/bin/env python3
"""Finalize BORE using the exact dynamically locked upstream patch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / ".resolved-patches/patch-lock.json"


class FinalizeError(RuntimeError):
    pass


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    compiled = re.compile(pattern, re.MULTILINE)
    matches = list(compiled.finditer(text))
    if len(matches) != 1:
        raise FinalizeError(f"{label}: expected one match, found {len(matches)}")
    return compiled.sub(lambda _match: replacement, text, count=1)


def load_locked_bore(lock_path: Path, kernel_version: str) -> tuple[dict[str, Any], Path]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        record = lock["components"]["bore"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"unable to read the BORE patch lock: {lock_path}") from exc

    locked_kernel = str(lock.get("kernel", {}).get("version", ""))
    if locked_kernel != kernel_version:
        raise FinalizeError(
            f"BORE lock kernel mismatch: {locked_kernel!r} != {kernel_version!r}"
        )
    if record.get("selection") != "exact":
        raise FinalizeError(
            "the latest stable kernel has no exact BORE source; "
            "refuse to reuse an older reviewed port"
        )
    if str(record.get("kernel_target", "")) != kernel_version:
        raise FinalizeError(
            f"BORE target mismatch: {record.get('kernel_target')!r} != {kernel_version!r}"
        )

    version = str(record.get("project_version", ""))
    sha256 = str(record.get("sha256", ""))
    output = str(record.get("output", ""))
    if not version:
        raise FinalizeError("locked BORE project version is missing")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise FinalizeError("locked BORE SHA-256 is invalid")
    if not output:
        raise FinalizeError("locked BORE output path is missing")

    resolved_root = lock_path.parent.resolve()
    patch_path = (lock_path.parent / output).resolve()
    if resolved_root not in patch_path.parents:
        raise FinalizeError(f"locked BORE output escapes the resolver root: {output}")
    if not patch_path.is_file() or patch_path.stat().st_size <= 0:
        raise FinalizeError(f"locked BORE patch is missing: {patch_path}")

    data = patch_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FinalizeError("locked BORE patch SHA-256 no longer matches the lock")
    if len(data) != int(record.get("size", -1)):
        raise FinalizeError("locked BORE patch size no longer matches the lock")

    text = data.decode("utf-8")
    required = (
        f"Subject: [PATCH] linux{kernel_version}-bore-{version}",
        "SCHED_BORE_VERSION",
        f'"{version}"',
        "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c",
        "sched_bore",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise FinalizeError(f"locked BORE patch is missing markers: {missing}")

    return record, patch_path


def rewrite_core(path: Path, record: dict[str, Any], kernel_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    version = str(record["project_version"])
    sha256 = str(record["sha256"])
    output = str(record["output"])

    text = replace_regex_once(
        text,
        r'^BORE_PATCH=.*$',
        f'BORE_PATCH="$RESOLVED_PATCH_ROOT/{output}"',
        "BORE patch assignment",
    )
    text = replace_regex_once(
        text,
        r'^BORE_PORT_VERSION=.*$',
        f'BORE_PORT_VERSION="{version}"',
        "BORE version assignment",
    )
    text = replace_regex_once(
        text,
        r'^BORE_PORT_UPSTREAM_SHA256=.*$',
        f'BORE_PORT_UPSTREAM_SHA256="{sha256}"',
        "BORE SHA assignment",
    )
    text = replace_regex_once(
        text,
        r'^\s*grep -Fq \'SCHED_BORE_VERSION  "[^"]+"\' "\$BORE_UPSTREAM_PATCH"$',
        '  grep -Fq "SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"" "$BORE_UPSTREAM_PATCH"',
        "BORE upstream version assertion",
    )
    text = replace_regex_once(
        text,
        r'^\s*grep -Fq \'sched: port BORE [^\']+ to Linux [^\']+\' "\$BORE_PATCH"$',
        '  grep -Fq "Subject: [PATCH] linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}" "$BORE_PATCH"',
        "BORE subject assertion",
    )
    text = replace_regex_once(
        text,
        r'Applying the reviewed BORE [^"\n]+ Linux [0-9.]+ port',
        'Applying upstream BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION',
        "BORE apply label",
    )
    text = replace_regex_once(
        text,
        r'report_bore_rejects "BORE [0-9][^"]* for Linux [0-9.]+"',
        'report_bore_rejects "BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION"',
        "BORE reject label",
    )
    text = replace_regex_once(
        text,
        r'^\s*git diff --check \| tee "\$LOGDIR/01-bore-diff-check\.log"$',
        '''  if ! git diff --check > "$LOGDIR/01-bore-diff-check.log" 2>&1; then
    cat "$LOGDIR/01-bore-diff-check.log"
    echo "==> Normalizing whitespace introduced by BORE patch"
    normalize_changed_whitespace
    git diff --check | tee "$LOGDIR/01-bore-diff-check-after-fix.log"
  fi''',
        "BORE whitespace validation",
    )
    text = replace_regex_once(
        text,
        r'^\s*grep -Fq \'SCHED_BORE_VERSION\' kernel/sched/bore\.c$',
        '  grep -Fq "SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"" include/linux/sched/bore.h',
        "BORE installed version assertion",
    )
    text = replace_regex_once(
        text,
        r'BORE [^"\n]+ Linux port applied successfully',
        'BORE $BORE_PORT_VERSION Linux port applied successfully',
        "BORE success label",
    )

    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: finalize-bore-stable-port.py <generated-core-script>")
    kernel_version = os.environ.get("KERNEL_VERSION")
    if not kernel_version:
        raise SystemExit("KERNEL_VERSION must be resolved before finalizing BORE")

    record, patch_path = load_locked_bore(LOCK_PATH, kernel_version)
    core = Path(sys.argv[1])
    rewrite_core(core, record, kernel_version)

    for legacy in (ROOT / "patches/bore").glob(".resolved-*-bore-*.patch"):
        legacy.unlink(missing_ok=True)

    print(
        f"Finalized exact upstream BORE {record['project_version']} for Linux "
        f"{kernel_version}: {patch_path.relative_to(ROOT)}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except FinalizeError as exc:
        raise SystemExit(f"BORE finalization failed: {exc}") from exc
