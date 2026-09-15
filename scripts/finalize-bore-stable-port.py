#!/usr/bin/env python3
"""Compatibility front-end for the BORE stable finalizer.

The implementation is kept in finalize-bore-stable-port-base.py. This front-end
tightens BORE subject validation and performs final generated-core compatibility
rewrites after every earlier source rewriter has completed.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

_BASE_PATH = Path(__file__).with_name("finalize-bore-stable-port-base.py")
_spec = importlib.util.spec_from_file_location("_bore_stable_finalizer_base", _BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"unable to load BORE finalizer base: {_BASE_PATH}")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)

for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)


_RC_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:-rc(\d+))?$")


def _version_tuple_with_rc(value: str, label: str) -> tuple[int, int, int, int]:
    """Order RCs before the final release while preserving patchlevel ordering."""
    match = _RC_VERSION_RE.fullmatch(value)
    if not match:
        raise _base.FinalizeError(f"invalid {label}: {value!r}")
    major, minor, patch, rc = match.groups()
    if rc is not None:
        return int(major), int(minor), 0, int(rc)
    return int(major), int(minor), 1, int(patch or 0)


# The base finalizer predates RC targets. Keep every finalizer behavior intact,
# replacing only version parsing/comparison so e.g. 7.3-rc2 can be safely
# metadata-ported forward to 7.3-rc3 without selecting an older BORE release.
_base.version_tuple = _version_tuple_with_rc
version_tuple = _version_tuple_with_rc


def _bore_subject_match(text: str, source_target: str, version: str) -> re.Match[str] | None:
    pattern = re.compile(
        rf"^Subject: \[PATCH\] linux{re.escape(source_target)}(?:-rc\d+)?-bore-{re.escape(version)}$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        return None
    return matches[0]


def load_locked_bore(lock_path: Path, kernel_version: str):
    lock, record = _base.load_lock_record(lock_path, "bore")
    if record.get("kind") != "git_patch":
        raise _base.FinalizeError("locked BORE source is not a Git patch record")
    locked_kernel = str(lock.get("kernel", {}).get("version", ""))
    if locked_kernel != kernel_version:
        raise _base.FinalizeError(
            f"BORE lock kernel mismatch: {locked_kernel!r} != {kernel_version!r}"
        )
    if record.get("selection") != "exact":
        raise _base.FinalizeError(
            "the latest upstream kernel has no exact BORE source; refuse to reuse an older reviewed port"
        )
    source_target = str(record.get("kernel_target", ""))
    source_version = _base.version_tuple(source_target, "locked BORE kernel target")
    target_version = _base.version_tuple(kernel_version, "Linux version for BORE")
    if source_version[:2] != target_version[:2] or target_version < source_version:
        raise _base.FinalizeError(
            f"BORE target mismatch: {source_target!r} is not a compatible same-series source for {kernel_version!r}"
        )
    version = str(record.get("project_version", ""))
    if not version:
        raise _base.FinalizeError("locked BORE project version is missing")
    patch_path, data = _base.authenticated_patch(lock_path, record, "BORE")
    text = data.decode("utf-8")
    if _bore_subject_match(text, source_target, version) is None:
        raise _base.FinalizeError(
            "locked BORE patch subject does not match the locked kernel target/project version"
        )
    required = (
        "SCHED_BORE_VERSION",
        f'"{version}"',
        "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c",
        "sched_bore",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise _base.FinalizeError(f"locked BORE patch is missing markers: {missing}")
    return record, patch_path


def materialize_bore_patchlevel_port(lock_path, record, upstream_patch, kernel_version):
    source_target = str(record.get("kernel_target", ""))
    source_version = _base.version_tuple(source_target, "locked BORE kernel target")
    target_version = _base.version_tuple(kernel_version, "Linux version for BORE")
    if source_target == kernel_version:
        return None
    if source_version[:2] != target_version[:2] or target_version < source_version:
        raise _base.FinalizeError(
            f"BORE target mismatch: {source_target!r} is not a compatible same-series source for {kernel_version!r}"
        )
    project_version = str(record["project_version"])
    source_sha256 = str(record["sha256"])
    source_text = upstream_patch.read_text(encoding="utf-8")
    subject_match = _bore_subject_match(source_text, source_target, project_version)
    if subject_match is None:
        raise _base.FinalizeError(
            "locked BORE patch subject does not match the locked kernel target/project version"
        )
    source_subject = subject_match.group(0)
    target_subject = f"Subject: [PATCH] linux{kernel_version}-bore-{project_version}"
    port = source_text[: subject_match.start()] + target_subject + source_text[subject_match.end() :]
    if port.replace(target_subject, source_subject, 1) != source_text:
        raise _base.FinalizeError("generated BORE patch-level port changed content outside its subject")
    output = f"files/01-bore-linux{kernel_version}-patchlevel-port.patch"
    data = port.encode("utf-8")
    _base.write_port(lock_path, output, data)
    port_record = {
        "adapter": "same-series-bore-patchlevel-metadata",
        "kernel_target": kernel_version,
        "source_kernel_target": source_target,
        "output": output,
        "sha256": _base.hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "source_sha256": source_sha256,
    }
    _base.update_compatibility_lock(lock_path, "bore", source_sha256, port_record)
    return port_record


_base.load_locked_bore = load_locked_bore
_base.materialize_bore_patchlevel_port = materialize_bore_patchlevel_port


# Linux 7.3 split the load reweight operation used by the locked upstream
# sched_ext coexistence helper. Keep exact upstream helper copying for older
# kernels, and use the reviewed reweight_task_fair() adapter only for 7.3.
_base_replace_port_function = _base.replace_port_function
_base_reweight_task_implementation = _base.reweight_task_implementation
_base_materialize_sched_ext_port = _base.materialize_sched_ext_port
_semantic_sched_ext_target = False


def _is_linux_73_target(kernel_version: str) -> bool:
    match = _RC_VERSION_RE.fullmatch(kernel_version)
    return bool(match and match.group(1) == "7" and match.group(2) == "3")


def _replace_port_function_semantic(template: str, upstream: str) -> str:
    _base.reweight_task_patch_lines(upstream, "locked BORE sched_ext source")
    if not _semantic_sched_ext_target:
        return _base_replace_port_function(template, upstream)

    implementation = _base_reweight_task_implementation(
        template, "maintained Linux 7.3 BORE sched_ext adapter"
    )
    required = (
        "structload_weightlw={",
        ".weight=scale_load(sched_prio_to_weight[prio]),",
        ".inv_weight=sched_prio_to_wmult[prio],",
        "reweight_task_fair(task_rq(p),p,&lw);",
    )
    missing = [marker for marker in required if marker not in implementation]
    if missing:
        raise _base.FinalizeError(
            f"maintained Linux 7.3 BORE sched_ext adapter lost semantic markers: {missing}"
        )
    return template


def _reweight_task_implementation_semantic(text: str, label: str) -> str:
    implementation = _base_reweight_task_implementation(text, label)
    if not _semantic_sched_ext_target:
        return implementation

    upstream_markers = (
        "unsignedlongweight=scale_load(sched_prio_to_weight[prio]);",
        "reweight_entity(cfs_rq,se,weight);",
        "load->inv_weight=sched_prio_to_wmult[prio];",
    )
    adapter_markers = (
        "structload_weightlw={",
        ".weight=scale_load(sched_prio_to_weight[prio]),",
        ".inv_weight=sched_prio_to_wmult[prio],",
        "reweight_task_fair(task_rq(p),p,&lw);",
    )
    if all(marker in implementation for marker in upstream_markers):
        return "__bore_linux_7_3_reweight_semantics__"
    if all(marker in implementation for marker in adapter_markers):
        return "__bore_linux_7_3_reweight_semantics__"
    raise _base.FinalizeError(
        f"{label} no longer matches the reviewed Linux 7.3 reweight semantics"
    )


def materialize_sched_ext_port(lock_path, record, upstream_patch, kernel_version):
    global _semantic_sched_ext_target
    previous = _semantic_sched_ext_target
    semantic_target = _is_linux_73_target(kernel_version)
    _semantic_sched_ext_target = semantic_target
    try:
        port_record = _base_materialize_sched_ext_port(
            lock_path, record, upstream_patch, kernel_version
        )
        if semantic_target:
            source_sha256 = str(record["sha256"])
            port_record["adapter"] = "linux7.3-sched-ext-reweight-task-fair"
            _base.update_compatibility_lock(
                lock_path,
                "bore_sched_ext_coexistence",
                source_sha256,
                port_record,
            )
        return port_record
    finally:
        _semantic_sched_ext_target = previous


_base.replace_port_function = _replace_port_function_semantic
_base.reweight_task_implementation = _reweight_task_implementation_semantic
_base.materialize_sched_ext_port = materialize_sched_ext_port


_base_replace_regex_once = _base.replace_regex_once


def _replace_regex_once_with_rc_subject(
    text: str, pattern: str, replacement: str, label: str
) -> str:
    if label == "BORE subject assertion":
        replacement = (
            '  BORE_EXPECTED_SUBJECT="linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}"\n'
            '  BORE_RC_SUBJECT="linux${KERNEL_VERSION}-rc[0-9]+-bore-${BORE_PORT_VERSION}"\n'
            '  grep -Eq "^Subject: \\[PATCH\\] (${BORE_EXPECTED_SUBJECT}|${BORE_RC_SUBJECT})$" "$BORE_PATCH"'
        )
    return _base_replace_regex_once(text, pattern, replacement, label)


_base.replace_regex_once = _replace_regex_once_with_rc_subject


def finalize_cpu_optimization_fallback() -> None:
    if len(sys.argv) < 2:
        raise _base.FinalizeError("generated core path is missing for final compatibility rewrite")
    core = Path(sys.argv[1])
    helper = Path(__file__).with_name("apply-cpu-optimizations-7.2-port.py")
    try:
        subprocess.run([sys.executable, str(helper), str(core)], check=True)
    except subprocess.CalledProcessError as exc:
        raise _base.FinalizeError("unable to finalize Linux 7.2 CPU optimization fallback") from exc


def main() -> None:
    _base.main()
    finalize_cpu_optimization_fallback()


if __name__ == "__main__":
    try:
        main()
    except _base.FinalizeError as exc:
        raise SystemExit(f"BORE finalization failed: {exc}") from exc
