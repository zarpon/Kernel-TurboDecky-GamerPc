#!/usr/bin/env python3
"""Rewrite the generated build scripts to consume a build-time patch lock."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MARKER = "# Dynamic patch source lock"

REQUESTED = {
    "c23_libbpf": ("08-c23-libbpf.patch", "08-c23-libbpf"),
    "clear": ("09-clear.patch", "09-clear"),
    "fsync": ("10-fsync-futex-waitv.patch", "10-fsync"),
    "o3": ("11-o3.patch", "11-o3"),
    "bt_ssp": ("12-bt-ssp-key-size.patch", "12-bt-ssp"),
    "libbpf_uninitialized": ("13-libbpf-uninitialized.patch", "13-libbpf-uninitialized"),
    "cpu_optimizations": ("14-cpu-optimizations.patch", "14-cpu-optimizations"),
    "dkms_clang": ("15-dkms-clang.patch", "15-dkms-clang"),
    "clang_polly": ("16-clang-polly.patch", "16-clang-polly"),
    "firmware_name": ("17-firmware-name.patch", "17-firmware-name"),
    "minstrel_frac": ("18-minstrel-frac.patch", "18-minstrel-frac"),
    "minstrel_fluctuation": ("19-minstrel-fluctuation.patch", "19-minstrel-fluctuation"),
    "minstrel_downgrade": ("20-minstrel-downgrade.patch", "20-minstrel-downgrade"),
    "ath11k_remapped_ce": ("21-ath11k-remapped-ce.patch", "21-ath11k-remapped-ce"),
    "ath11k_disable_key": ("22-ath11k-disable-key.patch", "22-ath11k-disable-key"),
    "ath11k_upstream": ("23-ath11k-upstream.patch", "23-ath11k-upstream"),
}


class RewriteError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command, cwd=cwd, env=env, check=False, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RewriteError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


def materialize_locked_repositories(lock_path: Path, lock: dict[str, Any]) -> dict[str, Any]:
    """Replace promisor snapshots with tiny, fully self-contained Git repos."""
    root = lock_path.parent
    materialized_root = root / "materialized-repos"
    shutil.rmtree(materialized_root, ignore_errors=True)
    materialized_root.mkdir(parents=True, exist_ok=True)
    old_repo_dirs: set[Path] = set()

    for name, record in lock.get("components", {}).items():
        if record.get("kind") not in {"git_patch", "git_file"}:
            continue
        output = root / str(record["output"])
        if not output.is_file() or output.stat().st_size == 0:
            raise RewriteError(f"locked bytes are missing for {name}: {output}")
        path = str(record["path"])
        destination = materialized_root / re.sub(r"[^A-Za-z0-9._-]+", "-", name)
        destination.mkdir(parents=True)
        run(["git", "init", "--quiet", "--initial-branch=turbodecky-snapshot", str(destination)])
        run(["git", "config", "user.name", "TurboDecky Patch Resolver"], cwd=destination)
        run(["git", "config", "user.email", "noreply@localhost"], cwd=destination)
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output.read_bytes())
        run(["git", "add", "--", path], cwd=destination)
        environment = os.environ.copy()
        environment.update({
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        })
        run(["git", "commit", "--quiet", "-m", f"Snapshot {name}"], cwd=destination, env=environment)
        snapshot_commit = run(["git", "rev-parse", "HEAD"], cwd=destination)
        run(["git", "update-ref", "refs/heads/turbodecky-snapshot", snapshot_commit], cwd=destination)

        old_repo = record.get("repo_dir")
        if old_repo:
            old_repo_dirs.add((root / str(old_repo)).resolve())
        record.setdefault("upstream_commit", record.get("commit"))
        record["snapshot_commit"] = snapshot_commit
        record["commit"] = snapshot_commit
        record["repo_dir"] = str(destination.relative_to(root))

    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    materialized_resolved = materialized_root.resolve()
    root_resolved = root.resolve()
    for old_repo in old_repo_dirs:
        if old_repo == materialized_resolved or materialized_resolved in old_repo.parents:
            continue
        if root_resolved in old_repo.parents and old_repo.exists():
            shutil.rmtree(old_repo, ignore_errors=True)
    return lock


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RewriteError(f"{label}: expected one anchor, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def replace_assignment(text: str, variable: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(variable)}=.*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise RewriteError(f"{variable}: expected one assignment, found {len(matches)}")
    return pattern.sub(f'{variable}="{value}"', text, count=1)


def component(lock: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return lock["components"][name]
    except KeyError as exc:
        raise RewriteError(f"patch lock is missing component {name}") from exc


def repo_value(record: dict[str, Any]) -> str:
    return f'$RESOLVED_PATCH_ROOT/{record["repo_dir"]}'


def file_url(record: dict[str, Any]) -> str:
    return f'file://$RESOLVED_PATCH_ROOT/{record["output"]}'


def file_path(record: dict[str, Any]) -> str:
    return f'$RESOLVED_PATCH_ROOT/{record["output"]}'


def project_version(record: dict[str, Any], fallback: str) -> str:
    value = record.get("project_version")
    return str(value) if value else fallback


def patch_core(text: str, lock: dict[str, Any]) -> str:
    if MARKER in text:
        return text

    text = replace_once(
        text,
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n',
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
        f'{MARKER}\nRESOLVED_PATCH_ROOT="$ROOT/.resolved-patches"\n'
        ': "${KERNEL_VERSION:?latest stable version was not resolved}"\n'
        ': "${KERNEL_SERIES:?latest stable series was not resolved}"\n',
        "resolved patch root",
    )
    text = replace_once(
        text,
        'mkdir -p "$PATCHDIR" "$LOGDIR" "$ARTIFACTS"\n',
        'mkdir -p "$PATCHDIR" "$LOGDIR" "$ARTIFACTS"\n'
        'test -s "$RESOLVED_PATCH_ROOT/patch-lock.json"\n'
        'cp "$RESOLVED_PATCH_ROOT/patch-lock.json" "$LOGDIR/patch-lock.json"\n'
        'if [[ -s "$RESOLVED_PATCH_ROOT/resolution-summary.txt" ]]; then\n'
        '  cp "$RESOLVED_PATCH_ROOT/resolution-summary.txt" "$LOGDIR/patch-resolution-summary.txt"\n'
        'fi\n',
        "patch lock preservation",
    )

    text = replace_assignment(text, "LIQUORIX_CONFIG_URL", file_url(component(lock, "liquorix_config")))
    text = replace_assignment(text, "ADIOS_URL", file_url(component(lock, "adios")))

    for prefix, name in (("BORE", "bore"), ("MARIE", "marie"), ("REFLEX", "reflex")):
        record = component(lock, name)
        text = replace_assignment(text, f"{prefix}_REPO", repo_value(record))
        if f"{prefix}_COMMIT=" in text:
            text = replace_assignment(
                text, f"{prefix}_COMMIT", str(record.get("snapshot_commit", record["commit"]))
            )
        if f"{prefix}_PATCH_PATH=" in text:
            text = replace_assignment(text, f"{prefix}_PATCH_PATH", str(record["path"]))
        if prefix == "BORE" and "BORE_BRANCH=" in text:
            text = replace_assignment(text, "BORE_BRANCH", str(record.get("ref", "main")))

    bore_sched_ext = component(lock, "bore_sched_ext_coexistence")
    for suffix, value in (
        ("REPO", repo_value(bore_sched_ext)),
        ("COMMIT", str(bore_sched_ext.get("snapshot_commit", bore_sched_ext["commit"]))),
        ("PATCH_PATH", str(bore_sched_ext["path"])),
    ):
        variable = f"BORE_SCHED_EXT_{suffix}"
        if f"{variable}=" in text:
            text = replace_assignment(text, variable, value)

    versions = {
        "MARIE": project_version(component(lock, "marie"), "unknown"),
        "REFLEX": project_version(component(lock, "reflex"), "unknown"),
    }
    if "PATCH_MARIE_VERSION=" in text:
        text = replace_assignment(text, "PATCH_MARIE_VERSION", versions["MARIE"])
    else:
        marie_patch = re.compile(r'^(MARIE_PATCH=.*)$', re.MULTILINE)
        matches = list(marie_patch.finditer(text))
        if len(matches) != 1:
            raise RewriteError(
                f"PATCH_MARIE_VERSION: expected one MARIE_PATCH anchor, found {len(matches)}"
            )
        text = marie_patch.sub(
            rf'\1\nPATCH_MARIE_VERSION="{versions["MARIE"]}"',
            text,
            count=1,
        )
    if "PATCH_REFLEX_VERSION=" in text:
        text = replace_assignment(text, "PATCH_REFLEX_VERSION", versions["REFLEX"])
    else:
        anchor = f'PATCH_MARIE_VERSION="{versions["MARIE"]}"\n'
        text = replace_once(
            text,
            anchor,
            anchor + f'PATCH_REFLEX_VERSION="{versions["REFLEX"]}"\n',
            "dynamic REFLEX version",
        )

    replacements = {
        'grep -Fq \'Subject: [PATCH] linux7.1-rc5-lru_marie-0.7.7\' "$MARIE_PATCH"':
            'grep -Fq \'lru_marie\' "$MARIE_PATCH"',
        "grep -Fq '0.7.7' mm/lru_marie/version.h":
            '[[ "$PATCH_MARIE_VERSION" == "unknown" ]] || grep -Fq "$PATCH_MARIE_VERSION" mm/lru_marie/version.h',
        'grep -Fq \'Subject: [PATCH] linux7.1-reflex-v0.3.1\' "$REFLEX_PATCH"':
            'grep -Fq \'reflex\' "$REFLEX_PATCH"',
        "grep -Fq '#define CPUFREQ_REFLEX_VERSION  \"0.3.1\"' drivers/cpufreq/cpufreq_reflex.c":
            '[[ "$PATCH_REFLEX_VERSION" == "unknown" ]] || grep -Fq "$PATCH_REFLEX_VERSION" drivers/cpufreq/cpufreq_reflex.c',
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)

    for name, (output, prefix) in REQUESTED.items():
        component(lock, name)
        anchor = f'"$REQUESTED_SERIES_DIR/{output}" "{prefix}" \\\n'
        replacement = anchor + f'    "file://$RESOLVED_PATCH_ROOT/files/{output}" \\\n'
        text = replace_once(text, anchor, replacement, f"local candidate {name}")

    return text


def patch_wrapper(text: str, lock: dict[str, Any]) -> str:
    if "PATCH_ZRAM_IR_VERSION=" in text and "$RESOLVED_PATCH_ROOT/" in text:
        return text

    for prefix, name in (("ZRAM_IR", "zram_ir"), ("POC", "poc"), ("NAP", "nap"), ("VRAM_PATCH", "vram")):
        record = component(lock, name)
        repo_var = f"{prefix}_REPO"
        commit_var = f"{prefix}_COMMIT"
        path_var = f"{prefix}_PATCH_PATH"
        if repo_var in text:
            text = replace_assignment(text, repo_var, repo_value(record))
        if commit_var in text:
            text = replace_assignment(
                text, commit_var, str(record.get("snapshot_commit", record["commit"]))
            )
        if path_var in text:
            text = replace_assignment(text, path_var, str(record["path"]))

    for variable, name in (
        ("LZ4KDR_PATCH", "lz4kdr"),
        ("LZ4KDR_ZSWAP_PATCH", "lz4kdr_zswap"),
    ):
        if f"{variable}=" in text:
            text = replace_assignment(text, variable, file_path(component(lock, name)))

    versions = {
        "zram_ir": project_version(component(lock, "zram_ir"), "unknown"),
        "poc": project_version(component(lock, "poc"), "unknown"),
        "nap": project_version(component(lock, "nap"), "unknown"),
        "lz4kdr": project_version(component(lock, "lz4kdr"), "unknown"),
        "lz4kdr_zswap": project_version(component(lock, "lz4kdr_zswap"), "unknown"),
    }
    anchor = 'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"\n'
    position = text.find(anchor)
    if position < 0:
        raise RewriteError("dynamic wrapper versions: NAP patch assignment is missing")
    insertion = (
        f'PATCH_ZRAM_IR_VERSION="{versions["zram_ir"]}"\n'
        + f'PATCH_POC_VERSION="{versions["poc"]}"\n'
        + f'PATCH_NAP_VERSION="{versions["nap"]}"\n'
        + f'PATCH_LZ4KDR_VERSION="{versions["lz4kdr"]}"\n'
        + f'PATCH_LZ4KDR_ZSWAP_VERSION="{versions["lz4kdr_zswap"]}"\n'
    )
    position += len(anchor)
    text = text[:position] + insertion + text[position:]

    replacements = {
        "grep -Fq '#define ZRAM_IR_VERSION \"1.2\"' drivers/block/zram/zram_drv.c":
            '[[ "$PATCH_ZRAM_IR_VERSION" == "unknown" ]] || grep -Fq "$PATCH_ZRAM_IR_VERSION" drivers/block/zram/zram_drv.c',
        "grep -Fq '#define CPUIDLE_NAP_VERSION  \"0.5.0\"' \\\n    drivers/cpuidle/governors/nap/nap.c":
            '[[ "$PATCH_NAP_VERSION" == "unknown" ]] || grep -Fq "$PATCH_NAP_VERSION" \\\n    drivers/cpuidle/governors/nap/nap.c',
        "'Subject: [PATCH] linux7.1-rc1-zram-ir-1.2'": "'zram-ir'",
        "'Subject: [PATCH] 7.1-rc1-poc-selector-v2.6.2r2'": "'poc-selector'",
        "'Subject: [PATCH] 6.18.3-nap-v0.5.0'": "'nap'",
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)

    return text


def validate_lock(lock: dict[str, Any]) -> None:
    if lock.get("schema") != 1:
        raise RewriteError("unsupported patch lock schema")
    required = {
        "bore", "bore_sched_ext_coexistence", "marie", "adios", "zram_ir", "poc", "nap", "reflex",
        "lz4kdr", "lz4kdr_zswap", "vram", "liquorix_config", *REQUESTED.keys(),
    }
    missing = sorted(required - set(lock.get("components", {})))
    if missing:
        raise RewriteError(f"patch lock is incomplete: {', '.join(missing)}")


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: apply-dynamic-patch-sources.py <generated-core> <wrapper> <patch-lock.json>"
        )
    core_path, wrapper_path, lock_path = map(Path, sys.argv[1:])
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    try:
        validate_lock(lock)
        lock = materialize_locked_repositories(lock_path, lock)
        core = patch_core(core_path.read_text(encoding="utf-8"), lock)
        wrapper = patch_wrapper(wrapper_path.read_text(encoding="utf-8"), lock)
    except RewriteError as exc:
        raise SystemExit(f"dynamic patch source rewrite failed: {exc}") from exc
    core_path.write_text(core, encoding="utf-8")
    wrapper_path.write_text(wrapper, encoding="utf-8")
    print("Integrated build-locked dynamic patch sources")


if __name__ == "__main__":
    main()
