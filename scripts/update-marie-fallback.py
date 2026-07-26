#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "scripts/resolve-patch-sources.py"
SPEC = importlib.util.spec_from_file_location("turbodecky_patch_resolver", RESOLVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise SystemExit(f"unable to load resolver: {RESOLVER_PATH}")
resolver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = resolver
SPEC.loader.exec_module(resolver)


def replace_assignment(text: str, variable: str, replacement: str) -> str:
    pattern = re.compile(rf"^{re.escape(variable)}=.*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(f"{variable}: expected one assignment, found {len(matches)}")
    return pattern.sub(replacement, text, count=1)


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return True


def build_metadata(
    record: dict[str, Any], kernel_version: str, kernel_series: str
) -> dict[str, Any]:
    return {
        "schema": 1,
        "repo": record["repo"],
        "ref": record["ref"],
        "commit": record["commit"],
        "selected_path": record["selected_path"],
        "path": record["path"],
        "selection": record["selection"],
        "kernel_version": kernel_version,
        "kernel_series": kernel_series,
        "kernel_target": record.get("kernel_target"),
        "project_version": record["project_version"],
        "sha256": record["sha256"],
        "size": record["size"],
    }


def rewrite_core_defaults(path: Path, record: dict[str, Any]) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    text = replace_assignment(
        text, "MARIE_COMMIT", f'MARIE_COMMIT="{record["commit"]}"'
    )
    text = replace_assignment(
        text, "MARIE_PATCH_PATH", f'MARIE_PATCH_PATH="{record["path"]}"'
    )
    text = replace_assignment(
        text, "MARIE_PATCH", 'MARIE_PATCH="$PATCHDIR/02-lru-marie.patch"'
    )
    version = str(record["project_version"])
    text = replace_assignment(
        text,
        "PATCH_MARIE_VERSION",
        f'PATCH_MARIE_VERSION="${{PATCH_MARIE_VERSION:-{version}}}"',
    )
    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "config/patch-sources.json"
    )
    parser.add_argument("--kernel-version", required=True)
    parser.add_argument("--kernel-series", required=True)
    parser.add_argument(
        "--patch-output",
        type=Path,
        default=ROOT / "patches/fallback/lru_marie.patch",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=ROOT / "patches/fallback/lru_marie.json",
    )
    parser.add_argument(
        "--core", type=Path, default=ROOT / "scripts/build-kernelnote-core.sh"
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marie = dict(manifest["components"]["marie"])
    marie.pop("local_fallback_patch", None)
    marie.pop("local_fallback_metadata", None)
    subset = {"schema": 1, "components": {"marie": marie}}
    kernel = resolver.KernelVersion.parse(args.kernel_version)

    with tempfile.TemporaryDirectory(prefix="marie-fallback-") as directory:
        output = Path(directory) / "resolved"
        lock = resolver.resolve(
            subset,
            output,
            kernel,
            args.kernel_series,
            manifest_root=manifest_path.parent,
        )
        record = lock["components"]["marie"]
        if record.get("selection") == "local-fallback":
            raise SystemExit(
                "upstream Marie resolution unexpectedly used the local fallback"
            )
        patch_data = (output / record["output"]).read_bytes()

    metadata = build_metadata(record, args.kernel_version, args.kernel_series)
    metadata_data = (
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    patch_changed = write_if_changed(args.patch_output, patch_data)
    metadata_changed = write_if_changed(args.metadata_output, metadata_data)
    core_changed = rewrite_core_defaults(args.core, record)

    print(
        f"Marie fallback {record['project_version']} synchronized; "
        f"patch_changed={patch_changed}; metadata_changed={metadata_changed}; "
        f"core_changed={core_changed}"
    )


if __name__ == "__main__":
    main()
