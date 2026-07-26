#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


class FallbackError(RuntimeError):
    pass


def validate(
    patch_path: Path,
    metadata_path: Path,
    *,
    expected_version: str | None = None,
    expected_commit: str | None = None,
    expected_path: str | None = None,
) -> dict[str, Any]:
    data = patch_path.read_bytes()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema") != 1:
        raise FallbackError("unsupported Marie fallback metadata schema")

    text = data.decode("utf-8", errors="replace")
    for marker in ("LRU_MARIE", "lru_marie"):
        if marker not in text:
            raise FallbackError(f"Marie fallback marker is missing: {marker}")

    digest = hashlib.sha256(data).hexdigest()
    if metadata.get("sha256") != digest:
        raise FallbackError(
            f"Marie fallback SHA-256 mismatch: {digest} != {metadata.get('sha256')}"
        )
    if metadata.get("size") != len(data):
        raise FallbackError(
            f"Marie fallback size mismatch: {len(data)} != {metadata.get('size')}"
        )

    commit = str(metadata.get("commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise FallbackError(f"invalid Marie fallback commit: {commit!r}")

    version = str(metadata.get("project_version", ""))
    selected_path = str(metadata.get("selected_path", ""))
    if not version or not selected_path:
        raise FallbackError("Marie fallback version or path is missing")
    if version not in selected_path or version not in text:
        raise FallbackError("Marie fallback version is inconsistent with patch content")

    if expected_version and version != expected_version:
        raise FallbackError(f"Marie fallback version {version} != {expected_version}")
    if expected_commit and commit != expected_commit:
        raise FallbackError(f"Marie fallback commit {commit} != {expected_commit}")
    if expected_path and selected_path != expected_path:
        raise FallbackError(f"Marie fallback path {selected_path} != {expected_path}")

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-path")
    args = parser.parse_args()

    try:
        metadata = validate(
            args.patch,
            args.metadata,
            expected_version=args.expected_version,
            expected_commit=args.expected_commit,
            expected_path=args.expected_path,
        )
    except (OSError, json.JSONDecodeError, FallbackError) as exc:
        raise SystemExit(f"Marie fallback validation failed: {exc}") from exc

    print(
        f"Marie fallback {metadata['project_version']} validated: "
        f"{metadata['sha256']}"
    )


if __name__ == "__main__":
    main()
