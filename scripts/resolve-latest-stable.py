#!/usr/bin/env python3
"""Resolve the newest upstream Linux release, including release candidates."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

RELEASES_URL = "https://www.kernel.org/releases.json"
# Accept final releases (X.Y / X.Y.Z) and release candidates (X.Y-rcN).
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+(?:(?:\.[0-9]+)|(?:-rc[0-9]+))?$")
DEBIAN_KERNEL_RELEASE_RE = re.compile(r"^[0-9][A-Za-z0-9.+~_-]*$")


def append_key_value(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def version_key(version: str) -> tuple[int, int, int, int]:
    """Sort upstream versions so a newer mainline/RC outranks an older stable series."""
    rc = re.fullmatch(r"([0-9]+)\.([0-9]+)-rc([0-9]+)", version)
    if rc:
        return int(rc.group(1)), int(rc.group(2)), 1, int(rc.group(3))
    final = re.fullmatch(r"([0-9]+)\.([0-9]+)(?:\.([0-9]+))?", version)
    if not final:
        raise ValueError(version)
    # A final X.Y outranks X.Y-rcN; stable X.Y.Z belongs to the final X.Y line.
    patch = int(final.group(3) or 0)
    return int(final.group(1)), int(final.group(2)), 2, patch


def select_latest_release(payload: dict) -> dict:
    candidates = []
    for release in payload.get("releases", []):
        version = str(release.get("version", "")).strip()
        if (
            VERSION_RE.fullmatch(version)
            and not release.get("iseol", False)
            and release.get("source")
            and str(release.get("moniker", "")) in {"mainline", "stable"}
        ):
            candidates.append(release)
    if not candidates:
        raise SystemExit("kernel.org returned no downloadable non-EOL mainline/stable release")

    # Preserve the previous source-quality preference when kernel.org exposes
    # duplicate records for exactly the same version during a transition.
    # Version always wins first; stable only breaks an equal-version tie.
    moniker_priority = {"mainline": 0, "stable": 1}
    return max(
        candidates,
        key=lambda release: (
            version_key(str(release["version"])),
            moniker_priority.get(str(release.get("moniker", "")), -1),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-env", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    args = parser.parse_args()

    request = urllib.request.Request(
        RELEASES_URL,
        headers={"User-Agent": "TurboDecky-GamerPc-latest-upstream-resolver/2.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()

    payload = json.loads(raw)
    release = select_latest_release(payload)
    version = str(release["version"]).strip()
    series = ".".join(version.split("-")[0].split(".")[:2])
    kernel_release = f"{version}.turbodecky"
    publish_name = f"linux.{kernel_release}"
    if not DEBIAN_KERNEL_RELEASE_RE.fullmatch(kernel_release):
        raise SystemExit(f"invalid Debian-compatible kernel release: {kernel_release!r}")

    values = {
        "KERNEL_VERSION": version,
        "KERNEL_SERIES": series,
        "KERNEL_TAG": f"v{version}",
        "KERNEL_RELEASE_NAME": kernel_release,
        "KERNEL_PUBLISH_NAME": publish_name,
        "KERNEL_ARTIFACT_NAME": f"{publish_name}-debs",
        "KERNEL_DEB_VERSION": f"{version}-1turbodecky1",
        "KERNEL_SOURCE_URL": str(release.get("source") or ""),
        "KERNEL_GITWEB_URL": str(release.get("gitweb") or ""),
        "KERNEL_RELEASE_DATE": str(release.get("released", {}).get("isodate") or ""),
    }

    args.log_dir.mkdir(parents=True, exist_ok=True)
    (args.log_dir / "kernel.org-releases.json").write_bytes(raw)
    (args.log_dir / "latest-upstream-kernel.txt").write_text(
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
            "kernel_release": kernel_release,
            "release_name": publish_name,
            "publish_name": publish_name,
            "artifact_name": values["KERNEL_ARTIFACT_NAME"],
        },
    )

    print(f"Latest upstream Linux (RCs included): {version}")
    print(f"Kernel identity: {kernel_release}")
    print(f"Publish identity: {publish_name}")
    print(f"Source: {values['KERNEL_SOURCE_URL']}")


if __name__ == "__main__":
    main()
