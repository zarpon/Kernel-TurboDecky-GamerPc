#!/usr/bin/env python3
"""Resolve all six Infinity v4.6-gpu patches while reusing the proven resolver."""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

LIB = Path(__file__).with_name("resolve-infinity-v46-cpu-series-lib.py")
spec = importlib.util.spec_from_file_location("turbodecky_infinity_legacy", LIB)
if spec is None or spec.loader is None:
    raise SystemExit(f"unable to load resolver library: {LIB}")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


def normalize_record(record: dict[str, Any], selected_paths: list[str] | None = None) -> None:
    if selected_paths is not None:
        record["selected_paths"] = selected_paths
    paths = list(record.get("selected_paths", []))
    record.update({
        "selection": "exact-branch-head-full-series",
        "series_count": len(paths),
        "excluded_patches": [],
        "source_policy": "v4.6-gpu full CPU/RT/DRM/GPU series; patches 0001-0006",
    })


def resolve_full(config: dict[str, Any], kernel_series: str, workdir: Path):
    if config.get("schema") != 1:
        raise legacy.InfinityResolutionError("unsupported Infinity source schema")
    specs = list(config.get("patches", []))
    if len(specs) != 6:
        raise legacy.InfinityResolutionError(
            f"Infinity full-series policy requires exactly six patches, found {len(specs)}"
        )
    upstream = workdir / "infinity-upstream"
    upstream_commit = legacy.snapshot_branch(str(config["repo"]), str(config["ref"]), upstream)
    tree_paths = legacy.list_tree(upstream, upstream_commit)
    selected_paths: list[str] = []
    chunks: list[bytes] = []
    import fnmatch, hashlib
    for index, patch_spec in enumerate(specs, start=1):
        pattern = str(patch_spec["glob"]).format(series=kernel_series)
        matches = sorted(path for path in tree_paths if fnmatch.fnmatch(path, pattern))
        if len(matches) != 1:
            raise legacy.InfinityResolutionError(
                f"Infinity patch {index} expected one match for {pattern!r}, found {len(matches)}: {matches}"
            )
        selected = matches[0]
        data = legacy.read_blob(upstream, upstream_commit, selected)
        legacy.validate_patch(data, f"Infinity patch {index}: {selected}", list(patch_spec.get("required_markers", [])), [])
        selected_paths.append(selected)
        chunks.append(data.rstrip() + b"\n")
    combined = b"\n".join(chunks)
    legacy.validate_patch(combined, "combined Infinity v4.6-gpu full series", list(config.get("combined_required_markers", [])), [])
    synthetic_path = str(config["synthetic_path"]).format(series=kernel_series)
    combined_repo = workdir / "infinity-combined"
    legacy.create_combined_repo(combined_repo, synthetic_path, combined)
    return combined_repo, upstream_commit, synthetic_path, selected_paths, hashlib.sha256(combined).hexdigest()


_original_write_summary = legacy.write_summary
def write_summary_full(lock: dict[str, Any], path: Path | None) -> None:
    record = lock.get("components", {}).get("infinity")
    if isinstance(record, dict):
        normalize_record(record)
    _original_write_summary(lock, path)

legacy.resolve_infinity_source = resolve_full
legacy.write_summary = write_summary_full
legacy.main()

# The legacy main writes patch-lock.json before invoking write_summary(). Normalize
# the persisted record as a final fail-closed step.
args = sys.argv[1:]
try:
    out = Path(args[args.index("--output-dir") + 1])
except (ValueError, IndexError):
    raise SystemExit("--output-dir is required")
lock_path = out / "patch-lock.json"
lock = json.loads(lock_path.read_text(encoding="utf-8"))
record = lock["components"]["infinity"]
normalize_record(record)
if record["series_count"] != 6:
    raise SystemExit(f"Infinity full-series lock expected six patches, found {record['series_count']}")
lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
