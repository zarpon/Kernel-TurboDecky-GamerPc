import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


resolver = load('cast_policy_resolver', ROOT / 'scripts/resolve-patch-sources.py')
port = load('cast_policy_port', ROOT / 'scripts/port-lru-cast-latest.py')


class CastPolicyTests(unittest.TestCase):
    def resolve_fixture(self, paths):
        component = json.loads((ROOT / 'config/patch-sources.json').read_text())['components']['cast']
        patch = b'diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-LRU_CAST lru_cast\n+LRU_CAST lru_cast new\n'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            with mock.patch.object(resolver.base, 'snapshot_repo', return_value='a'*40), \
                 mock.patch.object(resolver.base, 'list_tree', return_value=paths), \
                 mock.patch.object(resolver.base, 'read_git_blob', side_effect=lambda repo, commit, path: (patch, path)):
                lock = resolver.base.resolve({'components': {'cast': component}}, output,
                                             resolver.KernelVersion.parse('7.2.7'), '7.2')
            return lock['components']['cast']

    def test_newer_foreign_release_beats_old_native(self):
        record = self.resolve_fixture(['patches/0001-7.2-rc1-lru_cast-v0.2.5.patch',
                                       'patches/0001-7.3-rc7-lru_cast-v0.3.0.patch'])
        self.assertEqual(record['project_version'], '0.3.0')
        self.assertEqual(record['selection'], 'fallback')

    def test_native_variant_of_latest_release_wins(self):
        record = self.resolve_fixture(['patches/0001-7.2-rc1-lru_cast-v0.3.0.patch',
                                       'patches/0001-7.3-rc7-lru_cast-v0.3.0.patch'])
        self.assertIn('7.2-rc1', record['selected_path'])

    def test_newer_foreign_revision_beats_old_native(self):
        record = self.resolve_fixture(['patches/0001-7.2-rc1-lru_cast-v0.3.0.patch',
                                       'patches/0001-7.3-rc7-lru_cast-v0.3.0r2.patch'])
        self.assertEqual(record['project_version'], '0.3.0r2')
        self.assertEqual(record['selection'], 'fallback')
        self.assertIn('7.3-rc7', record['selected_path'])

    def test_foreign_release_used_when_no_native_exists(self):
        record = self.resolve_fixture(['patches/0001-7.3-rc7-lru_cast-v0.3.0r2.patch',
                                       'patches/0001-7.1-rc1-lru_cast-v0.3.0.patch'])
        self.assertEqual(record['project_version'], '0.3.0r2')
        self.assertEqual(record['selection'], 'fallback')

    def test_kernel_default_and_no_swappiness_override(self):
        self.assertIn('CONFIG_LRU_CAST=y', (ROOT / 'config/kernelnote.config').read_text())
        self.assertIn('assert_config "CONFIG_LRU_CAST=y"', (ROOT / 'scripts/build-kernelnote-core.sh').read_text())
        self.assertNotIn('swappiness', (ROOT / 'packaging/99-kernelnote.conf').read_text())

    def test_native_preflight_preserves_upstream_and_failure_does_not_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            subprocess.run(['git', 'init', '-q', str(tree)], check=True)
            (tree / 'mm').mkdir()
            (tree / 'mm/folio.c').write_text('original\n')
            source, output = tree / 'source.patch', tree / 'prepared.patch'
            source.write_text('diff --git a/mm/folio.c b/mm/folio.c\n--- a/mm/folio.c\n+++ b/mm/folio.c\n@@ -1 +1 @@\n-original\n+replacement\n')
            before = source.read_bytes()
            self.assertEqual(port.prepare(source, output, tree), 'upstream-unmodified')
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual((tree / 'mm/folio.c').read_text(), 'original\n')
            source.write_text(source.read_text().replace('-original', '-missing'))
            with self.assertRaisesRegex(RuntimeError, 'reviewed kernel API port'):
                port.prepare(source, output, tree)
            self.assertFalse(output.exists())
            self.assertEqual((tree / 'mm/folio.c').read_text(), 'original\n')

    def test_reviewed_folio_include_port_preserves_locked_source(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            subprocess.run(['git', 'init', '-q', str(tree)], check=True)
            (tree / 'mm').mkdir()
            (tree / 'mm/folio.c').write_text('#include <linux/buffer_head.h>\n#include <linux/kvm_types.h>\n\n#include "internal.h"\n#include "page_alloc.h"\n')
            source, output = tree / 'source.patch', tree / 'prepared.patch'
            source.write_text('diff --git a/mm/folio.c b/mm/folio.c\n--- a/mm/folio.c\n+++ b/mm/folio.c\n@@ -1,4 +1,5 @@\n #include <linux/buffer_head.h>\n+#include <linux/lru_cast.h>\n \n #include "internal.h"\n #include "page_alloc.h"\n')
            source.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
            folio = tree / 'mm/folio.c'
            folio.write_bytes(folio.read_bytes().replace(b'\r\n', b'\n'))
            locked = source.read_bytes()
            self.assertEqual(port.prepare(source, output, tree), 'ported-folio-include-context')
            self.assertEqual(source.read_bytes(), locked)
            self.assertEqual(subprocess.run(['git', '-C', str(tree), 'apply', '--recount', '--check', str(output)], capture_output=True).returncode, 0)


    def test_linux74_port_is_immutable_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / "mm").mkdir()
            files = {
                "mm/migrate.c": "folio_migrate_lru_refs(newfolio, folio);\n",
                "mm/swap.h": "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio);\n",
                "mm/page_io.c": (
                    "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio)\n"
                    "bio_associate_blkg_from_folio(bio, bio_first_folio_all(bio));\n"
                    "folio_test_dropbehind(bvec_folio(&sio->bvecs[p]))\n"
                ),
                "mm/huge_memory.c": "new_folio->swap.val = folio->swap.val + i;\n",
            }
            for name, body in files.items():
                (tree / name).write_text(body)
            upstream = b"locked 7.3 CAST sample"
            with self.assertRaisesRegex(RuntimeError, "upstream SHA differs"):
                port.port_linux74_rc1(upstream, tree, "inert")
            with mock.patch.object(port, "CAST_74_BASE_SHA256", port.hashlib.sha256(upstream).hexdigest()):
                with self.assertRaises(subprocess.CalledProcessError):
                    # A real Git commit is mandatory; the fixture lacks a .git directory.
                    port.port_linux74_rc1(upstream, tree, "inert")

    def test_linux74_adapter_preserves_exact_context_and_rejects_drift(self):
        source = (ROOT / "scripts/port-lru-cast-latest.py").read_text(encoding="utf-8")
        self.assertIn('KERNEL_VERSION") == "7.4-rc1"', source)
        self.assertIn('LINUX_74_RC1_COMMIT', source)
        self.assertIn('CAST_74_BASE_SHA256', source)
        self.assertIn("apply\", \"--recount\", \"--check\"", source)
        self.assertIn('bio_set_flag(bio, BIO_COMPLETE_IN_TASK)', source)
        self.assertIn('__cast_swap_writeout', source)
        self.assertIn('folio_migrate_lru_refs(newfolio, folio)', source)
        with self.assertRaisesRegex(RuntimeError, "reviewed preimage"):
            port.replace_exactly_once("unrelated", "not here", "new", "test")




if __name__ == '__main__':
    unittest.main()
