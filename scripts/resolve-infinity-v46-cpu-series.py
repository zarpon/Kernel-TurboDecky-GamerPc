#!/usr/bin/env python3
"""Resolve the v4.6-gpu CPU/RT subset and delegate all other sources.

The upstream v4.6-gpu branch publishes six modular patches for each kernel
series. TurboDecky deliberately combines only patches 0001 through 0003 into a
single build-locked mbox so the existing application path can consume it while
DRM/GPU patches 0004 through 0006 remain excluded.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PATCH_PREFIXES = (b"From ", b"From:", b"diff --git ", b"--- a/", b"--- /dev/null")


class InfinityResolutionError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        detail = ""
        if capture:
            detail = f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        raise InfinityResolutionError(
            f"command failed ({result.returncode}): {' '.join(command)}{detail}"
        )
    return result.stdout.strip() if capture else ""


def snapshot_branch(repo: str, ref: str, destination: Path) -> str:
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "--quiet", str(destination)])
    run(["git", "-C", str(destination), "remote", "add", "origin", repo])
    run(["git", "-C", str(destination), "config", "remote.origin.promisor", "true"])
    run(
        [
            "git",
            "-C",
            str(destination),
            "config",
            "remote.origin.partialclonefilter",
            "blob:none",
        ]
    )
    command = [
        "git",
        "-C",
        str(destination),
        "fetch",
        "--no-tags",
        "--depth=1",
        "--filter=blob:none",
        "origin",
        ref,
    ]
    try:
        run(command)
    except InfinityResolutionError:
        run(
            [
                "git",
                "-C",
                str(destination),
                "fetch",
                "--no-tags",
                "--depth=1",
                "origin",
                ref,
            ]
        )
    commit = run(
        ["git", "-C", str(destination), "rev-parse", "FETCH_HEAD"], capture=True
    )
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise InfinityResolutionError(f"invalid branch-head commit: {commit!r}")
    return commit


def list_tree(repo: Path, commit: str) -> list[str]:
    output = run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commit],
        capture=True,
    )
    return [line for line in output.splitlines() if line]


def read_blob(repo: Path, commit: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise InfinityResolutionError(
            f"unable to read {path}: {result.stderr.decode(errors='replace')}"
        )
    return result.stdout


def validate_patch(
    data: bytes,
    label: str,
    required_markers: list[str],
    forbidden_markers: list[str] | None = None,
) -> None:
    if not data:
        raise InfinityResolutionError(f"empty patch: {label}")
    if not any(line.startswith(PATCH_PREFIXES) for line in data.splitlines()):
        raise InfinityResolutionError(f"not a patch: {label}")
    text = data.decode("utf-8", errors="replace")
    for marker in required_markers:
        if marker not in text:
            raise InfinityResolutionError(
                f"required marker {marker!r} missing from {label}"
            )
    for marker in forbidden_markers or []:
        if marker in text:
            raise InfinityResolutionError(
                f"forbidden GPU marker {marker!r} present in {label}"
            )


def create_combined_repo(
    destination: Path,
    synthetic_path: str,
    combined: bytes,
) -> str:
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True)
    run(["git", "init", "--quiet", "--initial-branch=main", str(destination)])
    run(["git", "config", "user.name", "TurboDecky Infinity Resolver"], cwd=destination)
    run(["git", "config", "user.email", "noreply@localhost"], cwd=destination)
    target = destination / synthetic_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(combined)
    run(["git", "add", "--", synthetic_path], cwd=destination)
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
    )
    run(
        ["git", "commit", "--quiet", "-m", "Combine Infinity CPU and RT series"],
        cwd=destination,
        env=environment,
    )
    return run(["git", "rev-parse", "HEAD"], cwd=destination, capture=True)


def resolve_infinity_source(
    config: dict[str, Any], kernel_series: str, workdir: Path
) -> tuple[Path, str, str, list[str], str]:
    if config.get("schema") != 1:
        raise InfinityResolutionError("unsupported Infinity source schema")
    repo = str(config["repo"])
    ref = str(config["ref"])
    upstream = workdir / "infinity-upstream"
    upstream_commit = snapshot_branch(repo, ref, upstream)
    paths = list_tree(upstream, upstream_commit)

    selected_paths: list[str] = []
    chunks: list[bytes] = []
    for index, patch_spec in enumerate(config.get("patches", []), start=1):
        pattern = str(patch_spec["glob"]).format(series=kernel_series)
        matches = sorted(path for path in paths if fnmatch.fnmatch(path, pattern))
        if len(matches) != 1:
            raise InfinityResolutionError(
                f"Infinity patch {index} expected one match for {pattern!r}, "
                f"found {len(matches)}: {matches}"
            )
        selected = matches[0]
        data = read_blob(upstream, upstream_commit, selected)
        validate_patch(
            data,
            f"Infinity patch {index}: {selected}",
            list(patch_spec.get("required_markers", [])),
            list(config.get("forbidden_markers", [])),
        )
        selected_paths.append(selected)
        chunks.append(data.rstrip() + b"\n")

    if len(chunks) != 3:
        raise InfinityResolutionError(
            f"Infinity CPU/RT policy requires exactly three patches, found {len(chunks)}"
        )
    combined = b"\n".join(chunks)
    validate_patch(
        combined,
        "combined Infinity v4.6-gpu CPU/RT series",
        list(config.get("combined_required_markers", [])),
        list(config.get("forbidden_markers", [])),
    )
    synthetic_path = str(config["synthetic_path"]).format(series=kernel_series)
    combined_repo = workdir / "infinity-combined"
    create_combined_repo(combined_repo, synthetic_path, combined)
    return combined_repo, upstream_commit, synthetic_path, selected_paths, hashlib.sha256(combined).hexdigest()


def write_summary(lock: dict[str, Any], path: Path | None) -> None:
    kernel = lock.get("kernel", {})
    lines = [
        f"Kernel: {kernel.get('version', 'unknown')} ({kernel.get('series', 'unknown')})",
        f"Resolved components: {len(lock.get('components', {}))}",
    ]
    for name, record in lock.get("components", {}).items():
        location = record.get("path") or record.get("url")
        version = record.get("project_version") or "unversioned"
        lines.append(
            f"{name}: {version}; {record.get('selection', 'unknown')}; "
            f"{location}; sha256={record.get('sha256', 'unknown')}"
        )
        if name == "infinity":
            lines.append(
                "infinity-policy: v4.6-gpu branch HEAD; patches 0001-0003 only; "
                "DRM/GPU patches 0004-0006 excluded"
            )
    summary = "\n".join(lines) + "\n"
    print(summary, end="")
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(summary, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kernel-version", required=True)
    parser.add_argument("--kernel-series", required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument(
        "--infinity-config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config/infinity-source.json",
    )
    parser.add_argument(
        "--base-resolver",
        type=Path,
        default=Path(__file__).with_name("resolve-patch-sources.py"),
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    infinity_config = json.loads(args.infinity_config.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("components"), dict) or "infinity" not in manifest["components"]:
        raise SystemExit("patch source manifest is missing the infinity component")

    try:
        with tempfile.TemporaryDirectory(prefix="turbodecky-infinity-") as temp:
            workdir = Path(temp)
            combined_repo, upstream_commit, synthetic_path, selected_paths, combined_sha = (
                resolve_infinity_source(infinity_config, args.kernel_series, workdir)
            )
            overridden = json.loads(json.dumps(manifest))
            overridden["components"]["infinity"] = {
                "kind": "git_patch",
                "repo": str(combined_repo),
                "ref": "main",
                "exact_globs": [synthetic_path],
                "fallback_globs": [],
                "require_exact_series": True,
                "output": str(infinity_config.get("output", "01-infinity.patch")),
                "required_markers": list(
                    infinity_config.get("combined_required_markers", [])
                ),
            }
            temporary_manifest = workdir / "patch-sources.json"
            temporary_manifest.write_text(
                json.dumps(overridden, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(args.base_resolver),
                "--manifest",
                str(temporary_manifest),
                "--output-dir",
                str(args.output_dir),
                "--kernel-version",
                args.kernel_version,
                "--kernel-series",
                args.kernel_series,
            ]
            run(command)

            lock_path = args.output_dir / "patch-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            record = lock["components"]["infinity"]
            record.update(
                {
                    "repo": str(infinity_config["repo"]),
                    "ref": str(infinity_config["ref"]),
                    "commit": upstream_commit,
                    "upstream_commit": upstream_commit,
                    "selected_paths": selected_paths,
                    "path": synthetic_path,
                    "selection": "exact-branch-head-cpu-rt-only",
                    "series_count": len(selected_paths),
                    "excluded_patches": ["0004", "0005", "0006"],
                    "source_policy": "v4.6-gpu CPU/RT only; no DRM/GPU scheduler patches",
                }
            )
            if record.get("sha256") != combined_sha:
                raise InfinityResolutionError(
                    "combined Infinity SHA-256 changed while delegating to base resolver"
                )
            lock_path.write_text(
                json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            write_summary(lock, args.summary)
    except InfinityResolutionError as exc:
        raise SystemExit(f"Infinity v4.6-gpu resolution failed: {exc}") from exc


if __name__ == "__main__":
    main()
