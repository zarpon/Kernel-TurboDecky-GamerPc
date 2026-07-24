#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
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
            self.assertIn('ZEN_INTERACTIVE_REF="7.0/zen-sauce"', result)
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

    def test_resolver_has_bounded_commands_and_total_deadline(self) -> None:
        source = RESOLVER.read_text(encoding="utf-8")
        self.assertIn("TOTAL_RESOLVE_TIMEOUT = 600", source)
        self.assertIn("subprocess.TimeoutExpired", source)
        self.assertIn('f"{intro}^"', source)
        self.assertNotIn('["git", "grep", "-l", SYMBOL, head, "--"]', source)


if __name__ == "__main__":
    unittest.main()
