#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/infinity-source.json"
COMPAT = ROOT / "scripts/validate-infinity-poc-compat.py"


class InfinityFullSeriesTests(unittest.TestCase):
    def test_manifest_requires_all_six_patches(self) -> None:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["ref"], "v4.6-gpu")
        self.assertEqual(len(config["patches"]), 6)
        names = [Path(spec["glob"]).name[:4] for spec in config["patches"]]
        self.assertEqual(names, ["0001", "0002", "0003", "0004", "0005", "0006"])
        required = "\n".join(config["combined_required_markers"])
        self.assertIn("Subject: [PATCH 4/6]", required)
        self.assertIn("drm_sched_entity_calc_vtime", required)
        self.assertIn("INFINITY_GPU_EMA_CLIMB_NS", required)
        self.assertEqual(config["forbidden_markers"], [])

    def test_poc_and_gpu_series_have_no_direct_overlap(self) -> None:
        infinity = """Subject: [PATCH 4/6] v4.6-gpu: GPU DRM scheduler header extensions

diff --git a/include/drm/gpu_scheduler.h b/include/drm/gpu_scheduler.h
Subject: [PATCH 5/6] v4.6-gpu: GPU virtual time scheduling

diff --git a/drivers/gpu/drm/scheduler/sched_main.c b/drivers/gpu/drm/scheduler/sched_main.c
+READ_ONCE(inf_p->infinity.futex_waiting)
+READ_ONCE(inf_p->infinity.ema)
Subject: [PATCH 6/6] v4.6-gpu: cleanup
"""
        poc = """diff --git a/kernel/sched/fair.c b/kernel/sched/fair.c
diff --git a/kernel/sched/sched.h b/kernel/sched/sched.h
diff --git a/kernel/sched/poc_selector.c b/kernel/sched/poc_selector.c
+select_idle_cpu_poc
+!sched_asym_cpucap_active()
+poc_selector_active
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            infinity_path = root / "infinity.patch"
            poc_path = root / "poc.patch"
            infinity_path.write_text(infinity, encoding="utf-8")
            poc_path.write_text(poc, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(COMPAT), str(infinity_path), str(poc_path)],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
