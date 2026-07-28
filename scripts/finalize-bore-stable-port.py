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
SCHED_EXT_PORT_TEMPLATE = ROOT / "patches/bore/7.1.4-sched-ext-coexistence-fix.patch"


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

    if not isinstance(record, dict) or record.get("kind") != "git_patch":
        raise FinalizeError("locked BORE source is not a Git patch record")
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
    size = record.get("size")
    if not isinstance(size, int) or size <= 0:
        raise FinalizeError("locked BORE size is invalid")

    resolved_root = lock_path.parent.resolve()
    patch_path = (lock_path.parent / output).resolve()
    if resolved_root not in patch_path.parents:
        raise FinalizeError(f"locked BORE output escapes the resolver root: {output}")
    if not patch_path.is_file() or patch_path.stat().st_size <= 0:
        raise FinalizeError(f"locked BORE patch is missing: {patch_path}")

    data = patch_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FinalizeError("locked BORE patch SHA-256 no longer matches the lock")
    if len(data) != size:
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


def load_locked_sched_ext(
    lock_path: Path, kernel_version: str
) -> tuple[dict[str, Any], Path]:
    """Load and authenticate the exact sched_ext coexistence source from the lock.

    The sched_ext fix still needs a small Linux 7.1 context port because its
    original hunk targets an older scheduler file. Its upstream bytes must
    nevertheless be dynamic: the generated build verifies them against this
    lock instead of a SHA embedded in the repository.
    """

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        record = lock["components"]["bore_sched_ext_coexistence"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FinalizeError(
            f"unable to read the BORE sched_ext patch lock: {lock_path}"
        ) from exc

    if not isinstance(record, dict) or record.get("kind") != "git_patch":
        raise FinalizeError("locked BORE sched_ext source is not a Git patch record")
    locked_kernel = str(lock.get("kernel", {}).get("version", ""))
    if locked_kernel != kernel_version:
        raise FinalizeError(
            f"BORE sched_ext lock kernel mismatch: {locked_kernel!r} != {kernel_version!r}"
        )
    if record.get("selection") != "exact":
        raise FinalizeError(
            "the BORE sched_ext coexistence source was not selected exactly; "
            "refuse to use a fallback port"
        )

    sha256 = str(record.get("sha256", ""))
    output = str(record.get("output", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise FinalizeError("locked BORE sched_ext SHA-256 is invalid")
    if not output:
        raise FinalizeError("locked BORE sched_ext output path is missing")
    size = record.get("size")
    if not isinstance(size, int) or size <= 0:
        raise FinalizeError("locked BORE sched_ext size is invalid")

    resolved_root = lock_path.parent.resolve()
    patch_path = (lock_path.parent / output).resolve()
    if resolved_root not in patch_path.parents:
        raise FinalizeError(
            f"locked BORE sched_ext output escapes the resolver root: {output}"
        )
    if not patch_path.is_file() or patch_path.stat().st_size <= 0:
        raise FinalizeError(f"locked BORE sched_ext patch is missing: {patch_path}")

    data = patch_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FinalizeError("locked BORE sched_ext SHA-256 no longer matches the lock")
    if len(data) != size:
        raise FinalizeError("locked BORE sched_ext size no longer matches the lock")

    text = data.decode("utf-8")
    required = (
        "Subject: [PATCH] sched-ext-coexistence-fix",
        "diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c",
        "void reweight_task(struct task_struct *p, int prio)",
        "reweight_entity",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise FinalizeError(
            f"locked BORE sched_ext patch is missing markers: {missing}"
        )

    return record, patch_path


def patch_section(text: str, path: str, label: str) -> str:
    """Return exactly one conventional diff section for a reviewed file."""

    escaped = re.escape(path)
    section = re.compile(
        rf"^diff --git a/{escaped} b/{escaped}\n", re.MULTILINE
    )
    matches = list(section.finditer(text))
    if len(matches) != 1:
        raise FinalizeError(
            f"{label} must contain exactly one diff section for {path}"
        )
    start = matches[0].start()
    next_section = re.search(r"^diff --git ", text[matches[0].end() :], re.MULTILINE)
    end = matches[0].end() + next_section.start() if next_section else len(text)
    return text[start:end]


def reweight_task_implementation(text: str, label: str) -> str:
    """Return a formatting/comment-insensitive reweight_task implementation.

    Both the upstream source and the Linux 7.1 port are unified patches. The
    local port deliberately changes context and adds the declaration required
    by the newer BORE header, but it must not silently preserve an older helper
    implementation if upstream changes the function itself.
    """

    lines = []
    for line in text.splitlines():
        if line.startswith("+++"):
            continue
        lines.append(line[1:] if line.startswith("+") else line)

    signature = "void reweight_task(struct task_struct *p, int prio)"
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if line.strip().startswith(signature)
        )
    except StopIteration as exc:
        raise FinalizeError(f"{label} has no reweight_task implementation") from exc

    function: list[str] = []
    depth = 0
    opened = False
    for line in lines[start:]:
        function.append(line)
        depth += line.count("{") - line.count("}")
        opened = opened or "{" in line
        if opened and depth == 0:
            break
    else:
        raise FinalizeError(f"{label} reweight_task implementation is incomplete")

    rendered = "\n".join(function)
    rendered = re.sub(r"/\*.*?\*/", "", rendered, flags=re.DOTALL)
    rendered = re.sub(r"//[^\n]*", "", rendered)
    return re.sub(r"\s+", "", rendered)


def reweight_task_patch_lines(text: str, label: str) -> list[str]:
    """Extract the added helper from one structurally compatible upstream patch."""

    lines = text.splitlines(keepends=True)
    signature = "+void reweight_task(struct task_struct *p, int prio)"
    matches = [index for index, line in enumerate(lines) if line.rstrip("\n") == signature]
    if len(matches) != 1:
        raise FinalizeError(f"{label} must add exactly one reweight_task helper")

    start = matches[0]
    function: list[str] = []
    depth = 0
    opened = False
    for line in lines[start:]:
        if not line.startswith("+"):
            raise FinalizeError(f"{label} reweight_task helper has unexpected patch context")
        function.append(line)
        source = line[1:]
        depth += source.count("{") - source.count("}")
        opened = opened or "{" in source
        if opened and depth == 0:
            break
    else:
        raise FinalizeError(f"{label} reweight_task helper is incomplete")

    rendered = "".join(function)
    if "reweight_entity" not in rendered or "sched_prio_to_weight" not in rendered:
        raise FinalizeError(
            f"{label} reweight_task helper no longer matches the supported adapter structure"
        )
    return function


def replace_port_function(template: str, upstream: str) -> str:
    """Keep the Linux 7.1 context/declaration while carrying current upstream code."""

    port_lines = template.splitlines(keepends=True)
    upstream_lines = reweight_task_patch_lines(upstream, "locked BORE sched_ext source")
    signature = "+void reweight_task(struct task_struct *p, int prio)"
    matches = [
        index
        for index, line in enumerate(port_lines)
        if line.rstrip("\n") == signature
    ]
    if len(matches) != 1:
        raise FinalizeError("Linux 7.1 sched_ext port template must contain one reweight_task helper")

    start = matches[0]
    end = start
    depth = 0
    opened = False
    while end < len(port_lines):
        line = port_lines[end]
        if not line.startswith("+"):
            raise FinalizeError("Linux 7.1 sched_ext port template has unexpected helper context")
        source = line[1:]
        depth += source.count("{") - source.count("}")
        opened = opened or "{" in source
        end += 1
        if opened and depth == 0:
            break
    else:
        raise FinalizeError("Linux 7.1 sched_ext port template helper is incomplete")

    return "".join(port_lines[:start] + upstream_lines + port_lines[end:])


def materialize_sched_ext_port(
    lock_path: Path,
    record: dict[str, Any],
    upstream_patch: Path,
    kernel_version: str,
) -> dict[str, Any]:
    """Create a lock-checked Linux 7.1 port from the current upstream helper.

    Only the fair.c context and BORE header declaration come from the reviewed
    template. The complete helper body is taken from the exact upstream bytes
    recorded in this build's lock. If either patch stops following that narrow
    structure, the build stops before the kernel checkout instead of applying
    an old port to a new source.
    """

    if not SCHED_EXT_PORT_TEMPLATE.is_file():
        raise FinalizeError(
            f"maintained BORE sched_ext port template is missing: {SCHED_EXT_PORT_TEMPLATE}"
        )

    if not re.fullmatch(r"\d+\.\d+\.\d+", kernel_version):
        raise FinalizeError(f"invalid Linux version for sched_ext port: {kernel_version!r}")

    upstream = upstream_patch.read_text(encoding="utf-8")
    template = SCHED_EXT_PORT_TEMPLATE.read_text(encoding="utf-8")
    upstream_fair = patch_section(
        upstream, "kernel/sched/fair.c", "locked BORE sched_ext source"
    )
    patch_section(template, "kernel/sched/fair.c", "Linux 7.1 sched_ext port template")
    patch_section(
        template, "include/linux/sched/bore.h", "Linux 7.1 sched_ext port template"
    )
    declaration = "extern void reweight_task(struct task_struct *p, int prio);"
    if declaration not in template:
        raise FinalizeError("Linux 7.1 sched_ext port template lacks the required declaration")

    port = replace_port_function(template, upstream_fair)
    source_sha256 = str(record["sha256"])
    port = replace_regex_once(
        port,
        r"^From [0-9a-f]{40} .*$",
        f"From {source_sha256[:40]} Mon Sep 17 00:00:00 2001",
        "generated sched_ext port From header",
    )
    port = replace_regex_once(
        port,
        r"^Subject: \[PATCH\] sched: port 0002 sched-ext coexistence fix to Linux [0-9.]+$",
        f"Subject: [PATCH] sched: adapt locked sched-ext coexistence fix to Linux {kernel_version}",
        "generated sched_ext port subject",
    )
    port = replace_regex_once(
        port,
        r"^Upstream-sha256: [0-9a-f]{64}$",
        f"Upstream-sha256: {source_sha256}",
        "generated sched_ext port source digest",
    )

    generated_fair = patch_section(
        port, "kernel/sched/fair.c", "generated BORE sched_ext port"
    )
    if reweight_task_implementation(generated_fair, "generated BORE sched_ext port") != (
        reweight_task_implementation(upstream_fair, "locked BORE sched_ext source")
    ):
        raise FinalizeError("generated BORE sched_ext port does not preserve upstream helper")

    output = f"files/01-bore-sched-ext-coexistence-fix-linux{kernel_version}-port.patch"
    target = lock_path.parent / output
    target.parent.mkdir(parents=True, exist_ok=True)
    data = port.encode("utf-8")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)

    port_record = {
        "adapter": "linux7.1-sched-ext-reweight-task",
        "kernel_target": kernel_version,
        "output": output,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "source_sha256": source_sha256,
    }
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        locked_record = lock["components"]["bore_sched_ext_coexistence"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FinalizeError(
            f"unable to update the BORE sched_ext compatibility lock: {lock_path}"
        ) from exc
    if locked_record.get("sha256") != source_sha256:
        raise FinalizeError("BORE sched_ext lock changed while its port was materialized")
    locked_record["compatibility_port"] = port_record
    temporary_lock = lock_path.with_suffix(lock_path.suffix + ".tmp")
    temporary_lock.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_lock, lock_path)
    return port_record


def rewrite_core(
    path: Path,
    record: dict[str, Any],
    sched_ext_record: dict[str, Any],
    sched_ext_port: dict[str, Any],
    kernel_version: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    version = str(record["project_version"])
    sha256 = str(record["sha256"])
    output = str(record["output"])
    sched_ext_sha256 = str(sched_ext_record["sha256"])
    sched_ext_output = str(sched_ext_port["output"])

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
        r'^BORE_SCHED_EXT_PORT_UPSTREAM_SHA256=.*$',
        f'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="{sched_ext_sha256}"',
        "BORE sched_ext SHA assignment",
    )
    text = replace_regex_once(
        text,
        r'^BORE_SCHED_EXT_PATCH=.*$',
        f'BORE_SCHED_EXT_PATCH="$RESOLVED_PATCH_ROOT/{sched_ext_output}"',
        "BORE sched_ext port assignment",
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
        r'^\s*grep -Fq \'sched: port 0002 sched-ext coexistence fix to Linux [^\']+\' "\$BORE_SCHED_EXT_PATCH"$',
        '  grep -Fq "Subject: [PATCH] sched: adapt locked sched-ext coexistence fix to Linux $KERNEL_VERSION" "$BORE_SCHED_EXT_PATCH"',
        "BORE sched_ext port subject assertion",
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
    sched_ext_record, sched_ext_patch = load_locked_sched_ext(LOCK_PATH, kernel_version)
    sched_ext_port = materialize_sched_ext_port(
        LOCK_PATH, sched_ext_record, sched_ext_patch, kernel_version
    )
    core = Path(sys.argv[1])
    rewrite_core(core, record, sched_ext_record, sched_ext_port, kernel_version)

    for legacy in (ROOT / "patches/bore").glob(".resolved-*-bore-*.patch"):
        legacy.unlink(missing_ok=True)

    print(
        f"Finalized exact upstream BORE {record['project_version']} for Linux "
        f"{kernel_version}: {patch_path.relative_to(ROOT)}; validated sched_ext "
        f"source {sched_ext_patch.relative_to(ROOT)} and materialized "
        f"{sched_ext_port['output']}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except FinalizeError as exc:
        raise SystemExit(f"BORE finalization failed: {exc}") from exc
