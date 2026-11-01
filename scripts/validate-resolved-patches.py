#!/usr/bin/env python3
"""Verify that every resolved patch byte-for-byte matches its generated lock."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class IntegrityError(RuntimeError):
    pass


def load_lock(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"unable to read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise IntegrityError("unsupported resolved patch lock")
    if not isinstance(value.get("components"), dict):
        raise IntegrityError("resolved patch lock has no components object")
    return value


def contained_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise IntegrityError(f"resolved output escapes lock directory: {relative}") from exc
    return candidate


def validate_materialized_output(root: Path, name: str, record: dict[str, Any]) -> None:
    digest = record.get("sha256")
    size = record.get("size")
    output = record.get("output")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise IntegrityError(f"{name}: invalid SHA-256 in lock")
    if not isinstance(size, int) or size <= 0:
        raise IntegrityError(f"{name}: invalid size in lock")
    if not isinstance(output, str) or not output:
        raise IntegrityError(f"{name}: missing output path")
    path = contained_file(root, output)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise IntegrityError(f"{name}: unable to read materialized output {path}: {exc}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != digest:
        raise IntegrityError(f"{name}: materialized SHA-256 {actual} != lock {digest}")
    if len(data) != size:
        raise IntegrityError(f"{name}: materialized size {len(data)} != lock {size}")


# Explicitly reviewed BORE 7.4-rc1 source; all other fallback ports remain forbidden.
REVIEWED_BORE_74_SOURCE_SHA = "0de0f56c2e3db14b4bb2797aa0362a623d4b7e39643add1da65f91a1cedcdcfd"


def reviewed_bore74_fallback(name: str, record: dict[str, Any],
                             port: dict[str, Any], lock: dict[str, Any]) -> bool:
    return (
        name == "bore"
        and lock.get("kernel", {}).get("version") == "7.4-rc1"
        and record.get("selection") == "fallback"
        and record.get("kernel_target") == "7.3-rc2"
        and record.get("project_version") == "7.0.0"
        and record.get("selected_path") == "patches/stable/0001-linux7.3-rc2-bore-7.0.0.patch"
        and record.get("sha256") == REVIEWED_BORE_74_SOURCE_SHA
        and port.get("adapter") == "linux7.4-rc1-bore7.0.0-futex-context"
        and port.get("kernel_target") == "7.4-rc1"
        and port.get("source_kernel_target") == "7.3-rc2"
        and port.get("source_sha256") == REVIEWED_BORE_74_SOURCE_SHA
    )


def validate_lock(lock_path: Path) -> int:
    lock = load_lock(lock_path)
    root = lock_path.parent
    checked = 0
    for name, raw in lock["components"].items():
        if not isinstance(raw, dict):
            raise IntegrityError(f"{name}: lock record must be an object")
        validate_materialized_output(root, name, raw)

        kind = raw.get("kind")
        if kind in {"git_patch", "git_file"}:
            for field in ("repo", "ref", "commit", "selected_path", "path"):
                if not isinstance(raw.get(field), str) or not raw[field]:
                    raise IntegrityError(f"{name}: missing immutable Git field {field}")
            if not re.fullmatch(r"[0-9a-f]{40}", raw["commit"]):
                raise IntegrityError(f"{name}: invalid resolved Git commit")
        elif kind == "http_patch":
            if not isinstance(raw.get("url"), str) or not raw["url"].startswith("https://"):
                raise IntegrityError(f"{name}: invalid resolved HTTPS URL")
        else:
            raise IntegrityError(f"{name}: unsupported component kind {kind!r}")
        checked += 1

        compatibility_port = raw.get("compatibility_port")
        if compatibility_port is None:
            continue
        if kind != "git_patch" or not isinstance(compatibility_port, dict):
            raise IntegrityError(f"{name}: invalid compatibility port record")
        if raw.get("selection") != "exact" and not reviewed_bore74_fallback(name, raw, compatibility_port, lock):
            raise IntegrityError(
                f"{name}: compatibility port requires an exact upstream selection"
            )
        source_sha256 = compatibility_port.get("source_sha256")
        if source_sha256 != raw.get("sha256"):
            raise IntegrityError(
                f"{name}: compatibility port source SHA-256 does not match upstream lock"
            )
        if not isinstance(compatibility_port.get("adapter"), str) or not compatibility_port["adapter"]:
            raise IntegrityError(f"{name}: compatibility port has no adapter identity")
        if compatibility_port.get("kernel_target") != lock.get("kernel", {}).get("version"):
            raise IntegrityError(f"{name}: compatibility port targets the wrong kernel")
        if compatibility_port.get("output") == raw.get("output"):
            raise IntegrityError(f"{name}: compatibility port overwrites its upstream source")
        validate_materialized_output(root, f"{name}.compatibility_port", compatibility_port)
        checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default=".resolved-patches/patch-lock.json")
    args = parser.parse_args()
    count = validate_lock(Path(args.lock))
    print(f"Resolved patch integrity passed for {count} components")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IntegrityError as exc:
        print(f"resolved patch integrity error: {exc}", file=sys.stderr)
        raise SystemExit(2)
