#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REWRITER = ROOT / "scripts/apply-zen-interactive.py"
RESOLVER = ROOT / "scripts/resolve-zen-interactive.py"
CORE = ROOT / "scripts/build-kernelnote-core.sh"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


rewriter = load("apply_zen_interactive", REWRITER)
resolver = load("resolve_zen_interactive", RESOLVER)


class ZenInteractiveRewriterTests(unittest.TestCase):
    def test_rewriter_integrates_official_profile_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text(CORE.read_text(encoding="utf-8"), encoding="utf-8")
            rewriter.rewrite(path)
            result = path.read_text(encoding="utf-8")
            self.assertIn(
                'ZEN_INTERACTIVE_REF="${KERNEL_SERIES:-7.1}/zen-sauce"', result
            )
            self.assertIn("compatibility commits", result)
            self.assertIn("fetch_zen_interactive_profile", result)
            self.assertIn("apply_zen_interactive_profile", result)
            self.assertIn("assert_zen_patch_does_not_touch_thp", result)
            self.assertIn("00-zen-interactive-thp-preserved.sha256", result)
            self.assertIn("scripts/config --enable ZEN_INTERACTIVE", result)
            self.assertIn('assert_config "CONFIG_ZEN_INTERACTIVE=y"', result)
            rewriter.rewrite(path)
            self.assertEqual(result, path.read_text(encoding="utf-8"))

    def test_rewriter_survives_prior_fetch_injections(self) -> None:
        original = CORE.read_text(encoding="utf-8")
        old = 'download "$LIQUORIX_CONFIG_URL" "$WORKDIR/liquorix-amd64.config"\n'
        self.assertEqual(original.count(old), 1)
        transformed = original.replace(
            old,
            old + "fetch_requested_patch_series\nfetch_reflex_patch\n",
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text(transformed, encoding="utf-8")
            rewriter.rewrite(path)
            result = path.read_text(encoding="utf-8")
            self.assertIn(
                "fetch_requested_patch_series\nfetch_reflex_patch\n\n"
                "fetch_zen_interactive_profile\n\ncd \"$KERNELDIR\"",
                result,
            )

    def test_rewriter_rejects_missing_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text("echo no anchors\n", encoding="utf-8")
            with self.assertRaises(rewriter.RewriteError):
                rewriter.rewrite(path)

    def test_resolver_keeps_symbol_hunks_and_excludes_thp(self) -> None:
        diff = """diff --git a/init/Kconfig b/init/Kconfig
index 1111111111111111111111111111111111111111..2222222222222222222222222222222222222222 100644
--- a/init/Kconfig
+++ b/init/Kconfig
@@ -1,2 +1,8 @@
 menu \"General setup\"
+config ZEN_INTERACTIVE
+\tbool \"Tune kernel for interactivity\"
+\tdefault y
+\thelp
+\t    Background-reclaim hugepages...: no -> yes
+
 config OTHER
diff --git a/mm/page_alloc.c b/mm/page_alloc.c
index 3333333333333333333333333333333333333333..4444444444444444444444444444444444444444 100644
--- a/mm/page_alloc.c
+++ b/mm/page_alloc.c
@@ -1,2 +1,4 @@
+#ifdef CONFIG_ZEN_INTERACTIVE
+#define DEFAULT_BOOST 0
+#endif
 value
diff --git a/mm/huge_memory.c b/mm/huge_memory.c
index 5555555555555555555555555555555555555555..6666666666666666666666666666666666666666 100644
--- a/mm/huge_memory.c
+++ b/mm/huge_memory.c
@@ -1,2 +1,6 @@
+#ifdef CONFIG_ZEN_INTERACTIVE
+#define THP_DEFAULT CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS
+#endif
 value
"""
        filtered, files, hunks, excluded = resolver.filter_symbol_hunks(diff)
        self.assertEqual(files, ["init/Kconfig", "mm/page_alloc.c"])
        self.assertEqual(hunks, 2)
        self.assertEqual(excluded, 1)
        self.assertIn("config ZEN_INTERACTIVE", filtered)
        self.assertIn("CONFIG_ZEN_INTERACTIVE", filtered)
        self.assertIn("Transparent memory-page policy....: unchanged", filtered)
        self.assertNotIn("mm/huge_memory.c", filtered)
        self.assertNotIn("TRANSPARENT_HUGEPAGE", filtered)
        self.assertNotIn("THP_DEFAULT", filtered)
        resolver.assert_thp_untouched(filtered)

    def test_thp_guard_rejects_functional_thp_changes(self) -> None:
        patch = """diff --git a/mm/Kconfig b/mm/Kconfig
--- a/mm/Kconfig
+++ b/mm/Kconfig
@@ -1 +1 @@
-CONFIG_TRANSPARENT_HUGEPAGE_MADVISE=y
+CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS=y
"""
        with self.assertRaises(resolver.ResolveError):
            resolver.assert_thp_untouched(patch)

    def test_resolver_discovers_only_introduction_commit_files(self) -> None:
        paths = "init/Kconfig\nmm/page_alloc.c\nREADME\n"
        contents = {
            "init/Kconfig": "config ZEN_INTERACTIVE\n",
            "mm/page_alloc.c": "#ifdef CONFIG_ZEN_INTERACTIVE\n#endif\n",
            "README": "unrelated\n",
        }

        def read_file_at(_checkout: Path, _head: str, path: str) -> str:
            return contents[path]

        with mock.patch.object(resolver, "run", return_value=paths) as run_mock:
            with mock.patch.object(resolver, "read_file_at", side_effect=read_file_at):
                selected = resolver.discover_symbol_files(
                    Path("checkout"), intro="intro", head="head"
                )

        self.assertEqual(selected, ["init/Kconfig", "mm/page_alloc.c"])
        command = run_mock.call_args.args[0]
        self.assertEqual(command[:2], ["git", "diff-tree"])
        self.assertNotIn("grep", command)

    def test_resolver_prefers_exact_series_and_falls_back_to_older_series(self) -> None:
        refs = """a refs/heads/7.0/zen-sauce
b refs/heads/7.1/zen-sauce
c refs/heads/6.18/zen-sauce
"""
        with mock.patch.object(resolver, "run", return_value=refs):
            self.assertEqual(
                resolver.select_compatible_ref("7.1"),
                ("7.1/zen-sauce", "7.1", "exact-series"),
            )
        with mock.patch.object(resolver, "run", return_value=refs):
            self.assertEqual(
                resolver.select_compatible_ref("7.2"),
                ("7.1/zen-sauce", "7.1", "nearest-older-series"),
            )

    def test_resolver_materializes_current_compatibility_commits(self) -> None:
        patches = {
            "drivers/input/evdev.c": """diff --git a/drivers/input/evdev.c b/drivers/input/evdev.c
--- a/drivers/input/evdev.c
+++ b/drivers/input/evdev.c
@@ -1 +1 @@
-old
+call_rcu(&client->rcu, evdev_reclaim_client);
""",
            "drivers/cpufreq/Kconfig.x86": """diff --git a/drivers/cpufreq/Kconfig.x86 b/drivers/cpufreq/Kconfig.x86
--- a/drivers/cpufreq/Kconfig.x86
+++ b/drivers/cpufreq/Kconfig.x86
@@ -1 +1 @@
-select CPU_FREQ_GOV_SCHEDUTIL
+# dependency removed for REFLEX
""",
        }

        def fake_run(args, **_kwargs):
            if args[1] == "log":
                return "commit-" + args[-1].replace("/", "-") + "\n"
            if args[1] == "rev-parse":
                return "parent\n"
            if args[1] == "diff":
                return patches[args[-1]]
            if args[1] == "show":
                return "ZEN compatibility commit\n"
            raise AssertionError(args)

        with mock.patch.object(resolver, "run", side_effect=fake_run):
            sources = resolver.discover_compatibility_sources(
                Path("checkout"), head="head"
            )

        self.assertEqual(
            [source["name"] for source in sources],
            ["evdev-call-rcu", "cpufreq-pstate-schedutil-dependency"],
        )
        self.assertTrue(all(source["sha256"] for source in sources))
        self.assertIn("call_rcu(&client->rcu", sources[0]["patch"])
        self.assertIn("CPU_FREQ_GOV_SCHEDUTIL", sources[1]["patch"])

    def test_resolver_main_writes_patch_lock_and_provenance(self) -> None:
        profile = resolver.ProfileResolution(
            patch="diff --git a/init/Kconfig b/init/Kconfig\n",
            head="head",
            intro="intro",
            base="base",
            ref="7.1/zen-sauce",
            kernel_target="7.1",
            files=["drivers/input/evdev.c", "init/Kconfig"],
            hunks=2,
            profile_hunks=1,
            excluded_thp_hunks=1,
            compatibility_sources=[
                {
                    "name": "evdev-call-rcu",
                    "path": "drivers/input/evdev.c",
                    "commit": "compat",
                    "parent_commit": "parent",
                    "subject": "compatibility",
                    "selection": "latest matching commit on selected official Zen series",
                    "sha256": "digest",
                    "size": 12,
                    "patch": "diff --git a/drivers/input/evdev.c b/drivers/input/evdev.c\n",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "zen.patch"
            provenance = root / "zen.provenance"
            lock = root / "patch-lock.json"
            lock.write_text('{"components": {}}\n', encoding="utf-8")
            argv = sys.argv
            sys.argv = [
                "resolve-zen-interactive.py",
                "--checkout",
                str(root / "checkout"),
                "--output",
                str(output),
                "--provenance",
                str(provenance),
                "--lock",
                str(lock),
            ]
            try:
                with mock.patch.object(resolver, "fetch_profile", return_value=profile):
                    resolver.main()
            finally:
                sys.argv = argv

            self.assertEqual(output.read_text(encoding="utf-8"), profile.patch)
            self.assertIn("Compatibility commit: evdev-call-rcu", provenance.read_text())
            record = json.loads(lock.read_text(encoding="utf-8"))["components"][
                "zen_interactive"
            ]
            self.assertEqual(record["compatibility_sources"][0]["commit"], "compat")
            self.assertNotIn("patch", record["compatibility_sources"][0])

    def test_resolver_fetch_profile_composes_a_local_series_checkout(self) -> None:
        def git(*args: str, cwd: Path) -> None:
            subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "zen.git"
            repo.mkdir()
            git("init", "--quiet", cwd=repo)
            git("config", "user.email", "test@example.invalid", cwd=repo)
            git("config", "user.name", "test", cwd=repo)

            files = {
                "init/Kconfig": "menu General\n",
                "mm/page_alloc.c": "int page_alloc;\n",
                "drivers/input/evdev.c": (
                    "static void evdev_detach_client(void)\n"
                    "{\n"
                    "\tsynchronize_rcu();\n"
                    "}\n"
                ),
                "drivers/cpufreq/Kconfig.x86": (
                    "config X86_PSTATE\n"
                    "\tselect CPU_FREQ_GOV_SCHEDUTIL\n"
                ),
            }
            for relative, content in files.items():
                path = repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            git("add", ".", cwd=repo)
            git("commit", "-qm", "base", cwd=repo)

            (repo / "init/Kconfig").write_text(
                "menu General\n"
                "config ZEN_INTERACTIVE\n"
                '\tbool "Tune interactivity"\n'
                "\tdefault y\n",
                encoding="utf-8",
            )
            (repo / "mm/page_alloc.c").write_text(
                "int page_alloc;\n"
                "#ifdef CONFIG_ZEN_INTERACTIVE\n"
                "int zen_page_alloc;\n"
                "#endif\n",
                encoding="utf-8",
            )
            git("add", ".", cwd=repo)
            git("commit", "-qm", "introduce Zen interactive profile", cwd=repo)

            (repo / "drivers/input/evdev.c").write_text(
                "static void evdev_reclaim_client(void) {}\n"
                "static void evdev_detach_client(void)\n"
                "{\n"
                "\tcall_rcu(&client->rcu, evdev_reclaim_client);\n"
                "}\n",
                encoding="utf-8",
            )
            git("add", ".", cwd=repo)
            git("commit", "-qm", "evdev call_rcu", cwd=repo)

            (repo / "drivers/cpufreq/Kconfig.x86").write_text(
                "config X86_PSTATE\n",
                encoding="utf-8",
            )
            git("add", ".", cwd=repo)
            git("commit", "-qm", "remove schedutil dependency", cwd=repo)
            git("update-ref", "refs/heads/7.1/zen-sauce", "HEAD", cwd=repo)

            checkout = root / "checkout"
            original_repo = resolver.REPO
            resolver.REPO = str(repo)
            try:
                with mock.patch.dict(os.environ, {"KERNEL_SERIES": "7.1"}):
                    resolution = resolver.fetch_profile(checkout)
            finally:
                resolver.REPO = original_repo

            self.assertEqual(resolution.ref, "7.1/zen-sauce")
            self.assertEqual(
                [source["name"] for source in resolution.compatibility_sources],
                ["evdev-call-rcu", "cpufreq-pstate-schedutil-dependency"],
            )
            self.assertIn("config ZEN_INTERACTIVE", resolution.patch)
            self.assertIn("call_rcu(&client->rcu", resolution.patch)
            self.assertIn("CPU_FREQ_GOV_SCHEDUTIL", resolution.patch)

    def test_resolver_has_bounded_commands_and_total_deadline(self) -> None:
        source = RESOLVER.read_text(encoding="utf-8")
        self.assertIn("TOTAL_RESOLVE_TIMEOUT = 600", source)
        self.assertIn("subprocess.TimeoutExpired", source)
        self.assertIn('f"{intro}^"', source)
        self.assertIn("git", source)
        self.assertIn("compatibility_sources", source)
        self.assertNotIn('["git", "grep", "-l", SYMBOL, head, "--"]', source)


if __name__ == "__main__":
    unittest.main()
