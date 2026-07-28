#!/usr/bin/env python3
"""Guard the build-time policy that selects current compatible patch sources."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/patch-sources.json"
RESOLVER_PATH = ROOT / "scripts/resolve-patch-sources.py"
REFLEX_REWRITER = (ROOT / "scripts/apply-reflex-core.py").read_text(encoding="utf-8")
DYNAMIC_REWRITER = (ROOT / "scripts/apply-dynamic-patch-sources.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/validate-kernel.yml").read_text(encoding="utf-8")

VERSIONED_COMPONENTS = {
    "bore",
    "marie",
    "adios",
    "zram_ir",
    "poc",
    "nap",
    "reflex",
}

IMMUTABLE_HTTP_COMPONENTS = {
    "c23_libbpf",
    "bt_ssp",
    "libbpf_uninitialized",
    "firmware_name",
    "ath11k_disable_key",
    "ath11k_upstream",
}

EXPECTED_COMPONENTS = {
    "bore",
    "bore_sched_ext_coexistence",
    "marie",
    "adios",
    "zram_ir",
    "poc",
    "nap",
    "reflex",
    "c23_libbpf",
    "clear",
    "fsync",
    "o3",
    "bt_ssp",
    "libbpf_uninitialized",
    "cpu_optimizations",
    "dkms_clang",
    "clang_polly",
    "firmware_name",
    "minstrel_frac",
    "minstrel_fluctuation",
    "minstrel_downgrade",
    "ath11k_remapped_ce",
    "ath11k_disable_key",
    "ath11k_upstream",
    "vram",
    "liquorix_config",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PatchSourcePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.components = cls.manifest["components"]

    def test_manifest_covers_the_complete_patchset(self) -> None:
        self.assertEqual(self.manifest["schema"], 1)
        self.assertEqual(set(self.components), EXPECTED_COMPONENTS)

    def test_all_git_sources_follow_a_live_primary_ref(self) -> None:
        for name, component in self.components.items():
            if component["kind"] not in {"git_patch", "git_file"}:
                continue
            with self.subTest(component=name):
                self.assertRegex(component["repo"], r"^https://")
                primary_ref = component.get("ref", "main")
                self.assertTrue(primary_ref)
                self.assertIsNone(
                    re.fullmatch(r"[0-9a-f]{40}", primary_ref),
                    f"{name} primary ref is pinned instead of following upstream",
                )
                self.assertTrue(component.get("exact_globs"))
                self.assertIn("require_exact_series", component)

    def test_versioned_patchsets_have_latest_version_metadata(self) -> None:
        for name in VERSIONED_COMPONENTS:
            component = self.components[name]
            with self.subTest(component=name):
                self.assertEqual(component["kind"], "git_patch")
                self.assertTrue(component.get("project_version_regex"))
                self.assertTrue(component.get("required_markers"))
                self.assertNotRegex(component.get("ref", ""), r"^[0-9a-f]{40}$")

    def test_http_sources_are_explicit_immutable_fixes(self) -> None:
        actual = {
            name for name, component in self.components.items()
            if component["kind"] == "http_patch"
        }
        self.assertEqual(actual, IMMUTABLE_HTTP_COMPONENTS)
        for name in actual:
            with self.subTest(component=name):
                urls = self.components[name].get("urls", [])
                self.assertTrue(urls)
                self.assertTrue(all(url.startswith("https://") for url in urls))

    def test_resolver_prefers_newer_component_versions_for_equal_compatibility(self) -> None:
        resolver = load_module("resolve_patch_sources_policy", RESOLVER_PATH)
        kernel = resolver.KernelVersion.parse("7.1.5")
        reflex_031 = resolver.candidate_score(
            "patches/0001-linux7.1-reflex-v0.3.1.patch",
            kernel,
            self.components["reflex"]["project_version_regex"],
        )
        reflex_032 = resolver.candidate_score(
            "patches/0001-linux7.1-reflex-v0.3.2.patch",
            kernel,
            self.components["reflex"]["project_version_regex"],
        )
        self.assertGreater(reflex_032, reflex_031)

        marie_090 = resolver.candidate_score(
            "patches/testing/0001-linux7.1-lru_marie-0.9.0.patch",
            kernel,
            self.components["marie"]["project_version_regex"],
        )
        marie_091 = resolver.candidate_score(
            "patches/testing/0001-linux7.1-lru_marie-0.9.1.patch",
            kernel,
            self.components["marie"]["project_version_regex"],
        )
        self.assertGreater(marie_091, marie_090)

    def test_reflex_bootstrap_is_rewritten_to_the_locked_dynamic_version(self) -> None:
        self.assertIn("# REFLEX dynamic patch bootstrap", REFLEX_REWRITER)
        self.assertIn('PATCH_REFLEX_VERSION="${{PATCH_REFLEX_VERSION:-0.3.1}}"', REFLEX_REWRITER)
        self.assertIn("Fetching REFLEX CPUFreq $PATCH_REFLEX_VERSION", REFLEX_REWRITER)
        self.assertIn("Applying REFLEX CPUFreq $PATCH_REFLEX_VERSION", REFLEX_REWRITER)
        self.assertIn("drivers/base/arch_topology.c", REFLEX_REWRITER)
        self.assertNotIn("Fetching pinned REFLEX CPUFreq 0.3.1", REFLEX_REWRITER)
        self.assertNotIn("Applying native Linux 7.1 REFLEX CPUFreq 0.3.1", REFLEX_REWRITER)

        self.assertIn('("BORE", "bore"), ("MARIE", "marie"), ("REFLEX", "reflex")', DYNAMIC_REWRITER)
        self.assertIn('replace_assignment(text, "PATCH_REFLEX_VERSION"', DYNAMIC_REWRITER)

    def test_ci_resolves_sources_after_injecting_reflex(self) -> None:
        reflex = "python3 scripts/apply-reflex-core.py"
        dynamic = "python3 scripts/apply-zarpon-generic-name.py"
        self.assertIn(reflex, WORKFLOW)
        self.assertIn(dynamic, WORKFLOW)
        self.assertLess(WORKFLOW.index(reflex), WORKFLOW.index(dynamic))


if __name__ == "__main__":
    unittest.main()
