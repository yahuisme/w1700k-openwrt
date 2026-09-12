"""Exact-key policy regression tests; temporary fixtures, no network."""
import importlib.util
import os
from unittest.mock import patch
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cache.py'


def load(path):
    spec = importlib.util.spec_from_file_location('cache_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        self.root.mkdir()
        self.cache = load(SCRIPT)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in self.cache.INPUTS:
            self.put(name + '/Makefile' if name in self.cache.INPUTS[:7] else name, 'input\n')

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def key(self):
        return self.cache.key(self.root, 'image-sha')

    def test_runtime_overlay_add_edit_rename_delete_and_symlink(self):
        before = self.key()
        for overlay in ('generic', 'airoha', 'airoha/an7581'):
            with self.subTest(overlay=overlay):
                p = self.put(f'target/linux/{overlay}/base-files/etc/hotplug.d/iface/51-test', 'old')
                stamp = p.stat().st_mtime_ns
                self.assertEqual(before, self.key())
                self.assertEqual(stamp, p.stat().st_mtime_ns)
                p.write_text('new')
                self.assertEqual(before, self.key())
                p = p.rename(p.with_name('52-test'))
                self.assertEqual(before, self.key())
                p.unlink()
                p.symlink_to('/etc/not-a-build-input')
                self.assertEqual(before, self.key())
                p.unlink()
                self.assertEqual(before, self.key())

    def test_compilation_inputs_still_invalidate(self):
        for name in ('.config', 'tools/flock/Makefile', 'tools/include/sys/test.h',
                     'toolchain/gcc/patches/001-test.patch', 'include/target.mk',
                     'target/linux/airoha/an7581/target.mk',
                     'target/linux/airoha/base-files.mk',
                     'target/linux/generic/config-6.18',
                     'target/linux/generic/files/include/test.h',
                     'target/linux/airoha/patches-6.18/001-test.patch',
                     'target/linux/airoha/files/base-files/test.h'):
            with self.subTest(name=name):
                p = self.put(name, 'old')
                before = self.key()
                p.write_text('new')
                self.assertNotEqual(before, self.key())
                before = self.key()
                p.unlink()
                if name != '.config':
                    self.assertNotEqual(before, self.key())
                else:
                    with self.assertRaises(ValueError):
                        self.key()
                    self.put(name, 'input')

    def test_policy_not_archive_code_participates(self):
        before = self.key()
        alternate = Path(self.tmp.name) / 'alternate.py'
        alternate.write_text(SCRIPT.read_text().replace('def pack(root, cache, kind, expected):',
                            'def pack(root, cache, kind, expected):\n    # unrelated upload edit'))
        self.assertEqual(before, load(alternate).key(self.root, 'image-sha'))
        alternate.write_text(SCRIPT.read_text().replace('tc-inputs-v6', 'tc-inputs-test'))
        self.assertNotEqual(before, load(alternate).key(self.root, 'image-sha'))

    def test_entire_config_always_participates(self):
        original = 'CONFIG_PACKAGE_runtime=y\nCONFIG_VERSION_NUMBER="one"\n'
        self.put('.config', original)
        before = self.key()
        for changed in (original.replace('runtime=y', 'runtime=m'),
                        original.replace('"one"', '"two"'), original + '# comment\n'):
            self.put('.config', changed)
            self.assertNotEqual(before, self.key())

    def test_external_mutable_inputs_rejected(self):
        for setting in ('CONFIG_EXTERNAL_TOOLCHAIN=y', 'CONFIG_SRC_TREE_OVERRIDE=y',
                        'CONFIG_EXTERNAL_KERNEL_TREE="/outside"'):
            self.put('.config', setting + '\n')
            with self.assertRaises(ValueError):
                self.key()

    def test_generated_config_and_completion_mtimes(self):
        self.put('scripts/config/.gitignore', 'conf\n*.o\n')
        before = self.key()
        generated = self.put('scripts/config/conf', 'generated')
        stamp = self.put('build_dir/host/flock/.built', 'stamp')
        ns = 1700000000123456789
        os.utime(stamp, ns=(ns, ns))
        self.assertEqual(before, self.key())
        self.assertEqual(stamp.stat().st_mtime_ns, ns)
        self.assertEqual((self.root / 'tools/Makefile').stat().st_mtime_ns,
                         self.cache.EPOCH * 1_000_000_000)
        generated.write_text('different generated output')
        self.assertEqual(before, self.key())

    def test_archive_pairing_pax_and_gzip_fallback(self):
        for name in ('build_dir/host/.built', 'staging_dir/host/bin/tool',
                     'build_dir/toolchain-test/.built', 'staging_dir/toolchain-test/lib/test'):
            p = self.put(name, 'layout fixture, not GCC')
            os.utime(p, ns=(1700000000123456789, 1700000000123456789))
        archive = Path(self.tmp.name) / 'archive'
        expected = self.key()
        with patch.object(self.cache.shutil, 'which', return_value=None):
            self.cache.pack(self.root, archive, 'toolchain', expected)
        self.put('build_dir/stale-target/object', 'must disappear')
        self.cache.restore(self.root, archive, expected)
        self.assertFalse((self.root / 'build_dir/stale-target').exists())
        self.assertEqual((self.root / 'build_dir/host/.built').stat().st_mtime_ns,
                         1700000000123456789)
        with self.assertRaisesRegex(ValueError, 'key mismatch'):
            self.cache.restore(self.root, archive, 'wrong-key')
        self.cache.restore(self.root, archive / 'absent', expected)
        self.assertFalse((self.root / 'staging_dir').exists())
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.cache.pack(self.root, archive, 'toolchain', expected)

    def test_mode_mtime_image_and_links(self):
        p = self.root / 'tools/Makefile'
        before = self.key()
        p.touch()
        self.assertEqual(before, self.key())
        p.chmod(p.stat().st_mode ^ 0o100)
        self.assertNotEqual(before, self.key())
        self.assertNotEqual(self.key(), self.cache.key(self.root, 'other-image'))
        p.unlink()
        p.symlink_to('../.config')
        with self.assertRaises(ValueError):
            self.key()


if __name__ == '__main__':
    unittest.main()
