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
            "the latest stable kernel has no exact BORE source; refuse to reuse an older reviewed port"
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
