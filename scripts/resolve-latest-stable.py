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



GITHUB_MAINLINE_REFS = "https://api.github.com/repos/torvalds/linux/git/matching-refs/tags/"
GITHUB_MAINLINE_TAGS = "https://api.github.com/repos/torvalds/linux/git/tags/"


def _github_json(url: str):
    request = urllib.request.Request(
        url, headers={"User-Agent": "TurboDecky-GamerPc-mainline-check/1.0",
                      "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def reconcile_mainline_tag(release: dict) -> tuple[dict, list[dict]]:
    """A delayed kernel.org releases.json must not conceal a newer tagged mainline RC."""
    selected = str(release["version"])
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+|-rc\d+)?", selected)
    if not match:
        raise SystemExit(f"invalid kernel.org version for GitHub reconciliation: {selected}")
    major, minor = (int(n) for n in match.groups())
    prefixes = (f"v{major}.{minor}", f"v{major}.{minor + 1}", f"v{major + 1}.0")
    observed = []
    for prefix in prefixes:
        refs = _github_json(GITHUB_MAINLINE_REFS + prefix)
        if not isinstance(refs, list):
            raise SystemExit(f"invalid GitHub mainline tag listing: {prefix}")
        for candidate in refs:
            if not isinstance(candidate, dict):
                raise SystemExit(f"invalid GitHub mainline tag item for {prefix}")
            tag_ref = str(candidate.get("ref", ""))
            match_ref = re.fullmatch(r"refs/tags/v(\d+\.\d+(?:-rc\d+)?)", tag_ref)
            if match_ref is None or not tag_ref.startswith("refs/tags/" + prefix):
                continue
            obj = candidate.get("object")
            if (not isinstance(obj, dict) or obj.get("type") not in {"tag", "commit"} or
                    not re.fullmatch(r"[0-9a-f]{40}", str(obj.get("sha", "")))):
                raise SystemExit(f"invalid GitHub mainline tag SHA or type: {tag_ref}")
            observed.append({"version": match_ref.group(1), "ref": tag_ref,
                             "type": obj["type"], "sha": obj["sha"]})
    newer = [tag for tag in observed if version_key(tag["version"]) > version_key(selected)]
    if not newer:
        return release, observed
    chosen = max(newer, key=lambda tag: version_key(tag["version"]))
    commit = chosen["sha"]
    date = ""
    if chosen["type"] == "tag":
        tagged = _github_json(GITHUB_MAINLINE_TAGS + chosen["sha"])
        obj = tagged.get("object", {}) if isinstance(tagged, dict) else {}
        if (not isinstance(tagged, dict) or tagged.get("tag") != "v" + chosen["version"]
                or obj.get("type") != "commit"
                or not re.fullmatch(r"[0-9a-f]{40}", str(obj.get("sha", "")))):
            raise SystemExit(f"unverifiable annotated Linux tag: {chosen['ref']}")
        commit = obj["sha"]
        tagger = tagged.get("tagger") or {}
        date = str(tagger.get("date", ""))[:10]
    version = chosen["version"]
    return {
        "version": version, "moniker": "mainline", "iseol": False,
        "source": f"https://github.com/torvalds/linux/archive/refs/tags/v{version}.tar.gz",
        "gitweb": f"https://github.com/torvalds/linux/tree/v{version}",
        "released": {"isodate": date}, "_github_commit": commit,
        "_github_ref_sha": chosen["sha"], "_github_tag_ref": chosen["ref"],
    }, observed


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
    release, github_refs = reconcile_mainline_tag(select_latest_release(payload))
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
        "KERNEL_UPSTREAM_COMMIT": str(release.get("_github_commit") or ""),
        "KERNEL_UPSTREAM_TAG_SHA": str(release.get("_github_ref_sha") or ""),
    }

    args.log_dir.mkdir(parents=True, exist_ok=True)
    (args.log_dir / "kernel.org-releases.json").write_bytes(raw)
    (args.log_dir / "torvalds-linux-tag-reconciliation.json").write_text(
        json.dumps({"refs": github_refs, "selected": release["version"],
                    "tag_ref": release.get("_github_tag_ref"),
                    "tag_sha": release.get("_github_ref_sha"),
                    "commit_sha": release.get("_github_commit")}, indent=2) + "\n",
        encoding="utf-8",
    )
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
