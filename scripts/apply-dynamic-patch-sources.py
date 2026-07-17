#!/usr/bin/env python3
"""Rewrite the generated build scripts to consume a build-time patch lock."""
from __future__ import annotations

import json
import re
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

    # Files materialized by the resolver.
    text = replace_assignment(text, "LIQUORIX_CONFIG_URL", file_url(component(lock, "liquorix_config")))
    text = replace_assignment(text, "ADIOS_URL", file_url(component(lock, "adios")))

    # Repositories are local immutable snapshots. Existing fetch/show functions
    # remain unchanged and therefore continue validating the selected blobs.
    for prefix, name in (("INFINITY", "infinity"), ("MARIE", "marie"), ("REFLEX", "reflex")):
        record = component(lock, name)
        text = replace_assignment(text, f"{prefix}_REPO", repo_value(record))
        if f"{prefix}_COMMIT=" in text:
            text = replace_assignment(text, f"{prefix}_COMMIT", str(record["commit"]))
        if f"{prefix}_PATCH_PATH=" in text:
            text = replace_assignment(text, f"{prefix}_PATCH_PATH", str(record["path"]))
        if prefix == "INFINITY" and "INFINITY_BRANCH=" in text:
            text = replace_assignment(text, "INFINITY_BRANCH", str(record.get("ref", "v3")))

    versions = {
        "MARIE": project_version(component(lock, "marie"), "unknown"),
        "REFLEX": project_version(component(lock, "reflex"), "unknown"),
    }
    insertion = (
        f'PATCH_MARIE_VERSION="{versions["MARIE"]}"\n'
        f'PATCH_REFLEX_VERSION="{versions["REFLEX"]}"\n'
    )
    text = replace_once(
        text,
        'MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"\n',
        'MARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"\n' + insertion,
        "dynamic core versions",
    )

    # Remove exact-version assumptions while retaining structural validation.
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

    # Prefer the locally locked requested-series file, while preserving the
    # original remote candidates as diagnostics/fallbacks.
    for name, (output, prefix) in REQUESTED.items():
        component(lock, name)
        anchor = f'"$REQUESTED_SERIES_DIR/{output}" "{prefix}" \\\n'
        replacement = anchor + f'    "file://$RESOLVED_PATCH_ROOT/files/{output}" \\\n'
        text = replace_once(text, anchor, replacement, f"local candidate {name}")

    return text


def patch_wrapper(text: str, lock: dict[str, Any]) -> str:
    if "PATCH_ZRAM_IR_VERSION=" in text and "$RESOLVED_PATCH_ROOT/repos/" in text:
        return text

    # These assignments live inside the wrapper's generated Python string.
    for prefix, name in (("ZRAM_IR", "zram_ir"), ("POC", "poc"), ("NAP", "nap"), ("VRAM_PATCH", "vram")):
        record = component(lock, name)
        repo_var = f"{prefix}_REPO"
        commit_var = f"{prefix}_COMMIT"
        path_var = f"{prefix}_PATCH_PATH"
        if repo_var in text:
            text = replace_assignment(text, repo_var, repo_value(record))
        if commit_var in text:
            text = replace_assignment(text, commit_var, str(record["commit"]))
        if path_var in text:
            text = replace_assignment(text, path_var, str(record["path"]))

    versions = {
        "zram_ir": project_version(component(lock, "zram_ir"), "unknown"),
        "poc": project_version(component(lock, "poc"), "unknown"),
        "nap": project_version(component(lock, "nap"), "unknown"),
    }
    anchor = 'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"\n'
    version_block = (
        anchor
        + f'PATCH_ZRAM_IR_VERSION="{versions["zram_ir"]}"\n'
        + f'PATCH_POC_VERSION="{versions["poc"]}"\n'
        + f'PATCH_NAP_VERSION="{versions["nap"]}"\n'
    )
    text = replace_once(text, anchor, version_block, "dynamic wrapper versions")

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
        "infinity", "marie", "adios", "zram_ir", "poc", "nap", "reflex",
        "vram", "liquorix_config", *REQUESTED.keys(),
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
        core = patch_core(core_path.read_text(encoding="utf-8"), lock)
        wrapper = patch_wrapper(wrapper_path.read_text(encoding="utf-8"), lock)
    except RewriteError as exc:
        raise SystemExit(f"dynamic patch source rewrite failed: {exc}") from exc
    core_path.write_text(core, encoding="utf-8")
    wrapper_path.write_text(wrapper, encoding="utf-8")
    print("Integrated build-locked dynamic patch sources")


if __name__ == "__main__":
    main()
