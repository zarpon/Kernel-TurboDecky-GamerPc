#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINALIZER_PATH = ROOT / "scripts/finalize-bore-stable-port.py"
WORKFLOW = ROOT / ".github/workflows/validate-kernel.yml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


finalizer = load_module("finalize_bore_stable_port", FINALIZER_PATH)


class BoreStableFinalizerTests(unittest.TestCase):
    def make_lock(
        self, directory: Path
    ) -> tuple[Path, dict[str, object], dict[str, object]]:
        resolved = directory / ".resolved-patches"
        patch = resolved / "files/01-bore.patch"
        sched_ext_patch = resolved / "files/01-bore-sched-ext-coexistence-fix.patch"
        patch.parent.mkdir(parents=True)
        data = (
            "From 1 Mon Sep 17 00:00:00 2001\n"
            "Subject: [PATCH] linux7.1.5-bore-6.8.0\n\n"
            "diff --git a/kernel/sched/bore.c b/kernel/sched/bore.c\n"
            "+#define SCHED_BORE_VERSION  \"6.8.0\"\n"
            "+sched_bore\n"
        ).encode()
        patch.write_bytes(data)
        sched_ext_data = (
            "From 2 Mon Sep 17 00:00:00 2001\n"
            "Subject: [PATCH] sched-ext-coexistence-fix\n\n"
            "diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c\n"
            "+void reweight_task(struct task_struct *p, int prio)\n"
            "+{\n"
            "+\tstruct sched_entity *se = &p->se;\n"
            "+\tstruct cfs_rq *cfs_rq = cfs_rq_of(se);\n"
            "+\tstruct load_weight *load = &se->load;\n"
            "+\tunsigned long weight = scale_load(sched_prio_to_weight[prio]);\n"
            "+\n"
            "+\treweight_entity(cfs_rq, se, weight);\n"
            "+\tload->inv_weight = sched_prio_to_wmult[prio];\n"
            "+}\n"
        ).encode()
        sched_ext_patch.write_bytes(sched_ext_data)
        record: dict[str, object] = {
            "kind": "git_patch",
            "selection": "exact",
            "kernel_target": "7.1.5",
            "project_version": "6.8.0",
            "output": "files/01-bore.patch",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        sched_ext_record: dict[str, object] = {
            "kind": "git_patch",
            "selection": "exact",
            "output": "files/01-bore-sched-ext-coexistence-fix.patch",
            "sha256": hashlib.sha256(sched_ext_data).hexdigest(),
            "size": len(sched_ext_data),
        }
        lock = {
            "schema": 1,
            "kernel": {"version": "7.1.5", "series": "7.1"},
            "components": {
                "bore": record,
                "bore_sched_ext_coexistence": sched_ext_record,
            },
        }
        lock_path = resolved / "patch-lock.json"
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        return lock_path, record, sched_ext_record

    def test_exact_locked_patch_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path, expected, _sched_ext = self.make_lock(Path(directory))
            record, patch = finalizer.load_locked_bore(lock_path, "7.1.5")
            self.assertEqual(record, expected)
            self.assertEqual(patch.name, "01-bore.patch")

    def test_exact_sched_ext_patch_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path, _bore, expected = self.make_lock(Path(directory))
            record, patch = finalizer.load_locked_sched_ext(lock_path, "7.1.5")
            self.assertEqual(record, expected)
            self.assertEqual(patch.name, "01-bore-sched-ext-coexistence-fix.patch")
            port = finalizer.materialize_sched_ext_port(
                lock_path, record, patch, "7.1.5"
            )
            self.assertEqual(port["source_sha256"], expected["sha256"])
            self.assertEqual(port["kernel_target"], "7.1.5")
            generated = lock_path.parent / port["output"]
            self.assertTrue(generated.is_file())
            self.assertIn(
                "Subject: [PATCH] sched: adapt locked sched-ext coexistence fix to Linux 7.1.5",
                generated.read_text(encoding="utf-8"),
            )
            updated = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["components"]["bore_sched_ext_coexistence"]["compatibility_port"],
                port,
            )

    def test_fallback_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path, _record, _sched_ext = self.make_lock(Path(directory))
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["components"]["bore"]["selection"] = "fallback"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            with self.assertRaisesRegex(finalizer.FinalizeError, "no exact BORE source"):
                finalizer.load_locked_bore(lock_path, "7.1.5")

    def test_final_rewrite_uses_locked_upstream_patch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _lock_path, record, sched_ext_record = self.make_lock(root)
            _loaded, upstream = finalizer.load_locked_sched_ext(_lock_path, "7.1.5")
            sched_ext_port = finalizer.materialize_sched_ext_port(
                _lock_path, sched_ext_record, upstream, "7.1.5"
            )
            core = root / "build-core.sh"
            core.write_text(
                '''BORE_PATCH="$ROOT/patches/bore/.resolved-7.1.5-bore-6.8.0-rc1.patch"
'''
                '''BORE_PORT_VERSION="6.8.0-rc1"
'''
                '''BORE_PORT_UPSTREAM_SHA256="old"
'''
                '''BORE_SCHED_EXT_PORT_UPSTREAM_SHA256="old"
'''
                '''BORE_SCHED_EXT_PATCH="$ROOT/patches/bore/7.1.4-sched-ext-coexistence-fix.patch"
'''
                '''  grep -Fq 'SCHED_BORE_VERSION  "6.8.0-rc1"' "$BORE_UPSTREAM_PATCH"
'''
                '''  grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux 7.1.5' "$BORE_PATCH"
'''
                '''  grep -Fq 'sched: port 0002 sched-ext coexistence fix to Linux 7.1.4' "$BORE_SCHED_EXT_PATCH"
'''
                '''  echo "==> Applying the reviewed BORE 6.8.0-rc1 Linux 7.1.5 port"
'''
                '''    report_bore_rejects "BORE 6.8.0-rc1 for Linux 7.1.5" "$LOGDIR/rejects.log"
'''
                '''    report_bore_rejects "BORE sched_ext coexistence fix for Linux 7.1.5" "$LOGDIR/sched-ext-rejects.log"
'''
                '''  git diff --check | tee "$LOGDIR/01-bore-diff-check.log"
'''
                '''  grep -Fq 'SCHED_BORE_VERSION' kernel/sched/bore.c
'''
                '''  echo "==> BORE 6.8.0-rc1 Linux port applied successfully"
''',
                encoding="utf-8",
            )
            finalizer.rewrite_core(
                core, record, sched_ext_record, sched_ext_port, "7.1.5"
            )
            result = core.read_text(encoding="utf-8")
            self.assertIn('BORE_PATCH="$RESOLVED_PATCH_ROOT/files/01-bore.patch"', result)
            self.assertIn('BORE_PORT_VERSION="6.8.0"', result)
            self.assertIn(str(record["sha256"]), result)
            self.assertIn(str(sched_ext_record["sha256"]), result)
            self.assertIn(
                'BORE_SCHED_EXT_PATCH="$RESOLVED_PATCH_ROOT/'
                'files/01-bore-sched-ext-coexistence-fix-linux7.1.5-port.patch"',
                result,
            )
            self.assertIn("linux${KERNEL_VERSION}-bore-${BORE_PORT_VERSION}", result)
            self.assertIn("include/linux/sched/bore.h", result)
            self.assertIn(
                'report_bore_rejects "BORE $BORE_PORT_VERSION for Linux $KERNEL_VERSION"',
                result,
            )
            self.assertIn(
                'report_bore_rejects "BORE sched_ext coexistence fix for Linux 7.1.5"',
                result,
            )
            self.assertIn("Normalizing whitespace introduced by BORE patch", result)
            self.assertIn("01-bore-diff-check-after-fix.log", result)
            self.assertNotIn("6.8.0-rc1", result)

    def test_sched_ext_structural_change_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path, _record, _sched_ext = self.make_lock(Path(directory))
            patch = lock_path.parent / "files/01-bore-sched-ext-coexistence-fix.patch"
            data = patch.read_bytes().replace(
                b"+void reweight_task(struct task_struct *p, int prio)",
                b"+void reweight_task(struct task_struct *p, int prio)\n"
                b"+void reweight_task(struct task_struct *p, int prio)",
            )
            patch.write_bytes(data)
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            record = lock["components"]["bore_sched_ext_coexistence"]
            record["sha256"] = hashlib.sha256(data).hexdigest()
            record["size"] = len(data)
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            _loaded, upstream = finalizer.load_locked_sched_ext(lock_path, "7.1.5")
            with self.assertRaisesRegex(finalizer.FinalizeError, "exactly one reweight_task"):
                finalizer.materialize_sched_ext_port(
                    lock_path, _loaded, upstream, "7.1.5"
                )

    def test_sched_ext_port_carries_the_current_locked_helper_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path, _record, _sched_ext = self.make_lock(Path(directory))
            patch = lock_path.parent / "files/01-bore-sched-ext-coexistence-fix.patch"
            data = patch.read_bytes().replace(
                b"+\tload->inv_weight = sched_prio_to_wmult[prio];",
                b"+\tload->inv_weight = 0;",
            )
            patch.write_bytes(data)
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            record = lock["components"]["bore_sched_ext_coexistence"]
            record["sha256"] = hashlib.sha256(data).hexdigest()
            record["size"] = len(data)
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            loaded, upstream = finalizer.load_locked_sched_ext(lock_path, "7.1.5")
            port = finalizer.materialize_sched_ext_port(
                lock_path, loaded, upstream, "7.1.5"
            )
            generated = (lock_path.parent / port["output"]).read_text(encoding="utf-8")
            self.assertIn("+\tload->inv_weight = 0;", generated)
            self.assertNotIn("+\tload->inv_weight = sched_prio_to_wmult[prio];", generated)

    def test_workflow_finalizes_bore_after_dynamic_resolution(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        dynamic = (
            "python3 scripts/apply-zarpon-generic-name.py "
            "scripts/build-kernelnote-core.sh scripts/build-kernelnote.sh"
        )
        final = (
            "python3 scripts/finalize-bore-stable-port.py "
            "scripts/build-kernelnote-core.sh"
        )
        self.assertIn(final, workflow)
        self.assertLess(workflow.index(dynamic), workflow.index(final))
        self.assertIn("sched_ext['sha256']", workflow)
        validation = "python3 scripts/validate-resolved-patches.py --lock .resolved-patches/patch-lock.json"
        self.assertGreater(workflow.rindex(validation), workflow.index(final))


if __name__ == "__main__":
    unittest.main()
