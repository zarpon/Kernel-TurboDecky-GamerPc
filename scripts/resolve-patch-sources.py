#!/usr/bin/env python3
"""Resolve the newest compatible patch sources for the selected stable kernel.

Each build snapshots the configured upstream branches, selects the best patch for
KERNEL_VERSION/KERNEL_SERIES, materializes immutable bytes locally, and writes a
lock file containing the exact commit, path and SHA-256 used by the build.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PATCH_PREFIXES = (
    b"From ",
    b"From:",
    b"diff --git ",
    b"--- a/",
    b"--- /dev/null",
)
USER_AGENT = "TurboDecky-GamerPc-Patch-Resolver/2.0"


class ResolverError(RuntimeError):
    pass


@dataclass(frozen=True)
class KernelVersion:
    text: str
    parts: tuple[int, ...]

    @classmethod
    def parse(cls, value: str) -> "KernelVersion":
        match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", value.strip())
        if not match:
            raise ResolverError(f"invalid kernel version: {value!r}")
        parts = tuple(int(item) for item in match.groups() if item is not None)
        return cls(value.strip(), parts)

    @property
    def series(self) -> tuple[int, int]:
        return self.parts[0], self.parts[1]


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        detail = ""
        if capture:
            detail = f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        raise ResolverError(f"command failed ({result.returncode}): {' '.join(command)}{detail}")
    return result.stdout.strip() if capture else ""


def safe_name(repo: str, ref: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{repo}-{ref}").strip("-")
    return value[-120:]


def snapshot_repo(repo: str, ref: str, destination: Path) -> str:
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "--quiet", str(destination)])
    run(["git", "-C", str(destination), "remote", "add", "origin", repo])
    run(["git", "-C", str(destination), "config", "remote.origin.promisor", "true"])
    run(["git", "-C", str(destination), "config", "remote.origin.partialclonefilter", "blob:none"])
    command = [
        "git", "-C", str(destination), "fetch", "--no-tags", "--depth=1",
        "--filter=blob:none", "origin", ref,
    ]
    try:
        run(command)
    except ResolverError:
        run(["git", "-C", str(destination), "fetch", "--no-tags", "--depth=1", "origin", ref])
    commit = run(["git", "-C", str(destination), "rev-parse", "FETCH_HEAD"], capture=True)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ResolverError(f"invalid resolved commit for {repo}@{ref}: {commit}")
    run([
        "git", "-C", str(destination), "update-ref",
        "refs/heads/turbodecky-snapshot", commit,
    ])
    return commit


def list_tree(repo_dir: Path, commit: str) -> list[str]:
    output = run(
        ["git", "-C", str(repo_dir), "ls-tree", "-r", "--name-only", commit],
        capture=True,
    )
    return [line for line in output.splitlines() if line]


def read_git_blob(
    repo_dir: Path, commit: str, path: str, *, max_symlinks: int = 8
) -> tuple[bytes, str]:
    """Read a tree path and safely follow internal patch indirections."""
    current = path
    visited: set[str] = set()
    for _ in range(max_symlinks + 1):
        if current in visited:
            raise ResolverError(f"patch indirection loop while resolving {path} at {current}")
        visited.add(current)
        listing = run(
            ["git", "-C", str(repo_dir), "ls-tree", commit, "--", current],
            capture=True,
        )
        if not listing:
            raise ResolverError(f"tree path {current} is missing from {commit}")
        first = listing.splitlines()[0]
        metadata, _, listed_path = first.partition("\t")
        fields = metadata.split()
        if len(fields) < 3 or listed_path != current:
            raise ResolverError(f"unexpected ls-tree response for {current}: {first!r}")
        mode, obj_type = fields[0], fields[1]
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "show", f"{commit}:{current}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise ResolverError(
                f"unable to read {current} from {commit}: "
                f"{result.stderr.decode(errors='replace')}"
            )
        data = result.stdout
        if obj_type != "blob":
            raise ResolverError(f"tree path {current} is not a blob: {obj_type}")

        target: str | None = None
        if mode == "120000":
            target = data.decode("utf-8", errors="strict").strip()
        elif len(data) <= 4096:
            candidate = data.decode("utf-8", errors="replace").strip()
            if (
                candidate
                and "\n" not in candidate
                and not candidate.startswith(("/", "From ", "diff --git "))
                and candidate.lower().endswith((".patch", ".diff"))
            ):
                target = candidate

        if target is None:
            return data, current
        if target.startswith("/"):
            raise ResolverError(f"unsafe Git patch indirection {current} -> {target!r}")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(current), target))
        if resolved == ".." or resolved.startswith("../"):
            raise ResolverError(f"Git patch indirection escapes repository: {current} -> {target}")
        current = resolved
    raise ResolverError(f"too many Git patch indirections while resolving {path}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_patch(data: bytes, component: str, markers: list[str]) -> None:
    if not data:
        raise ResolverError(f"empty patch selected for {component}")
    lines = data.splitlines()
    if not any(line.startswith(PATCH_PREFIXES) for line in lines):
        preview = data[:160].decode("utf-8", errors="replace")
        raise ResolverError(
            f"selected source for {component} is not a unified/email patch; preview={preview!r}"
        )
    text = data.decode("utf-8", errors="replace")
    for marker in markers:
        if marker not in text:
            raise ResolverError(f"required marker {marker!r} missing from {component}")


def extract_kernel_target(path: str) -> KernelVersion | None:
    candidates: list[KernelVersion] = []
    for match in re.finditer(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?(?:-rc\d+)?", path):
        major = int(match.group(1))
        if major < 5:
            continue
        version = ".".join(item for item in match.groups() if item is not None)
        candidates.append(KernelVersion.parse(version))
    return candidates[0] if candidates else None


def version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    pieces: list[int] = []
    for token in re.findall(r"\d+|r\d+", value.lower()):
        pieces.append(int(token[1:] if token.startswith("r") else token))
    return tuple(pieces)


def project_version(path: str, pattern: str | None) -> str | None:
    if not pattern:
        return None
    match = re.search(pattern, path, flags=re.IGNORECASE)
    return match.group(1) if match else None


def compatibility_score(target: KernelVersion | None, kernel: KernelVersion) -> tuple[int, tuple[int, ...]]:
    if target is None:
        return 4, ()
    if target.parts == kernel.parts:
        return 6, target.parts
    if target.series == kernel.series:
        return 5, target.parts
    if target.series < kernel.series:
        return 3, target.parts
    return 0, target.parts


def candidate_score(path: str, kernel: KernelVersion, version_pattern: str | None) -> tuple[Any, ...]:
    target = extract_kernel_target(path)
    compat_rank, target_parts = compatibility_score(target, kernel)
    channel_rank = 2 if "/stable/" in f"/{path}" else 1 if "/testing/" in f"/{path}" else 0
    version = project_version(path, version_pattern)
    return compat_rank, target_parts, version_key(version), channel_rank, path


def match_paths(paths: list[str], patterns: list[str], values: dict[str, str]) -> list[str]:
    selected: set[str] = set()
    for template in patterns:
        pattern = template.format(**values)
        selected.update(path for path in paths if fnmatch.fnmatch(path, pattern))
    return sorted(selected)


def fetch_url(url: str, attempts: int = 4) -> bytes:
    curl = shutil.which("curl")
    if curl:
        result = subprocess.run(
            [
                curl, "--fail", "--location", "--retry", str(attempts),
                "--retry-all-errors", "--retry-delay", "3",
                "--connect-timeout", "30", "--max-time", "600",
                "--user-agent", USER_AGENT, "--silent", "--show-error", url,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
        curl_error = result.stderr.decode(errors="replace").strip()
    else:
        curl_error = "curl is unavailable"

    last_error: Exception | None = None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if data:
                return data
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(attempt * 2)
    raise ResolverError(
        f"unable to fetch {url}: curl={curl_error}; urllib={last_error}"
    )


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)



def load_local_fallback(
    spec: dict[str, Any],
    manifest_root: Path | None,
    component: str,
    kernel: KernelVersion,
) -> tuple[bytes, dict[str, Any]] | None:
    patch_value = spec.get("local_fallback_patch")
    metadata_value = spec.get("local_fallback_metadata")
    if not patch_value or not metadata_value:
        return None
    if manifest_root is None:
        raise ResolverError(f"local fallback root is unavailable for {component}")

    patch_path = (manifest_root / str(patch_value)).resolve()
    metadata_path = (manifest_root / str(metadata_value)).resolve()
    try:
        data = patch_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResolverError(f"unable to read local fallback for {component}: {exc}") from exc

    if metadata.get("schema") != 1:
        raise ResolverError(f"unsupported local fallback metadata for {component}")
    validate_patch(data, component, list(spec.get("required_markers", [])))
    actual_sha256 = sha256(data)
    if metadata.get("sha256") != actual_sha256:
        raise ResolverError(
            f"local fallback SHA-256 mismatch for {component}: "
            f"{actual_sha256} != {metadata.get('sha256')}"
        )
    if metadata.get("size") != len(data):
        raise ResolverError(
            f"local fallback size mismatch for {component}: "
            f"{len(data)} != {metadata.get('size')}"
        )

    selected = str(metadata.get("selected_path", ""))
    resolved_path = str(metadata.get("path", selected))
    repo = str(metadata.get("repo", ""))
    ref = str(metadata.get("ref", ""))
    commit = str(metadata.get("commit", ""))
    if not selected or not resolved_path or not repo or not ref:
        raise ResolverError(f"local fallback metadata is incomplete for {component}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ResolverError(f"local fallback commit is invalid for {component}: {commit!r}")

    target = extract_kernel_target(selected)
    if compatibility_score(target, kernel)[0] <= 0:
        raise ResolverError(
            f"local fallback for {component} targets "
            f"{target.text if target else 'unknown'} and is incompatible with {kernel.text}"
        )
    if spec.get("require_exact_series", False) and target and target.series != kernel.series:
        raise ResolverError(
            f"local fallback for {component} targets {target.text}, not {kernel.text}"
        )

    detected_version = project_version(selected, spec.get("project_version_regex"))
    recorded_version = metadata.get("project_version")
    if detected_version and recorded_version and detected_version != recorded_version:
        raise ResolverError(
            f"local fallback version mismatch for {component}: "
            f"{detected_version} != {recorded_version}"
        )

    return data, {
        "repo": repo,
        "ref": ref,
        "commit": commit,
        "selected_path": selected,
        "path": resolved_path,
        "selection": "local-fallback",
        "kernel_target": target.text if target else metadata.get("kernel_target"),
        "project_version": recorded_version or detected_version,
        "fallback_metadata": str(metadata_path),
    }


def resolve(
    manifest: dict[str, Any],
    output_dir: Path,
    kernel: KernelVersion,
    series_text: str,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    temp_root = Path(tempfile.mkdtemp(prefix="patch-resolver-", dir=output_dir.parent))
    repos_dir = temp_root / "repos"
    files_dir = temp_root / "files"
    repos_dir.mkdir(parents=True)
    files_dir.mkdir(parents=True)

    repo_cache: dict[tuple[str, str], tuple[Path, str, list[str]]] = {}
    lock: dict[str, Any] = {
        "schema": 1,
        "kernel": {"version": kernel.text, "series": series_text},
        "components": {},
    }

    try:
        for component, raw_spec in manifest["components"].items():
            spec = dict(raw_spec)
            kind = spec["kind"]
            output_name = spec["output"]
            output_path = files_dir / output_name
            record: dict[str, Any] = {"kind": kind, "output": f"files/{output_name}"}

            if kind in {"git_patch", "git_file"}:
                repo = spec["repo"]
                refs = [spec.get("ref", "main"), *spec.get("fallback_refs", [])]
                values = {"kernel_version": kernel.text, "series": series_text}
                options: list[tuple[tuple[Any, ...], Path, str, str, str, str]] = []
                ref_errors: list[str] = []

                for ref_index, ref in enumerate(dict.fromkeys(refs)):
                    key = (repo, ref)
                    try:
                        if key not in repo_cache:
                            repo_path = repos_dir / safe_name(repo, ref)
                            commit = snapshot_repo(repo, ref, repo_path)
                            paths = list_tree(repo_path, commit)
                            repo_cache[key] = (repo_path, commit, paths)
                        repo_path, commit, paths = repo_cache[key]
                    except ResolverError as exc:
                        ref_errors.append(f"{ref}: {exc}")
                        continue

                    exact = match_paths(paths, spec.get("exact_globs", []), values)
                    fallback = [] if spec.get("require_exact_series", False) else match_paths(
                        paths, spec.get("fallback_globs", []), values
                    )
                    for mode, candidates in (("exact", exact), ("fallback", fallback)):
                        for candidate_path in candidates:
                            target = extract_kernel_target(candidate_path)
                            if compatibility_score(target, kernel)[0] <= 0:
                                continue
                            try:
                                candidate_data, resolved_path = read_git_blob(
                                    repo_path, commit, candidate_path
                                )
                                if kind == "git_patch":
                                    validate_patch(
                                        candidate_data,
                                        component,
                                        list(spec.get("required_markers", [])),
                                    )
                            except ResolverError as exc:
                                ref_errors.append(f"{ref}:{candidate_path}: {exc}")
                                continue
                            base_score = candidate_score(
                                candidate_path, kernel, spec.get("project_version_regex")
                            )
                            score = (*base_score[:-1], -ref_index, candidate_path)
                            options.append(
                                (
                                    score,
                                    repo_path,
                                    commit,
                                    ref,
                                    mode,
                                    candidate_path,
                                    resolved_path,
                                )
                            )

                if not options:
                    fallback = load_local_fallback(
                        spec, manifest_root, component, kernel
                    )
                    if fallback is None:
                        detail = " | ".join(ref_errors) if ref_errors else "no matching paths"
                        expectation = "exact " if spec.get("require_exact_series", False) else ""
                        raise ResolverError(
                            f"no {expectation}compatible path found for {component} and Linux "
                            f"{series_text}: {detail}"
                        )
                    data, fallback_record = fallback
                    write_bytes(output_path, data)
                    record.update(fallback_record)
                else:
                    _, repo_path, commit, ref, mode, selected, resolved_path = max(
                        options, key=lambda item: item[0]
                    )
                    target = extract_kernel_target(selected)
                    if spec.get("require_exact_series", False) and target and target.series != kernel.series:
                        raise ResolverError(
                            f"{component} selected incompatible kernel target {target.text} "
                            f"for Linux {series_text}"
                        )
                    data, confirmed_path = read_git_blob(repo_path, commit, selected)
                    if confirmed_path != resolved_path:
                        raise ResolverError(
                            f"resolved path changed during selection for {component}: "
                            f"{resolved_path} != {confirmed_path}"
                        )
                    if kind == "git_patch":
                        validate_patch(data, component, list(spec.get("required_markers", [])))
                    approved_sha256 = spec.get("approved_sha256")
                    actual_sha256 = sha256(data)
                    if approved_sha256 and actual_sha256 != approved_sha256:
                        raise ResolverError(
                            f"{component} selected current official source with SHA-256 "
                            f"{actual_sha256}, but the reviewed local port requires "
                            f"{approved_sha256}; refresh and validate the port"
                        )
                    write_bytes(output_path, data)
                    record.update(
                        {
                            "repo": repo,
                            "ref": ref,
                            "commit": commit,
                            "selected_path": selected,
                            "path": resolved_path,
                            "selection": mode if ref == refs[0] else f"{mode}-fallback-ref",
                            "repo_dir": f"repos/{repo_path.name}",
                            "kernel_target": target.text if target else None,
                            "project_version": project_version(
                                selected, spec.get("project_version_regex")
                            ),
                        }
                    )
            elif kind == "http_patch":
                values = {"kernel_version": kernel.text, "series": series_text}
                errors: list[str] = []
                data: bytes | None = None
                selected_url: str | None = None
                for template in spec.get("urls", []):
                    url = template.format(**values)
                    try:
                        candidate = fetch_url(url)
                        validate_patch(candidate, component, list(spec.get("required_markers", [])))
                        approved_sha256 = spec.get("approved_sha256")
                        actual_sha256 = sha256(candidate)
                        if approved_sha256 and actual_sha256 != approved_sha256:
                            raise ResolverError(
                                f"{component} selected current official source with SHA-256 "
                                f"{actual_sha256}, but the reviewed local port requires "
                                f"{approved_sha256}; refresh and validate the port"
                            )
                        data = candidate
                        selected_url = url
                        break
                    except ResolverError as exc:
                        errors.append(str(exc))
                if data is None or selected_url is None:
                    raise ResolverError(
                        f"no usable URL for {component}: " + " | ".join(errors)
                    )
                write_bytes(output_path, data)
                record.update({"url": selected_url, "selection": "first-valid"})
            else:
                raise ResolverError(f"unknown component kind {kind!r} for {component}")

            record["sha256"] = sha256(output_path.read_bytes())
            record["size"] = output_path.stat().st_size
            lock["components"][component] = record

        lock_path = temp_root / "patch-lock.json"
        lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        os.replace(temp_root, output_dir)
        return lock
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kernel-version", required=True)
    parser.add_argument("--kernel-series", required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    kernel = KernelVersion.parse(args.kernel_version)
    expected_series = f"{kernel.series[0]}.{kernel.series[1]}"
    if args.kernel_series != expected_series:
        raise SystemExit(
            f"kernel series mismatch: {args.kernel_series} != {expected_series}"
        )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or not isinstance(manifest.get("components"), dict):
        raise SystemExit("unsupported patch source manifest")

    try:
        lock = resolve(
    manifest,
    args.output_dir.resolve(),
    kernel,
    args.kernel_series,
    manifest_root=args.manifest.resolve().parent,
)
    except ResolverError as exc:
        raise SystemExit(f"patch source resolution failed: {exc}") from exc

    lines = [
        f"Kernel: {args.kernel_version} ({args.kernel_series})",
        f"Resolved components: {len(lock['components'])}",
    ]
    for name, record in lock["components"].items():
        location = record.get("path") or record.get("url")
        version = record.get("project_version") or "unversioned"
        lines.append(
            f"{name}: {version}; {record['selection']}; {location}; sha256={record['sha256']}"
        )
    summary = "\n".join(lines) + "\n"
    print(summary, end="")
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary, encoding="utf-8")


if __name__ == "__main__":
    main()
