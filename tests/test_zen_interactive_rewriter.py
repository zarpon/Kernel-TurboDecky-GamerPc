#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

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
            self.assertIn("scripts/config --enable ZEN_INTERACTIVE", result)
            self.assertIn('assert_config "CONFIG_ZEN_INTERACTIVE=y"', result)
            rewriter.rewrite(path)
            self.assertEqual(result, path.read_text(encoding="utf-8"))

    def test_rewriter_rejects_missing_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build-core.sh"
            path.write_text("echo no anchors\n", encoding="utf-8")
            with self.assertRaises(rewriter.RewriteError):
                rewriter.rewrite(path)

    def test_resolver_keeps_only_symbol_gated_hunks(self) -> None:
        diff = """diff --git a/init/Kconfig b/init/Kconfig
index 1111111111111111111111111111111111111111..2222222222222222222222222222222222222222 100644
--- a/init/Kconfig
+++ b/init/Kconfig
@@ -1,2 +1,6 @@
 menu \"General setup\"
+config ZEN_INTERACTIVE
+\tbool \"Tune kernel for interactivity\"
+\tdefault y
+
 config OTHER
@@ -20,2 +24,3 @@ config OTHER
 value
+unrelated change
 end
diff --git a/mm/page_alloc.c b/mm/page_alloc.c
index 3333333333333333333333333333333333333333..4444444444444444444444444444444444444444 100644
--- a/mm/page_alloc.c
+++ b/mm/page_alloc.c
@@ -1,2 +1,4 @@
+#ifdef CONFIG_ZEN_INTERACTIVE
+#define DEFAULT_BOOST 0
+#endif
 value
@@ -20,2 +22,3 @@
 value
+unrelated change
 end
"""
        filtered, files, hunks = resolver.filter_symbol_hunks(diff)
        self.assertEqual(files, ["init/Kconfig", "mm/page_alloc.c"])
        self.assertEqual(hunks, 2)
        self.assertIn("config ZEN_INTERACTIVE", filtered)
        self.assertIn("CONFIG_ZEN_INTERACTIVE", filtered)
        self.assertNotIn("unrelated change", filtered)


if __name__ == "__main__":
    unittest.main()
