#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
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
    def test_linux_715_port_replaces_removed_util_est_update_hunk(self) -> None:
        port = finalizer.stable.materialize_bore_port("7.1.5")
        try:
            finalizer.validate_port(port, "7.1.5")
            text = port.read_text(encoding="utf-8")
            self.assertIn(
                "Subject: [PATCH] sched: port BORE 6.8.0-rc1 to Linux 7.1.5",
                text,
            )
            hunk = text.split(
                "@@ -7427,6 +7523,20 @@ static bool dequeue_task_fair", 1
            )[1].split("@@ ", 1)[0]
            self.assertNotIn("util_est_update(", hunk)
            self.assertIn("restart_burst_bore(p);", hunk)
            self.assertIn("if (dequeue_entities(rq, &p->se, flags) < 0)", hunk)
        finally:
            port.unlink(missing_ok=True)

    def test_final_rewrite_overrides_a_stale_714_assignment(self) -> None:
        port = finalizer.stable.materialize_bore_port("7.1.5")
        try:
            with tempfile.TemporaryDirectory() as directory:
                core = Path(directory) / "build-core.sh"
                core.write_text(
                    '''BORE_PATCH="$ROOT/patches/bore/7.1.4-bore-6.8.0-rc1.patch"
'''
                    '''grep -Fq 'sched: port BORE 6.8.0-rc1 to Linux 7.1.4' "$BORE_PATCH"
'''
                    '''echo "==> Applying the reviewed BORE 6.8.0-rc1 Linux 7.1.4 port"
'''
                    '''report_bore_rejects "BORE 6.8.0-rc1 for Linux 7.1.4" "$LOGDIR/rejects.log"
''',
                    encoding="utf-8",
                )
                finalizer.rewrite_core(core, port, "7.1.5")
                result = core.read_text(encoding="utf-8")
                self.assertIn(".resolved-7.1.5-bore-6.8.0-rc1.patch", result)
                self.assertNotIn("Linux 7.1.4", result)
                self.assertEqual(result.count("Linux 7.1.5"), 3)
        finally:
            port.unlink(missing_ok=True)

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


if __name__ == "__main__":
    unittest.main()
