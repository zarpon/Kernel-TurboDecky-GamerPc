#!/usr/bin/env python3
"""Compatibility front-end for the BORE stable finalizer.

The implementation is kept in finalize-bore-stable-port-base.py. This front-end
only tightens subject validation so an exact same-series BORE source may retain
its upstream -rcN subject qualifier while still being authenticated by the lock.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_BASE_PATH = Path(__file__).with_name("finalize-bore-stable-port-base.py")
_spec = importlib.util.spec_from_file_location("_bore_stable_finalizer_base", _BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"unable to load BORE finalizer base: {_BASE_PATH}")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)

# Preserve the original module API for tests and callers.
for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)


def _bore_subject_match(text: str, source_target: str, version: str) -> re.Match[str] | None:
    """Match exactly the locked BORE subject, allowing only an upstream -rcN qualifier."""
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


# Make the base main() use the corrected functions while retaining the rest of its
# fail-closed implementation unchanged.
_base.load_locked_bore = load_locked_bore
_base.materialize_bore_patchlevel_port = materialize_bore_patchlevel_port

# The base finalizer also rewrites a runtime assertion inside the generated shell
# build. Its historical assertion required a subject without -rcN, even when the
# authenticated exact source selected by the resolver legitimately carries the
# upstream same-series -rcN qualifier. Intercept only that labeled rewrite and
# keep every other replacement unchanged.
_base_replace_regex_once = _base.replace_regex_once


def _replace_regex_once_with_rc_subject(
    text: str, pattern: str, replacement: str, label: str
) -> str:
    if label == "BORE subject assertion":
        replacement = (
            '  grep -Eq "^Subject: \\[PATCH\\] linux${KERNEL_VERSION}'
            '(-rc[0-9]+)?-bore-${BORE_PORT_VERSION}$" "$BORE_PATCH"'
        )
    return _base_replace_regex_once(text, pattern, replacement, label)


_base.replace_regex_once = _replace_regex_once_with_rc_subject


def main() -> None:
    _base.main()


if __name__ == "__main__":
    try:
        main()
    except _base.FinalizeError as exc:
        raise SystemExit(f"BORE finalization failed: {exc}") from exc
