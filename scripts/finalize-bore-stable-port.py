#!/usr/bin/env python3
"""Finalize locked BORE sources for the resolved stable kernel."""
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
# Final upstream Linux releases can be X.Y (for example 7.2) or X.Y.Z.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
_BORE_SUBJECT_RE = re.compile(
    r"^Subject: \[PATCH\] linux"
    r"(?P<target>\d+\.\d+(?:\.\d+)?(?:-rc\d+)?)"
    r"-bore-(?P<version>[^\s]+)$",
    re.MULTILINE,
)


class FinalizeError(RuntimeError):
    pass


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    compiled = re.compile(pattern, re.MULTILINE)
    matches = list(compiled.finditer(text))
    if len(matches) != 1:
        raise FinalizeError(f"{label}: expected one match, found {len(matches)}")
    return compiled.sub(lambda _match: replacement, text, count=1)


def version_tuple(value: str, label: str) -> tuple[int, int, int]:
    """Normalize a final X.Y or X.Y.Z release to a comparable 3-tuple."""
    match = _VERSION_RE.fullmatch(value)
    if not match:
        raise FinalizeError(f"invalid {label}: {value!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def bore_subject_target(text: str, project_version: str) -> str:
    """Return the exact Linux target encoded in an upstream BORE subject.

    Testing BORE patches may target an RC (for example 7.2-rc1) while the
    resolver records the compatible final series target (7.2).  The exact
    subject target is preserved for authentication and rewritten only when a
    same-series compatibility patch is materialized.
    """
    matches = list(_BORE_SUBJECT_RE.finditer(text))
    if len(matches) != 1:
        raise FinalizeError(
            f"locked BORE patch must contain exactly one recognized subject, found {len(matches)}"
        )
    match = matches[0]
    version = match.group("version")
    if version != project_version:
        raise FinalizeError(
            f"locked BORE subject version mismatch: {version!r} != {project_version!r}"
        )
    return match.group("target")


def final_target_from_bore_subject(target: str) -> str:
    """Strip only an RC suffix before comparing against a final Linux target."""
    return re.sub(r"-rc\d+$", "", target)


def load_lock_record(lock_path: Path, component: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        record = lock["components"][component]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FinalizeError(f"unable to read the {component} patch lock: {lock_path}") from exc
    if not isinstance(lock, dict) or not isinstance(record, dict):
        raise FinalizeError(f"invalid {component} patch lock")
    return lock, record


def authenticated_patch(lock_path: Path, record: dict[str, Any], label: str) -> tuple[Path, bytes]:
    sha256 = str(record.get("sha256", ""))
    output = str(record.get("output", ""))
    size = record.get("size")
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise FinalizeError(f"locked {label} SHA-256 is invalid")
    if not output:
        raise FinalizeError(f"locked {label} output path is missing")
    if not isinstance(size, int) or size <= 0:
        raise FinalizeError(f"locked {label} size is invalid")
    root = lock_path.parent.resolve()
    path = (lock_path.parent / output).resolve()
    if root not in path.parents:
        raise FinalizeError(f"locked {label} output escapes the resolver root: {output}")
    if not path.is_file() or path.stat().st_size <= 0:
        raise FinalizeError(f"locked {label} patch is missing: {path}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FinalizeError(f"locked {label} patch SHA-256 no longer matches the lock")
    if len(data) != size:
        raise FinalizeError(f"locked {label} patch size no longer matches the lock")
    return path, data


def load_locked_bore(lock_path: Path, kernel_version: str) -> tuple[dict[str, Any], Path]:
    lock, record = load_lock_record(lock_path, "bore")
    if record.get("kind") != "git_patch":
        raise FinalizeError("locked BORE source is not a Git patch record")
    locked_kernel = str(lock.get("kernel", {}).get("version", ""))
    if locked_kernel != kernel_version:
        raise FinalizeError(f"BORE lock kernel mismatch: {locked_kernel!r} != {kernel_version!r}")
    if record.get("selection") != "exact":
        raise FinalizeError(
            "the latest stable kernel has no exact BORE source; refuse to reuse an older reviewed port"
        )
    source_target = str(record.get("kernel_target", ""))
    source_version = version_tuple(source_target, "locked BORE kernel target")
    target_version = version_tuple(kernel_version, "Linux version for BORE")
    if source_version[:2] != target_version[:2] or target_version < source_version:
        raise FinalizeError(
            f"BORE target mismatch: {source_target!r} is not a compatible same-series source for {kernel_version!r}"
        )
    version = str(record.get("project_version", ""))
    if not version:
        raise FinalizeError("locked BORE project version is missing")
    patch_path, data = authenticated_patch(lock_path, record, "BORE")
    text = data.decode("utf-8")
    subject_target = bore_subject_target(text, version)
    subject_final_target = final_target_from_bore_subject(subject_target)
    subject_version = version_tuple(subject_final_target, "BORE subject Linux target")
    if subject_version != source_version:
        raise FinalizeError(
            f"BORE lock target {source_target!r} does not match subject target {subject_target!r}"
        )
    if subject_version[:2] != target_version[:2] or target_version < subject_version:
        raise FinalizeError(
            f"BORE subject target {subject_target!r} is not compatible with {kernel_version!r}"
        )
    required = (
        f"Subject: [PATCH] linux{subject_target}-bore-{version}",
        "SCHED_BORE_VERSION",
        f'"{version}"',
        "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c",
        "sched_bore",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise FinalizeError(f"locked BORE patch is missing markers: {missing}")
    return record, patch_path


def load_locked_sched_ext(lock_path: Path, kernel_version: str) -> tuple[dict[str, Any], Path]:
    lock, record = load_lock_record(lock_path, "bore_sched_ext_coexistence")
    if record.get("kind") != "git_patch":
        raise FinalizeError("locked BORE sched_ext source is not a Git patch record")
    locked_kernel = str(lock.get("kernel", {}).get("version", ""))
    if locked_kernel != kernel_version:
        raise FinalizeError(
            f"BORE sched_ext lock kernel mismatch: {locked_kernel!r} != {kernel_version!r}"
        )
    if record.get("selection") != "exact":
        raise FinalizeError(
            "the BORE sched_ext coexistence source was not selected exactly; refuse to use a fallback port"
        )
    patch_path, data = authenticated_patch(lock_path, record, "BORE sched_ext")
    text = data.decode("utf-8")
    required = (
        "Subject: [PATCH] sched-ext-coexistence-fix",
        "diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c",
        "void reweight_task(struct task_struct *p, int prio)",
        "reweight_entity",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise FinalizeError(f"locked BORE sched_ext patch is missing markers: {missing}")
    return record, patch_path


def patch_section(text: str, path: str, label: str) -> str:
    escaped = re.escape(path)
    section = re.compile(rf"^diff --git a/{escaped} b/{escaped}\n", re.MULTILINE)
    matches = list(section.finditer(text))
    if len(matches) != 1:
        raise FinalizeError(f"{label} must contain exactly one diff section for {path}")
    start = matches[0].start()
    next_section = re.search(r"^diff --git ", text[matches[0].end():], re.MULTILINE)
    end = matches[0].end() + next_section.start() if next_section else len(text)
    return text[start:end]


def reweight_task_implementation(text: str, label: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("+++"):
            continue
        lines.append(line[1:] if line.startswith("+") else line)
    signature = "void reweight_task(struct task_struct *p, int prio)"
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().startswith(signature))
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
    lines = text.splitlines(keepends=True)
    signature = "+void reweight_task(struct task_struct *p, int prio)"
    matches = [i for i, line in enumerate(lines) if line.rstrip("\n") == signature]
    if len(matches) != 1:
        raise FinalizeError(f"{label} must add exactly one reweight_task helper")
    function: list[str] = []
    depth = 0
    opened = False
    for line in lines[matches[0]:]:
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
    port_lines = template.splitlines(keepends=True)
    upstream_lines = reweight_task_patch_lines(upstream, "locked BORE sched_ext source")
    signature = "+void reweight_task(struct task_struct *p, int prio)"
    matches = [i for i, line in enumerate(port_lines) if line.rstrip("\n") == signature]
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


def update_compatibility_lock(
    lock_path: Path, component: str, source_sha256: str, port_record: dict[str, Any]
) -> None:
    lock, locked_record = load_lock_record(lock_path, component)
    if locked_record.get("sha256") != source_sha256:
        raise FinalizeError(f"{component} lock changed while its port was materialized")
    locked_record["compatibility_port"] = port_record
    temporary = lock_path.with_suffix(lock_path.suffix + ".tmp")
    temporary.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, lock_path)


def write_port(lock_path: Path, output: str, data: bytes) -> Path:
    target = lock_path.parent / output
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return target


def materialize_bore_patchlevel_port(
    lock_path: Path,
    record: dict[str, Any],
    upstream_patch: Path,
    kernel_version: str,
) -> dict[str, Any] | None:
    source_target = str(record.get("kernel_target", ""))
    locked_source_version = version_tuple(source_target, "locked BORE kernel target")
    target_version = version_tuple(kernel_version, "Linux version for BORE")
    project_version = str(record["project_version"])
    source_sha256 = str(record["sha256"])
    source_text = upstream_patch.read_text(encoding="utf-8")
    subject_target = bore_subject_target(source_text, project_version)
    subject_final_target = final_target_from_bore_subject(subject_target)
    source_version = version_tuple(subject_final_target, "BORE subject Linux target")
    if source_version != locked_source_version:
        raise FinalizeError(
            f"BORE lock target {source_target!r} does not match subject target {subject_target!r}"
        )
    if subject_target == kernel_version:
        return None
    if source_version[:2] != target_version[:2] or target_version < source_version:
        raise FinalizeError(
            f"BORE target mismatch: {subject_target!r} is not a compatible same-series source for {kernel_version!r}"
        )
    source_subject = f"Subject: [PATCH] linux{subject_target}-bore-{project_version}"
    target_subject = f"Subject: [PATCH] linux{kernel_version}-bore-{project_version}"
    port = replace_regex_once(
        source_text,
        rf"^{re.escape(source_subject)}$",
        target_subject,
        "generated BORE same-series port subject",
    )
    if port.replace(target_subject, source_subject, 1) != source_text:
        raise FinalizeError("generated BORE same-series port changed content outside its subject")
    output = f"files/01-bore-linux{kernel_version}-patchlevel-port.patch"
    data = port.encode("utf-8")
    write_port(lock_path, output, data)
    port_record = {
        "adapter": "same-series-bore-patchlevel-metadata",
        "kernel_target": kernel_version,
        "source_kernel_target": subject_target,
        "output": output,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "source_sha256": source_sha256,
    }
    update_compatibility_lock(lock_path, "bore", source_sha256, port_record)
    return port_record


def materialize_sched_ext_port(
    lock_path: Path,
    record: dict[str, Any],
    upstream_patch: Path,
    kernel_version: str,
) -> dict[str, Any]:
    if not SCHED_EXT_PORT_TEMPLATE.is_file():
        raise FinalizeError(f"maintained BORE sched_ext port template is missing: {SCHED_EXT_PORT_TEMPLATE}")
    version_tuple(kernel_version, "Linux version for sched_ext port")
    upstream = upstream_patch.read_text(encoding="utf-8")
    template = SCHED_EXT_PORT_TEMPLATE.read_text(encoding="utf-8")
    upstream_fair = patch_section(upstream, "kernel/sched/fair.c", "locked BORE sched_ext source")
    patch_section(template, "kernel/sched/fair.c", "Linux 7.1 sched_ext port template")
    patch_section(template, "include/linux/sched/bore.h", "Linux 7.1 sched_ext port template")
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
    generated_fair = patch_section(port, "kernel/sched/fair.c", "generated BORE sched_ext port")
    if reweight_task_implementation(generated_fair, "generated BORE sched_ext port") != reweight_task_implementation(
        upstream_fair, "locked BORE sched_ext source"
    ):
        raise FinalizeError("generated BORE sched_ext port does not preserve upstream helper")
    output = f"files/01-bore-sched-ext-coexistence-fix-linux{kernel_version}-port.patch"
    data = port.encode("utf-8")
    write_port(lock_path, output, data)
    port_record = {
        "adapter": "linux7.1-sched-ext-reweight-task",
        "kernel_target": kernel_version,
        "output": output,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "source_sha256": source_sha256,
    }
    update_compatibility_lock(
        lock_path, "bore_sched_ext_coexistence", source_sha256, port_record
    )
    return port_record


def rewrite_core(
    path: Path,
    record: dict[str, Any],
    sched_ext_record: dict[str, Any],
    sched_ext_port: dict[str, Any],
    kernel_version: str,
    bore_port: dict[str, Any] | None = None,
) -> None:
    text = path.read_text(encoding="utf-8")
    version = str(record["project_version"])
    sha256 = str(record["sha256"])
    output = str((bore_port or record)["output"])
    sched_ext_sha256 = str(sched_ext_record["sha256"])
    sched_ext_output = str(sched_ext_port["output"])
    replacements = (
        (r'^BORE_PATCH=.*$', f'BORE_PATCH="$RESOLVED_PATCH_ROOT/{output}"', "BORE patch assignment"),
        (r'^BORE_PORT_VERSION=.*$', f'BORE_PORT_VERSION="{version}"', "BORE version assignment"),
        (r'^BORE_PORT_UPSTREAM_SHA256=.*$', f'BORE_PORT_UPSTREAM_SHA256="{sha256}"', "BORE SHA assignment"),
        (r'^BORE_SCHED_EXT_PORT_UPSTREAM_SHA256=.*$', f'BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="{sched_ext_sha256}"', "BORE sched_ext SHA assignment"),
        (r'^BORE_SCHED_EXT_PATCH=.*$', f'BORE_SCHED_EXT_PATCH="$RESOLVED_PATCH_ROOT/{sched_ext_output}"', "BORE sched_ext port assignment"),
        (r'^\s*grep -Fq \'SCHED_BORE_VERSION  "[^"]+"\' "\$BORE_UPSTREAM_PATCH"$', '  grep -Fq "SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"" "$BORE_UPSTREAM_PATCH"', "BORE upstream version assertion"),
        (r'^\s*grep -Fq \'sched: port BORE [^\']+ to Linux [^\']+\' "\$BORE_PATCH"$', '  grep -Fq "Subject: [PATCH] linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}" "$BORE_PATCH"', "BORE subject assertion"),
        (r'^\s*grep -Fq \'sched: port 0002 sched-ext coexistence fix to Linux [^\']+\' "\$BORE_SCHED_EXT_PATCH"$', '  grep -Fq "Subject: [PATCH] sched: adapt locked sched-ext coexistence fix to Linux $KERNEL_VERSION" "$BORE_SCHED_EXT_PATCH"', "BORE sched_ext port subject assertion"),
        (r'Applying the reviewed BORE [^"\n]+ Linux [0-9.]+ port', 'Applying upstream BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION', "BORE apply label"),
        (r'report_bore_rejects "BORE [0-9][^"]* for Linux [0-9.]+"', 'report_bore_rejects "BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION"', "BORE reject label"),
        (r'^\s*git diff --check \| tee "\$LOGDIR/01-bore-diff-check\.log"$', '  if ! git diff --check > "$LOGDIR/01-bore-diff-check.log" 2>&1; then\n    cat "$LOGDIR/01-bore-diff-check.log"\n    echo "==> Normalizing whitespace introduced by BORE patch"\n    normalize_changed_whitespace\n    git diff --check | tee "$LOGDIR/01-bore-diff-check-after-fix.log"\n  fi', "BORE whitespace validation"),
        (r'^\s*grep -Fq \'SCHED_BORE_VERSION\' kernel/sched/bore\.c$', '  grep -Fq "SCHED_BORE_VERSION  \\\"$BORE_PORT_VERSION\\\"" include/linux/sched/bore.h', "BORE installed version assertion"),
        (r'BORE [^"\n]+ Linux port applied successfully', 'BORE $BORE_PORT_VERSION Linux port applied successfully', "BORE success label"),
    )
    for pattern, replacement, label in replacements:
        text = replace_regex_once(text, pattern, replacement, label)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: finalize-bore-stable-port.py <generated-core-script>")
    kernel_version = os.environ.get("KERNEL_VERSION")
    if not kernel_version:
        raise SystemExit("KERNEL_VERSION must be resolved before finalizing BORE")
    record, patch_path = load_locked_bore(LOCK_PATH, kernel_version)
    bore_port = materialize_bore_patchlevel_port(LOCK_PATH, record, patch_path, kernel_version)
    sched_ext_record, sched_ext_patch = load_locked_sched_ext(LOCK_PATH, kernel_version)
    sched_ext_port = materialize_sched_ext_port(
        LOCK_PATH, sched_ext_record, sched_ext_patch, kernel_version
    )
    core = Path(sys.argv[1])
    rewrite_core(
        core, record, sched_ext_record, sched_ext_port, kernel_version, bore_port
    )
    for legacy in (ROOT / "patches/bore").glob(".resolved-*-bore-*.patch"):
        legacy.unlink(missing_ok=True)
    selected = bore_port["output"] if bore_port else str(patch_path.relative_to(ROOT))
    mode = "same-series compatibility port" if bore_port else "exact upstream patch"
    print(
        f"Finalized BORE {record['project_version']} for Linux {kernel_version} via {mode}: "
        f"{selected}; validated sched_ext source {sched_ext_patch.relative_to(ROOT)} and "
        f"materialized {sched_ext_port['output']}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except FinalizeError as exc:
        raise SystemExit(f"BORE finalization failed: {exc}") from exc
