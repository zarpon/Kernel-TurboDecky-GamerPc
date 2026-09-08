#!/usr/bin/env python3
"""Resolve latest upstream patch releases first and port ZRAM-IR to Linux 7.2."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "resolve-patch-sources-base.py"
PORT_PATH = HERE.parent / "patches" / "ports" / "zram-ir-1.3-linux7.2.patch"
ZRAM_PORT_VERSION = "1.3"
ZRAM_PORT_UPSTREAM_SHA256 = "1620f45f0fbab1173c8693a2afc0ada37920c78fdde2d0cbff6afe28545128f4"

spec = importlib.util.spec_from_file_location("turbodecky_patch_resolver_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit(f"unable to load resolver base: {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)


def latest_first_candidate_score(
    path: str, kernel: Any, version_pattern: str | None
) -> tuple[Any, ...]:
    """For versioned projects, newest upstream release outranks kernel proximity."""
    if not version_pattern:
        return _ORIGINAL_CANDIDATE_SCORE(path, kernel, version_pattern)
    target = base.extract_kernel_target(path)
    compat_rank, distance_rank = base.compatibility_score(target, kernel)
    target_parts = target.parts if target else ()
    channel_rank = (
        2 if "/stable/" in f"/{path}"
        else 1 if "/testing/" in f"/{path}"
        else 0
    )
    version = base.project_version(path, version_pattern)
    if not version:
        raise base.ResolverError(
            f"versioned component candidate has no project version: {path}"
        )
    return (
        base.version_key(version),
        compat_rank,
        distance_rank,
        target_parts,
        channel_rank,
        path,
    )


_ORIGINAL_CANDIDATE_SCORE = base.candidate_score
base.candidate_score = latest_first_candidate_score


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def port_zram_ir_if_needed(
    lock: dict[str, Any], output_dir: Path, kernel: Any, kernel_series: str
) -> None:
    if kernel_series != "7.2":
        return
    record = lock.get("components", {}).get("zram_ir")
    if not isinstance(record, dict):
        raise base.ResolverError("zram_ir is missing from patch lock")

    selected_version = str(record.get("project_version") or "")
    if selected_version != ZRAM_PORT_VERSION:
        raise base.ResolverError(
            "newest ZRAM-IR release is "
            f"{selected_version or 'unknown'}, but the reviewed Linux 7.2 port is "
            f"{ZRAM_PORT_VERSION}; port the newest release before building"
        )

    upstream_sha = str(record.get("sha256") or "")
    if upstream_sha != ZRAM_PORT_UPSTREAM_SHA256:
        raise base.ResolverError(
            "ZRAM-IR upstream bytes changed for version "
            f"{ZRAM_PORT_VERSION}: {upstream_sha} != {ZRAM_PORT_UPSTREAM_SHA256}; "
            "review and refresh the Linux 7.2 port"
        )

    target = base.extract_kernel_target(str(record.get("selected_path") or ""))
    if target is not None and target.series == kernel.series:
        return

    port = PORT_PATH.read_bytes()
    base.validate_patch(
        port,
        "zram_ir",
        ["zram_recomp_immediate", 'ZRAM_IR_VERSION "1.3"', "last_prio", "ZRAM_INCOMPRESSIBLE"],
    )
    output = output_dir / str(record["output"])
    upstream = {
        key: value
        for key, value in record.items()
        if key not in {"sha256", "size", "selection", "origin", "port_path", "upstream"}
    }
    upstream["sha256"] = upstream_sha
    upstream["size"] = output.stat().st_size
    output.write_bytes(port)
    record.update(
        {
            "origin": "local-port",
            "selection": "latest-upstream-port",
            "port_path": str(PORT_PATH.relative_to(HERE.parent)),
            "port_for_kernel": kernel.text,
            "upstream": upstream,
            "sha256": sha256(port),
            "size": len(port),
        }
    )
    (output_dir / "patch-lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kernel-version", required=True)
    parser.add_argument("--kernel-series", required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    kernel = base.KernelVersion.parse(args.kernel_version)
    expected_series = f"{kernel.series[0]}.{kernel.series[1]}"
    if args.kernel_series != expected_series:
        raise SystemExit(
            f"kernel series mismatch: {args.kernel_series} != {expected_series}"
        )

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or not isinstance(manifest.get("components"), dict):
        raise SystemExit("unsupported patch source manifest")

    try:
        lock = base.resolve(
            manifest,
            args.output_dir.resolve(),
            kernel,
            args.kernel_series,
            manifest_root=args.manifest.resolve().parent,
        )
        port_zram_ir_if_needed(lock, args.output_dir.resolve(), kernel, args.kernel_series)
    except base.ResolverError as exc:
        raise SystemExit(f"patch source resolution failed: {exc}") from exc

    lines = [
        f"Kernel: {args.kernel_version} ({args.kernel_series})",
        f"Resolved components: {len(lock['components'])}",
    ]
    for name, record in lock["components"].items():
        location = record.get("port_path") or record.get("path") or record.get("url")
        version = record.get("project_version") or "unversioned"
        lines.append(
            f"{name}: {version}; {record['selection']}; {location}; "
            f"sha256={record['sha256']}"
        )
    summary = "\n".join(lines) + "\n"
    print(summary, end="")
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
