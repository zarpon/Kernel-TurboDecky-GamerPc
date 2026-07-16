#!/usr/bin/env python3
"""Resolve the current stable Linux release for TurboDecky GamerPc."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

RELEASES_URL = "https://www.kernel.org/releases.json"
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def append_key_value(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    args = parser.parse_args()

    request = urllib.request.Request(
        RELEASES_URL,
        headers={"User-Agent": "TurboDecky-GamerPc-stable-resolver/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()

    payload = json.loads(raw)
    version = str(payload.get("latest_stable", {}).get("version", ""))
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"kernel.org returned an invalid latest_stable version: {version!r}")

    matching = [
        release
        for release in payload.get("releases", [])
        if release.get("moniker") == "stable"
        and release.get("version") == version
        and not release.get("iseol", False)
    ]
    if len(matching) != 1:
        raise SystemExit(
            f"expected exactly one non-EOL stable record for {version}, found {len(matching)}"
        )

    release = matching[0]
    series = ".".join(version.split(".")[:2])
    release_name = f"linux.{version}.turbodecky.release"
    values = {
        "KERNEL_VERSION": version,
        "KERNEL_SERIES": series,
        "KERNEL_TAG": f"v{version}",
        "KERNEL_RELEASE_NAME": release_name,
        "KERNEL_ARTIFACT_NAME": f"{release_name}-debs",
        "KERNEL_DEB_VERSION": f"{version}-1turbodecky1",
        "KERNEL_SOURCE_URL": str(release.get("source") or ""),
        "KERNEL_GITWEB_URL": str(release.get("gitweb") or ""),
        "KERNEL_RELEASE_DATE": str(release.get("released", {}).get("isodate") or ""),
    }

    args.log_dir.mkdir(parents=True, exist_ok=True)
    (args.log_dir / "kernel.org-releases.json").write_bytes(raw)
    (args.log_dir / "latest-stable-kernel.txt").write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )

    append_key_value(args.github_env, values)
    append_key_value(
        args.github_output,
        {
            "version": version,
            "series": series,
            "tag": values["KERNEL_TAG"],
            "release_name": release_name,
            "artifact_name": values["KERNEL_ARTIFACT_NAME"],
        },
    )

    print(f"Latest stable Linux: {version}")
    print(f"Kernel identity: {release_name}")
    print(f"Source: {values['KERNEL_SOURCE_URL']}")


if __name__ == "__main__":
    main()
