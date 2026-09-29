"""Exact-key policy regression tests; temporary fixtures, no network."""
import importlib.util
import os
from unittest.mock import patch
from pathlib import Path
import shutil
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

    def test_inactive_generic_kernel_inputs_do_not_invalidate(self):
        self.put('target/linux/airoha/Makefile', 'KERNEL_PATCHVER:=6.18\n')
        before = self.key()
        for name in ('kernel-6.12', 'config-6.12', 'backport-6.12/001.patch',
                     'pending-6.12/001.patch', 'hack-6.12/001.patch',
                     'files-6.12/include/test.h'):
            with self.subTest(name=name):
                p = self.put('target/linux/generic/' + name, 'old')
                stamp = p.stat().st_mtime_ns
                self.assertEqual(before, self.key())
                self.assertEqual(stamp, p.stat().st_mtime_ns)
                p.write_text('new')
                self.assertEqual(before, self.key())
                p.unlink()
                self.assertEqual(before, self.key())

    def test_kernel_selection_unknown_keeps_all_inputs(self):
        for declaration in ('', 'KERNEL_TESTING_PATCHVER:=6.19\n',
                            'KERNEL_PATCHVER:=$(NEXT_KERNEL)\n',
                            'KERNEL_PATCHVER:=6.18\\\n',
                            'KERNEL_PATCHVER:=6.18\nKERNEL_TESTING_PATCHVER?=6.19\n',
                            'override KERNEL_PATCHVER:=6.18\n'):
            with self.subTest(declaration=declaration):
                self.put('target/linux/airoha/Makefile', declaration)
                p = self.put('target/linux/generic/kernel-6.12', 'old')
                before = self.key()
                p.write_text('new')
                self.assertNotEqual(before, self.key())

    def test_unresolved_target_include_keeps_all_kernel_inputs(self):
        self.put('target/linux/airoha/Makefile',
                 'KERNEL_PATCHVER:=6.18\ninclude $(TOPDIR)/selection.inc\n')
        p = self.put('target/linux/generic/kernel-6.12', 'old')
        before = self.key()
        p.write_text('new')
        self.assertNotEqual(before, self.key())

    def test_declared_normal_testing_and_subtarget_versions_stay_hashed(self):
        self.put('target/linux/airoha/Makefile',
                 'KERNEL_PATCHVER := 6.18 # normal\nKERNEL_TESTING_PATCHVER:=6.19\n')
        self.put('target/linux/airoha/an7581/target.mk', 'KERNEL_PATCHVER:=6.20\n')
        for selection in ('', 'CONFIG_TESTING_KERNEL=y\n'):
            self.put('.config', selection)
            for version in ('6.18', '6.19', '6.20'):
                for name in ('kernel-', 'config-', 'files-', 'backport-', 'pending-', 'hack-'):
                    path = name + version + ('/test' if name not in ('kernel-', 'config-') else '')
                    with self.subTest(selection=selection, path=path):
                        p = self.put('target/linux/generic/' + path, 'old')
                        before = self.key()
                        p.write_text('new')
                        self.assertNotEqual(before, self.key())
                        p.unlink()
                        self.assertNotEqual(before, self.key())

    def test_kernel_selection_changes_without_hardcoded_version(self):
        selection = self.put('target/linux/airoha/Makefile', 'KERNEL_PATCHVER:=7.1\n')
        p = self.put('target/linux/generic/config-7.1', 'old')
        before = self.key()
        p.write_text('new')
        self.assertNotEqual(before, self.key())
        before = self.key()
        selection.write_text('KERNEL_PATCHVER:=7.2\n')
        self.assertNotEqual(before, self.key())
        before = self.key()
        p.write_text('inactive')
        self.assertEqual(before, self.key())

    def test_shared_unknown_and_target_kernel_paths_stay_hashed(self):
        self.put('target/linux/airoha/Makefile', 'KERNEL_PATCHVER:=6.18\n')
        for path in ('generic/files/include/test.h', 'generic/backport/test.patch',
                     'generic/pending/test.patch', 'generic/hack/test.patch',
                     'generic/config-default', 'generic/config-filter',
                     'generic/kernel-6.12-extra', 'generic/config-6.12.1',
                     'generic/future-6.12/test', 'generic/patches-6.12/test',
                     'generic/files/config-6.12', 'generic/config-6.12/nested',
                     'airoha/patches-6.12/test', 'airoha/an7581/config-6.12'):
            with self.subTest(path=path):
                p = self.put('target/linux/' + path, 'old')
                before = self.key()
                p.write_text('new')
                self.assertNotEqual(before, self.key())
                p.unlink()
        p = self.put('target/linux/generic/hack-6.12', 'not a directory')
        before = self.key()
        p.write_text('new')
        self.assertNotEqual(before, self.key())

    def test_inactive_version_root_symlink_is_rejected(self):
        self.put('target/linux/airoha/Makefile', 'KERNEL_PATCHVER:=6.18\n')
        (self.root / 'target/linux/generic/files-6.12').symlink_to('/outside')
        with self.assertRaisesRegex(ValueError, 'linked input'):
            self.key()

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
        alternate.write_text(SCRIPT.read_text().replace('tc-inputs-v8', 'tc-inputs-test'))
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


@unittest.skipUnless(os.environ.get('OPENWRT_SOURCE'), 'requires prepared official source')
class PreparedKernelKeyTests(unittest.TestCase):
    def test_real_tree_same_path_kernel_inputs(self):
        cache = load(SCRIPT)
        source = Path(os.environ['OPENWRT_SOURCE'])
        with tempfile.TemporaryDirectory() as tmp:
            # Copy only the actual fingerprint domain, preserving links. No
            # build, feeds or compilation prerequisites are needed for hashing.
            root = Path(tmp) / 'prepared'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            if (source / '.gitignore').exists():
                shutil.copy2(source / '.gitignore', root / '.gitignore')
            for name in cache.INPUTS:
                src, dst = source / name, root / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, symlinks=True)
                else:
                    shutil.copy2(src, dst)
            baseline = cache.key(root, 'prepared-image')
            for name in ('kernel-6.12', 'config-6.12',
                         'backport-6.12/cache-probe.patch',
                         'pending-6.12/cache-probe.patch',
                         'hack-6.12/cache-probe.patch',
                         'files-6.12/include/cache-probe.h'):
                p = root / 'target/linux/generic' / name
                original = p.read_bytes() if p.exists() else None
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((original or b'') + b'\n# inactive kernel probe\n')
                stamp = p.stat().st_mtime_ns
                self.assertEqual(baseline, cache.key(root, 'prepared-image'), name)
                self.assertEqual(stamp, p.stat().st_mtime_ns)
                p.unlink()
                self.assertEqual(baseline, cache.key(root, 'prepared-image'), name)
                if original is not None:
                    p.write_bytes(original)
            for name in ('target/linux/generic/kernel-6.18',
                         'target/linux/generic/config-6.18',
                         'target/linux/generic/backport-6.18/cache-probe.patch',
                         'target/linux/generic/files/include/cache-probe.h',
                         'include/kernel-version.mk', 'include/target.mk',
                         'include/quilt.mk', 'target/linux/airoha/Makefile', '.config'):
                p = root / name
                original = p.read_bytes() if p.exists() else None
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes((original or b'') + b'\n# active/shared probe\n')
                self.assertNotEqual(baseline, cache.key(root, 'prepared-image'), name)
                if original is None:
                    p.unlink()
                else:
                    p.write_bytes(original)
                self.assertEqual(baseline, cache.key(root, 'prepared-image'), name)
            self.assertNotEqual(baseline, cache.key(root, 'changed-image'))
            # Evaluate the real official version consumer with GNU make, not a
            # Python reimplementation. This target only prints variables.
            probe = Path(tmp) / 'consumer.mk'
            probe.write_text(
                '__rules_inc:=1\n__target_inc:=1\n'
                f'TOPDIR:={root}\nINCLUDE_DIR:=$(TOPDIR)/include\n'
                'include $(TOPDIR)/target/linux/airoha/Makefile\n'
                'include $(TOPDIR)/target/linux/airoha/an7581/target.mk\n'
                'GENERIC_PLATFORM_DIR:=$(TOPDIR)/target/linux/generic\n'
                'include $(INCLUDE_DIR)/kernel-version.mk\n'
                'probe:\n\t@printf "%s\\n" "$(KERNEL_PATCHVER)" "$(KERNEL_DETAILS_FILE)"\n')
            result = subprocess.run(['make', '-rR', '-s', '-f', str(probe), 'probe'],
                                    cwd=root, check=True, text=True, capture_output=True)
            self.assertEqual(result.stdout.splitlines(),
                             ['6.18', str(root / 'target/linux/generic/kernel-6.18')])


if __name__ == '__main__':
    unittest.main()
