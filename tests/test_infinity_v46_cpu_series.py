#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts/resolve-infinity-v46-cpu-series.py"
BUILD_REWRITER = ROOT / "scripts/patch-infinity-v46-build.py"


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


def patch(subject: str, markers: list[str]) -> str:
    marker_lines = "\n".join(f"+/* {marker} */" for marker in markers)
    return (
        f"From {'1' * 40} Mon Sep 17 00:00:00 2001\n"
        "From: Test <test@example.invalid>\n"
        f"Subject: {subject}\n\n"
        "diff --git a/test.c b/test.c\n"
        "--- a/test.c\n"
        "+++ b/test.c\n"
        "@@ -1 +1,2 @@\n"
        " old\n"
        f"{marker_lines}\n"
    )


def init_upstream(path: Path) -> None:
    path.mkdir(parents=True)
    run("git", "init", "-q", "-b", "v4.6-gpu", cwd=path)
    run("git", "config", "user.email", "test@example.invalid", cwd=path)
    run("git", "config", "user.name", "Test", cwd=path)
    files = {
        "0001-v4.5-core-Infinity-scheduler-infrastructure.patch": patch(
            "[PATCH 1/6] v4.5: core Infinity scheduler infrastructure",
            ["kernel/sched/infinity_sched.c", "futex_waiting", "infinity_version"],
        ),
        "0002-v4.5-Infinity-CPU-scheduling-on-CFS-EEVDF.patch": patch(
            "[PATCH 2/6] v4.5: Infinity CPU scheduling on CFS/EEVDF",
            ["infinity_update_weight", "group_ema_sleep_start", "can_migrate_task"],
        ),
        "0003-v4.5-Infinity-RT-scheduling-adaptive-RR-timeslice-an.patch": patch(
            "[PATCH 3/6] v4.5: Infinity RT scheduling -- adaptive RR timeslice and requeue safety valve",
            ["infinity_rt_consume", "infinity_rr_timeslice", "INFINITY_RT_DEMOTE_THRESHOLD", "requeue_task_rt"],
        ),
        "0004-v4.6-gpu-GPU-DRM-scheduler-header-extensions.patch": patch(
            "[PATCH 4/6] v4.6-gpu: GPU DRM scheduler header extensions",
            ["drivers/gpu/drm", "INFINITY_GPU_"],
        ),
        "0005-v4.6-gpu-GPU-virtual-time-scheduling-cross-scheduler.patch": patch(
            "[PATCH 5/6] v4.6-gpu: GPU virtual time scheduling",
            ["drm_sched_entity_calc_vtime"],
        ),
        "0006-v4.6-gpu-remove-dead-normalized_base-field-and-unuse.patch": patch(
            "[PATCH 6/6] v4.6-gpu: cleanup",
            ["drivers/gpu/drm"],
        ),
    }
    base = path / "patches/arch/7.1"
    base.mkdir(parents=True)
    for name, content in files.items():
        (base / name).write_text(content, encoding="utf-8")
    run("git", "add", ".", cwd=path)
    run("git", "commit", "-qm", "initial", cwd=path)


def write_stub_base_resolver(path: Path) -> None:
    path.write_text(
        '''#!/usr/bin/env python3
import argparse, hashlib, json, subprocess
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--manifest", type=Path, required=True)
p.add_argument("--output-dir", type=Path, required=True)
p.add_argument("--kernel-version", required=True)
p.add_argument("--kernel-series", required=True)
a=p.parse_args()
m=json.loads(a.manifest.read_text())
s=m["components"]["infinity"]
path=s["exact_globs"][0]
data=subprocess.check_output(["git","-C",s["repo"],"show",f"{s['ref']}:{path}"])
files=a.output_dir/"files"; files.mkdir(parents=True,exist_ok=True)
out=files/s["output"]; out.write_bytes(data)
lock={"schema":1,"kernel":{"version":a.kernel_version,"series":a.kernel_series},"components":{"infinity":{"kind":"git_patch","repo":s["repo"],"ref":s["ref"],"commit":"0"*40,"path":path,"selected_path":path,"selection":"exact","repo_dir":"repos/infinity","output":f"files/{s['output']}","sha256":hashlib.sha256(data).hexdigest(),"size":len(data)}}}
(a.output_dir/"patch-lock.json").write_text(json.dumps(lock,indent=2)+"\\n")
''',
        encoding="utf-8",
    )
    path.chmod(0o755)


class InfinityResolverTests(unittest.TestCase):
    def prepare(self, tmp: Path) -> tuple[Path, Path, Path, Path]:
        upstream = tmp / "upstream"
        init_upstream(upstream)
        config = json.loads((ROOT / "config/infinity-source.json").read_text())
        config["repo"] = str(upstream)
        config_path = tmp / "infinity.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest = tmp / "manifest.json"
        manifest.write_text(
            json.dumps({"schema": 1, "components": {"infinity": {"kind": "git_patch"}}}),
            encoding="utf-8",
        )
        stub = tmp / "base-resolver.py"
        write_stub_base_resolver(stub)
        return upstream, config_path, manifest, stub

    def invoke(self, tmp: Path, config: Path, manifest: Path, stub: Path, name: str = "resolved") -> Path:
        output = tmp / name
        run(
            sys.executable,
            str(RESOLVER),
            "--manifest",
            str(manifest),
            "--output-dir",
            str(output),
            "--kernel-version",
            "7.1.3",
            "--kernel-series",
            "7.1",
            "--infinity-config",
            str(config),
            "--base-resolver",
            str(stub),
        )
        return output

    def test_combines_only_cpu_rt_patches_and_tracks_branch_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            upstream, config, manifest, stub = self.prepare(tmp)
            first = self.invoke(tmp, config, manifest, stub, "first")
            first_lock = json.loads((first / "patch-lock.json").read_text())
            first_record = first_lock["components"]["infinity"]
            first_bytes = (first / "files/01-infinity.patch").read_bytes()

            self.assertEqual(first_record["ref"], "v4.6-gpu")
            self.assertEqual(first_record["series_count"], 3)
            self.assertEqual(first_record["excluded_patches"], ["0004", "0005", "0006"])
            self.assertEqual(len(first_record["selected_paths"]), 3)
            self.assertIn(b"[PATCH 1/6]", first_bytes)
            self.assertIn(b"[PATCH 2/6]", first_bytes)
            self.assertIn(b"[PATCH 3/6]", first_bytes)
            self.assertNotIn(b"[PATCH 4/6]", first_bytes)
            self.assertNotIn(b"drivers/gpu/drm", first_bytes)
            self.assertNotIn(b"INFINITY_GPU_", first_bytes)
            self.assertEqual(first_record["sha256"], hashlib.sha256(first_bytes).hexdigest())

            patch2 = upstream / "patches/arch/7.1/0002-v4.5-Infinity-CPU-scheduling-on-CFS-EEVDF.patch"
            patch2.write_text(patch2.read_text() + "+/* branch_head_revision_2 */\n")
            run("git", "add", ".", cwd=upstream)
            run("git", "commit", "-qm", "update CPU patch", cwd=upstream)

            second = self.invoke(tmp, config, manifest, stub, "second")
            second_record = json.loads((second / "patch-lock.json").read_text())["components"]["infinity"]
            second_bytes = (second / "files/01-infinity.patch").read_bytes()
            self.assertNotEqual(first_record["upstream_commit"], second_record["upstream_commit"])
            self.assertIn(b"branch_head_revision_2", second_bytes)

    def test_missing_required_patch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            upstream, config, manifest, stub = self.prepare(tmp)
            target = upstream / "patches/arch/7.1/0003-v4.5-Infinity-RT-scheduling-adaptive-RR-timeslice-an.patch"
            target.unlink()
            run("git", "add", "-A", cwd=upstream)
            run("git", "commit", "-qm", "remove RT patch", cwd=upstream)
            result = run(
                sys.executable,
                str(RESOLVER),
                "--manifest",
                str(manifest),
                "--output-dir",
                str(tmp / "failed"),
                "--kernel-version",
                "7.1.3",
                "--kernel-series",
                "7.1",
                "--infinity-config",
                str(config),
                "--base-resolver",
                str(stub),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("expected one match", result.stderr)


class InfinityBuildRewriteTests(unittest.TestCase):
    def test_rewrites_v3_assertions_and_enforces_gpu_exclusion(self) -> None:
        fixture = '''# Correct Infinity scheduler v3 patch for Linux 7.1. This is the single
# cumulative patch from the upstream v3/stable/linux-7.1-infinity tree; it
# includes the CPU, futex and RT hooks. No separate Infinity GPU series is used.
INFINITY_BRANCH="v4.6-gpu"
INFINITY_PATCH_PATH="patches/turbodecky/linux-7.1-infinity/0001-infinity-v4.6-gpu-cpu-rt.patch"
  echo "==> Fetching the pinned correct Infinity CPU scheduler patch locally"
  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' "$INFINITY_PATCH"
  grep -Fq 'Subject: [PATCH] infinity-scheduler v3' "$INFINITY_PATCH"
    echo "Component: Infinity scheduler v3"
  echo "==> Applying the correct Infinity v3 CPU/RT scheduler patch"
  grep -Fq 'infinity_slice' kernel/sched/fair.c
  grep -Fq 'SCHED_FLAG_NO_INFINITY_RT' include/uapi/linux/sched.h
  echo "==> Correct Infinity v3 CPU/RT scheduler patch applied successfully"
'''
        with tempfile.TemporaryDirectory() as directory:
            core = Path(directory) / "core.sh"
            core.write_text(fixture, encoding="utf-8")
            run(sys.executable, str(BUILD_REWRITER), str(core))
            text = core.read_text()
            self.assertIn("patches 0001-0003", text)
            self.assertIn("Subject: [PATCH 3/6]", text)
            self.assertIn("! grep -Fq 'drivers/gpu/drm'", text)
            self.assertIn("INFINITY_RT_DEMOTE_THRESHOLD", text)
            self.assertNotIn("infinity-scheduler v3", text)


if __name__ == "__main__":
    unittest.main()
