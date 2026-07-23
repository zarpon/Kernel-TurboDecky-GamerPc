#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts/resolve-patch-sources.py"
REWRITER = ROOT / "scripts/apply-dynamic-patch-sources.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def patch(subject: str, marker: str = "marker") -> str:
    return (
        f"From {'1'*40} Mon Sep 17 00:00:00 2001\n"
        f"Subject: [PATCH] {subject}\n\n"
        f"diff --git a/{marker}.c b/{marker}.c\n"
        f"--- a/{marker}.c\n"
        f"+++ b/{marker}.c\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )


def init_repo(path: Path, files: dict[str, str]) -> None:
    path.mkdir(parents=True)
    run("git", "init", "-q", "-b", "main", cwd=path)
    run("git", "config", "user.email", "test@example.invalid", cwd=path)
    run("git", "config", "user.name", "Test", cwd=path)
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run("git", "add", ".", cwd=path)
    run("git", "commit", "-qm", "fixture", cwd=path)


class ResolverTests(unittest.TestCase):
    def test_latest_exact_version_and_nearest_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(
                repo,
                {
                    "patches/stable/0001-linux7.1-lru_marie-0.7.9.patch": patch("lru_marie 0.7.9"),
                    "patches/testing/0001-linux7.1-lru_marie-0.8.0.patch": patch("lru_marie 0.8.0"),
                    "patches/stable/0001-linux6.19.3-nap-v0.6.0.patch": patch("nap 0.6.0"),
                    "patches/stable/0001-linux6.18.3-nap-v0.9.0.patch": patch("nap 0.9.0"),
                },
            )
            raw = tmp / "fixed.patch"
            raw.write_text(patch("fixed"), encoding="utf-8")
            manifest = {
                "schema": 1,
                "components": {
                    "marie": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/stable/*linux{series}*lru_marie*.patch", "patches/testing/*linux{series}*lru_marie*.patch"],
                        "fallback_globs": ["patches/*/*lru_marie*.patch"],
                        "require_exact_series": False,
                        "output": "marie.patch",
                        "project_version_regex": r"lru_marie-([0-9.]+)",
                    },
                    "nap": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/stable/*linux{series}*nap*.patch"],
                        "fallback_globs": ["patches/stable/*nap*.patch"],
                        "require_exact_series": False,
                        "output": "nap.patch",
                        "project_version_regex": r"nap-v([0-9.]+)",
                    },
                    "fixed": {
                        "kind": "http_patch",
                        "urls": [raw.as_uri()],
                        "output": "fixed.patch",
                    },
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = tmp / "resolved"
            run(
                "python3", str(RESOLVER),
                "--manifest", str(manifest_path),
                "--output-dir", str(output),
                "--kernel-version", "7.1.3",
                "--kernel-series", "7.1",
            )
            lock = json.loads((output / "patch-lock.json").read_text())
            self.assertIn("0.8.0", lock["components"]["marie"]["path"])
            self.assertIn("6.19.3", lock["components"]["nap"]["path"])
            self.assertEqual(lock["components"]["nap"]["selection"], "fallback")
            self.assertEqual((output / "files/fixed.patch").read_text(), raw.read_text())

            record = lock["components"]["marie"]
            clone = tmp / "consumer"
            run("git", "init", "-q", str(clone))
            run("git", "-C", str(clone), "remote", "add", "origin", str(output / record["repo_dir"]))
            run("git", "-C", str(clone), "fetch", "--depth=1", "origin", record.get("snapshot_commit", record["commit"]))
            shown = run("git", "-C", str(clone), "show", f"FETCH_HEAD:{record['path']}").stdout
            self.assertIn("lru_marie 0.8.0", shown)

    def test_fallback_ref_restores_exact_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(repo, {"patches/7.1/demo-v2.0.patch": patch("demo 2.0")})
            exact_commit = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
            (repo / "patches/7.1/demo-v2.0.patch").unlink()
            target = repo / "patches/7.0/demo-v3.0.patch"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(patch("demo 3.0"), encoding="utf-8")
            run("git", "add", "-A", cwd=repo)
            run("git", "commit", "-qm", "remove exact", cwd=repo)
            manifest = {
                "schema": 1,
                "components": {
                    "demo": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "fallback_refs": [exact_commit],
                        "exact_globs": ["patches/{series}/demo-*.patch"],
                        "fallback_globs": ["patches/*/demo-*.patch"],
                        "require_exact_series": False,
                        "output": "demo.patch",
                        "project_version_regex": r"demo-v([0-9.]+)",
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = tmp / "resolved"
            run(
                "python3", str(RESOLVER), "--manifest", str(manifest_path),
                "--output-dir", str(output), "--kernel-version", "7.1.3",
                "--kernel-series", "7.1",
            )
            record = json.loads((output / "patch-lock.json").read_text())["components"]["demo"]
            self.assertEqual(record["commit"], exact_commit)
            if "snapshot_commit" in record:
                self.assertRegex(record["snapshot_commit"], r"^[0-9a-f]{40}$")
            self.assertEqual(record["selection"], "exact-fallback-ref")
            self.assertIn("7.1", record["path"])

    def test_git_symlink_patch_is_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(repo, {"patches/7.0/clear.patch": patch("clear target")})
            link = repo / "patches/7.1/clear.patch"
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to("../7.0/clear.patch")
            run("git", "add", "-A", cwd=repo)
            run("git", "commit", "-qm", "series symlink", cwd=repo)
            manifest = {
                "schema": 1,
                "components": {
                    "clear": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/{series}/clear.patch"],
                        "fallback_globs": ["patches/*/clear.patch"],
                        "require_exact_series": False,
                        "output": "clear.patch",
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = tmp / "resolved"
            run(
                "python3", str(RESOLVER), "--manifest", str(manifest_path),
                "--output-dir", str(output), "--kernel-version", "7.1.3",
                "--kernel-series", "7.1",
            )
            record = json.loads((output / "patch-lock.json").read_text())["components"]["clear"]
            self.assertEqual(record["selected_path"], "patches/7.1/clear.patch")
            self.assertEqual(record["path"], "patches/7.0/clear.patch")
            self.assertIn("clear target", (output / "files/clear.patch").read_text())

    def test_exact_required_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(repo, {"patches/stable/linux7.0/demo.patch": patch("demo")})
            manifest = {
                "schema": 1,
                "components": {
                    "demo": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/stable/linux{series}/demo.patch"],
                        "fallback_globs": ["patches/stable/*/demo.patch"],
                        "require_exact_series": True,
                        "output": "demo.patch",
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3", str(RESOLVER), "--manifest", str(manifest_path),
                    "--output-dir", str(tmp / "resolved"), "--kernel-version", "7.1.3",
                    "--kernel-series", "7.1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no exact compatible path", result.stderr)

    def test_approved_sha_prevents_a_stale_local_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            init_repo(
                repo,
                {
                    "patches/testing/0001-linux7.1-rc1-bore-6.8.0-rc1.patch": patch(
                        "bore 6.8.0-rc1", "kernel/sched/bore"
                    )
                },
            )
            manifest = {
                "schema": 1,
                "components": {
                    "bore": {
                        "kind": "git_patch",
                        "repo": str(repo),
                        "ref": "main",
                        "exact_globs": ["patches/testing/*linux{series}*bore*.patch"],
                        "fallback_globs": [],
                        "require_exact_series": True,
                        "output": "bore.patch",
                        "approved_sha256": "0" * 64,
                        "required_markers": ["kernel/sched/bore"],
                    }
                },
            }
            manifest_path = tmp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3", str(RESOLVER), "--manifest", str(manifest_path),
                    "--output-dir", str(tmp / "resolved"), "--kernel-version", "7.1.4",
                    "--kernel-series", "7.1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed local port requires", result.stderr)


class RewriterTests(unittest.TestCase):
    def test_rewrite_is_idempotent_and_uses_local_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            components = {}
            git_names = {"bore", "bore_sched_ext_coexistence", "marie", "adios", "zram_ir", "poc", "nap", "reflex", "vram", "liquorix_config"}
            requested = {
                "c23_libbpf": "08-c23-libbpf.patch", "clear": "09-clear.patch",
                "fsync": "10-fsync-futex-waitv.patch", "o3": "11-o3.patch",
                "bt_ssp": "12-bt-ssp-key-size.patch", "libbpf_uninitialized": "13-libbpf-uninitialized.patch",
                "cpu_optimizations": "14-cpu-optimizations.patch", "dkms_clang": "15-dkms-clang.patch",
                "clang_polly": "16-clang-polly.patch", "firmware_name": "17-firmware-name.patch",
                "minstrel_frac": "18-minstrel-frac.patch", "minstrel_fluctuation": "19-minstrel-fluctuation.patch",
                "minstrel_downgrade": "20-minstrel-downgrade.patch", "ath11k_remapped_ce": "21-ath11k-remapped-ce.patch",
                "ath11k_disable_key": "22-ath11k-disable-key.patch", "ath11k_upstream": "23-ath11k-upstream.patch",
            }
            for name in git_names:
                components[name] = {
                    "kind": "git_patch", "output": f"files/{name}.patch", "repo_dir": f"repos/{name}",
                    "commit": "a" * 40, "path": f"patches/{name}.patch", "ref": "main",
                    "project_version": "9.9.9",
                }
            components["liquorix_config"]["kind"] = "git_file"
            components["liquorix_config"]["output"] = "files/liquorix.config"
            for name, output in requested.items():
                components[name] = {"kind": "http_patch", "output": f"files/{output}"}
            lock = {"schema": 1, "components": components}
            lock_path = tmp / "lock.json"
            for name in git_names:
                output = tmp / components[name]["output"]
                output.parent.mkdir(parents=True, exist_ok=True)
                if name == "liquorix_config":
                    output.write_text("CONFIG_GENERIC_CPU=y\n", encoding="utf-8")
                else:
                    output.write_text(patch(f"{name} snapshot"), encoding="utf-8")
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            requested_calls = "".join(
                f'  "$REQUESTED_SERIES_DIR/{output}" "{prefix}" \\\n    "https://example.invalid/{output}"\n'
                for name, output, prefix in [
                    ("c23_libbpf", "08-c23-libbpf.patch", "08-c23-libbpf"),
                    ("clear", "09-clear.patch", "09-clear"),
                    ("fsync", "10-fsync-futex-waitv.patch", "10-fsync"),
                    ("o3", "11-o3.patch", "11-o3"),
                    ("bt_ssp", "12-bt-ssp-key-size.patch", "12-bt-ssp"),
                    ("libbpf_uninitialized", "13-libbpf-uninitialized.patch", "13-libbpf-uninitialized"),
                    ("cpu_optimizations", "14-cpu-optimizations.patch", "14-cpu-optimizations"),
                    ("dkms_clang", "15-dkms-clang.patch", "15-dkms-clang"),
                    ("clang_polly", "16-clang-polly.patch", "16-clang-polly"),
                    ("firmware_name", "17-firmware-name.patch", "17-firmware-name"),
                    ("minstrel_frac", "18-minstrel-frac.patch", "18-minstrel-frac"),
                    ("minstrel_fluctuation", "19-minstrel-fluctuation.patch", "19-minstrel-fluctuation"),
                    ("minstrel_downgrade", "20-minstrel-downgrade.patch", "20-minstrel-downgrade"),
                    ("ath11k_remapped_ce", "21-ath11k-remapped-ce.patch", "21-ath11k-remapped-ce"),
                    ("ath11k_disable_key", "22-ath11k-disable-key.patch", "22-ath11k-disable-key"),
                    ("ath11k_upstream", "23-ath11k-upstream.patch", "23-ath11k-upstream"),
                ]
            )
            core = tmp / "core.sh"
            core.write_text(
                '#!/bin/bash\nROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                'WORKDIR="$ROOT/work"\nLOGDIR="$ROOT/logs"\nARTIFACTS="$ROOT/artifacts"\nPATCHDIR="$WORKDIR/patches"\n'
                'LIQUORIX_CONFIG_URL="old"\nADIOS_URL="old"\n'
                'BORE_REPO="old"\nBORE_BRANCH="main"\nBORE_COMMIT="old"\nBORE_PATCH_PATH="old"\n'
                'BORE_SCHED_EXT_REPO="old"\nBORE_SCHED_EXT_COMMIT="old"\nBORE_SCHED_EXT_PATCH_PATH="old"\n'
                'MARIE_REPO="old"\nMARIE_COMMIT="old"\nMARIE_PATCH_PATH="old"\nMARIE_PATCH="$PATCHDIR/0002-lru-marie-0.7.7-testing-linux7.1.patch"\n'
                'REFLEX_REPO="old"\nREFLEX_COMMIT="old"\nREFLEX_PATCH_PATH="old"\n'
                'rm -rf "$WORKDIR" "$LOGDIR" "$ARTIFACTS"\nmkdir -p "$PATCHDIR" "$LOGDIR" "$ARTIFACTS"\n'
                + requested_calls,
                encoding="utf-8",
            )
            wrapper = tmp / "wrapper.sh"
            wrapper.write_text(
                'ZRAM_IR_REPO="old"\nZRAM_IR_COMMIT="old"\nZRAM_IR_PATCH_PATH="old"\n'
                'POC_REPO="old"\nPOC_COMMIT="old"\nPOC_PATCH_PATH="old"\n'
                'NAP_REPO="old"\nNAP_COMMIT="old"\nNAP_PATCH_PATH="old"\n'
                'NAP_PATCH="$PATCHDIR/0006-nap-v0.5.0-linux7.1-port.patch"\n'
                'VRAM_PATCH_REPO="old"\nVRAM_PATCH_COMMIT="old"\nVRAM_PATCH_PATH="old"\n',
                encoding="utf-8",
            )
            run("python3", str(REWRITER), str(core), str(wrapper), str(lock_path))
            first_core = core.read_text()
            first_wrapper = wrapper.read_text()
            run("python3", str(REWRITER), str(core), str(wrapper), str(lock_path))
            self.assertEqual(first_core, core.read_text())
            self.assertEqual(first_wrapper, wrapper.read_text())
            self.assertIn("RESOLVED_PATCH_ROOT", first_core)
            self.assertIn("file://$RESOLVED_PATCH_ROOT/files/08-c23-libbpf.patch", first_core)
            self.assertIn('$RESOLVED_PATCH_ROOT/materialized-repos/bore', first_core)
            self.assertIn('$RESOLVED_PATCH_ROOT/materialized-repos/bore_sched_ext_coexistence', first_core)
            self.assertIn('$RESOLVED_PATCH_ROOT/materialized-repos/vram', first_wrapper)
            rewritten_lock = json.loads(lock_path.read_text())
            bore = rewritten_lock["components"]["bore"]
            self.assertRegex(bore["snapshot_commit"], r"^[0-9a-f]{40}$")
            self.assertEqual(bore["commit"], bore["snapshot_commit"])
            self.assertEqual(bore["upstream_commit"], "a" * 40)
            self.assertFalse((tmp / bore["repo_dir"] / ".git/objects/info/alternates").exists())


if __name__ == "__main__":
    unittest.main()
