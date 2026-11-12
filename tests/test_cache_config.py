"""Final-config hash projection; native make only, never firmware compilation."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('config_test_' + name, REPO / 'scripts' / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, DK_PROFILE=str(REPO / 'user/default')):
        spec.loader.exec_module(module)
    return module


class FinalConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        self.root.mkdir()
        self.tc = load('cache')
        self.tb = load('bootstrap_cache')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in self.tc.INPUTS:
            self.put(name + '/Makefile' if name in self.tc.INPUTS[:7] else name, b'# fixture\n')
        self.raw = b'CONFIG_CCACHE=y\nCONFIG_PACKAGE_active=m\n# ordinary comment\n'
        self.put('.config', self.raw)

    def put(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def keys(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return (self.tc.key(self.root, 'builder'), self.tb.key(self.root, 'builder', 'tc'))

    def test_unique_canonical_unset_package_is_hash_only_noise(self):
        before = self.keys()
        raw = self.raw + b'# CONFIG_PACKAGE_luci-app-argon-config is not set\n'
        path = self.put('.config', raw)
        self.assertEqual(before, self.keys())
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(path.stat().st_mtime_ns, self.tc.EPOCH * 1_000_000_000)
        self.assertEqual(self.tb.configuration(self.root)[0], raw)
    def test_inactive_boost_selectors_do_not_invalidate_either_cache(self):
        before = self.keys()
        selectors = ('context', 'coroutine', 'fiber')
        raw = self.raw + ''.join(
            f'# CONFIG_boost-{name}-exclude is not set\n' for name in selectors).encode()
        path = self.put('.config', raw)
        self.assertEqual(before, self.keys())
        self.assertEqual(path.read_bytes(), raw)

    def test_boost_assignments_and_active_packages_keep_selectors_locked(self):
        helper = self.tc.cache_config
        selector = b'# CONFIG_boost-context-exclude is not set\n'
        for package in ('boost', 'boost-context', 'boost-fiber', 'boost-headers'):
            for state in ('y', 'm', 'n'):
                raw = self.raw + f'CONFIG_PACKAGE_{package}={state}\n'.encode() + selector
                with self.subTest(package=package, state=state):
                    self.assertEqual(helper.fingerprint_bytes(raw), raw)
        for state in ('y', 'm', 'n'):
            raw = self.raw + f'CONFIG_boost-context-exclude={state}\n'.encode()
            self.assertEqual(helper.fingerprint_bytes(raw), raw)
        for extra in (selector, b'CONFIG_boost-context-exclude=y\n'):
            raw = self.raw + selector + extra
            self.assertEqual(helper.fingerprint_bytes(raw), raw)
        raw = self.raw + b'# CONFIG_boost-future-exclude is not set\n'
        self.assertEqual(helper.fingerprint_bytes(raw), raw)

    def test_ambiguous_or_unknown_format_keeps_entire_raw_bytes(self):
        helper = self.tc.cache_config
        noise = b'# CONFIG_PACKAGE_noise is not set\n'
        for extra in (
                noise, b'CONFIG_PACKAGE_noise=y\n', b'CONFIG_PACKAGE_noise=m\n',
                b'CONFIG_PACKAGE_noise=n\n', b'# CONFIG_PACKAGE_noise is not set \n',
                b'CONFIG_PACKAGE_noise = y\n', b'unknown-format\n',
                b'# CONFIG_PACKAGE_ is not set\n', b'CONFIG_CCACHE=y\n',
                b'# malformed\r\n', b'# unterminated', b'\x00\n', b'\xff\n',
                b'CONFIG_UNSAFE="$(shell id)"\n', b'CONFIG_UNSAFE="`id`"\n',
                b'# continuation\\\n', b'CONFIG_OTHER=y\nCONFIG_OTHER=m\n',
                b'#  CONFIG_PACKAGE_other is not set\n', b'#CONFIG_PACKAGE_other is not set\n',
                b'# CONFIG_PACKAGE_other is not set\t\n', b'# comment\x7f\n'):
            raw = self.raw + noise + extra
            with self.subTest(extra=extra):
                self.assertEqual(helper.fingerprint_bytes(raw), raw)
        raw = noise.rstrip(b'\n')
        self.assertEqual(helper.fingerprint_bytes(raw), raw)

    def test_selected_explicit_n_nonpackage_unset_comments_and_order_are_raw(self):
        helper = self.tc.cache_config
        for line in (b'CONFIG_PACKAGE_x=y\n', b'CONFIG_PACKAGE_x=m\n',
                     b'CONFIG_PACKAGE_x=n\n', b'# CONFIG_KERNEL_X is not set\n',
                     b'# ordinary\n', b'CONFIG_VERSION_NUMBER="one"\n'):
            raw = self.raw + line
            self.assertEqual(helper.fingerprint_bytes(raw), raw)
        raw = b'CONFIG_PACKAGE_z=y\n# CONFIG_PACKAGE_x is not set\nCONFIG_PACKAGE_a=m\n'
        self.assertEqual(helper.fingerprint_bytes(raw), b'CONFIG_PACKAGE_z=y\nCONFIG_PACKAGE_a=m\n')
    def test_both_keys_retain_active_n_nonpackage_comments_and_raw_formats(self):
        before = self.keys()
        for extra in (b'CONFIG_PACKAGE_probe=y\n', b'CONFIG_PACKAGE_probe=m\n',
                      b'CONFIG_PACKAGE_probe=n\n', b'# CONFIG_KERNEL_PROBE is not set\n',
                      b'# ordinary new comment\n'):
            self.put('.config', self.raw + extra)
            with self.subTest(extra=extra):
                for old, new in zip(before, self.keys()):
                    self.assertNotEqual(old, new)
        noise = b'# CONFIG_PACKAGE_probe is not set\n'
        for raw in (self.raw + noise + noise, self.raw + noise + b'CONFIG_PACKAGE_probe=y\n',
                    (self.raw + noise).replace(b'\n', b'\r\n'), self.raw + noise.rstrip(b'\n')):
            self.put('.config', raw)
            with self.subTest(raw=raw):
                for old, new in zip(before, self.keys()):
                    self.assertNotEqual(old, new)

    def test_native_make_unset_is_absent_but_explicit_n_is_defined(self):
        makefile = self.put('probe.mk', (
            'include .config\n'
            'probe:\n\t@printf "%s|%s|%s\\n" "$(origin CONFIG_PACKAGE_probe)" '
            '"$(CONFIG_PACKAGE_probe)" "$(if $(CONFIG_PACKAGE_probe),selected,absent)"\n'
        ).encode())
        outputs = []
        for config in (b'', b'# CONFIG_PACKAGE_probe is not set\n', b'CONFIG_PACKAGE_probe=n\n'):
            self.put('.config', config)
            result = subprocess.run(['make', '-rR', '-s', '-f', str(makefile), 'probe'],
                                    cwd=self.root, text=True, capture_output=True, check=True,
                                    env={k: v for k, v in os.environ.items() if k not in ('MAKEFLAGS', 'MAKEFILES')})
            outputs.append(result.stdout)
        self.assertEqual(outputs[:2], ['undefined||absent\n'] * 2)
        self.assertEqual(outputs[2], 'file|n|selected\n')

    def test_shared_helper_bytes_invalidate_both_cli_keys_at_container_boundary(self):
        import shutil
        import sys
        mount = Path(self.tmp.name) / 'cache-scripts'
        mount.mkdir()
        for name in ('cache.py', 'bootstrap_cache.py', 'cache_config.py',
                     'build_profile.py', 'toolchain_archive.py'):
            shutil.copy2(REPO / 'scripts' / name, mount / name)
        environment = dict(os.environ, DK_PROFILE=str(REPO / 'user/default'), PYTHONPATH='')
        # The container has no checkout user/default; absolute standalone script
        # invocation must resolve its sibling helper, not depend on runner CWD.
        def cli_keys():
            values = []
            for script, args in (('cache.py', ['key', self.root, self.root / 'unused', 'builder']),
                                 ('bootstrap_cache.py', ['key', self.root, self.root / 'unused', 'builder', 'tc'])):
                result = subprocess.run([sys.executable, str(mount / script), *map(str, args)],
                                        cwd=self.tmp.name, env=environment, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout, r'^[0-9a-f]{64}\n$')
                values.append(result.stdout)
            return values
        before = cli_keys()
        helper = mount / 'cache_config.py'
        helper.write_bytes(helper.read_bytes() + b'\n# changed shared policy\n')
        for old, new in zip(before, cli_keys()):
            self.assertNotEqual(old, new)
        # importlib absolute-path callers (including temporary baseline modules)
        # still work from the runner with Docker-only DK_PROFILE.
        code = (
            'import importlib.util; '
            f's=importlib.util.spec_from_file_location("absolute_fixture", {str(REPO / "scripts/cache.py")!r}); '
            'm=importlib.util.module_from_spec(s); s.loader.exec_module(m)'
        )
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO,
                                env=dict(os.environ, DK_PROFILE='/bld/user/default'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_config_mode_and_builder_remain_compatibility_inputs(self):
        before = self.keys()
        path = self.root / '.config'
        path.chmod(path.stat().st_mode ^ 0o100)
        for old, new in zip(before, self.keys()):
            self.assertNotEqual(old, new)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(self.tc.key(self.root, 'builder'), self.tc.key(self.root, 'other'))
            self.assertNotEqual(self.tb.key(self.root, 'builder', 'tc'), self.tb.key(self.root, 'other', 'tc'))

    def test_bootstrap_validation_still_consumes_raw_external_assignments(self):
        for line in (b'CONFIG_EXTERNAL_TOOLCHAIN=y\n', b'CONFIG_EXTERNAL_KERNEL_TREE="/outside"\n',
                     b'CONFIG_DOWNLOAD_FOLDER="/outside"\n', b'CONFIG_HOST_EXTRA_CFLAGS="-I/outside"\n'):
            self.put('.config', self.raw + b'# CONFIG_PACKAGE_noise is not set\n' + line)
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.tb.key(self.root, 'builder', 'tc')
    def test_path_environment_source_and_unknown_tc_boundary_remain_locked(self):
        import shutil
        before = self.keys()
        other = Path(self.tmp.name) / 'relocated'
        shutil.copytree(self.root, other)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(before[0], self.tc.key(other, 'builder'))
            self.assertNotEqual(before[1], self.tb.key(other, 'builder', 'tc'))
            self.assertNotEqual(before[1], self.tb.key(self.root, 'builder', 'changed-tc'))
            with patch.dict(os.environ, LANG='changed-language'):
                self.assertNotEqual(before[1], self.tb.key(self.root, 'builder', 'tc'))
            for name in self.tb.OVERRIDES:
                with self.subTest(override=name), patch.dict(os.environ, {name: 'unlocked'}), self.assertRaises(ValueError):
                    self.tb.key(self.root, 'builder', 'tc')
            p = self.root / 'tools/Makefile'
            p.write_bytes(p.read_bytes() + b'# changed source\n')
            for old, new in zip(before, self.keys()):
                self.assertNotEqual(old, new)

    def test_reviewed_independent_config_noise_and_unknown_inventory_fallback(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.tb.REVIEWED = {self.tb.inventory(self.root)}
            before = self.tb.key(self.root, 'builder', 'tc-one')
            self.assertEqual(before, self.tb.key(self.root, 'builder', 'tc-two'))
            self.put('.config', self.raw + b'# CONFIG_PACKAGE_noise is not set\n')
            self.assertEqual(before, self.tb.key(self.root, 'builder', 'tc-two'))
            self.put('.config', self.raw + b'CONFIG_BUILD_ALL_HOST_TOOLS=y\n')
            self.assertNotEqual(self.tb.key(self.root, 'builder', 'tc-one'),
                                self.tb.key(self.root, 'builder', 'tc-two'))


@unittest.skipUnless(os.environ.get('CACHE_CONFIG_SOURCES'), 'requires prepared official sources')
class PreparedMetadataTests(unittest.TestCase):
    def test_real_package_metadata_kernel_overrides_do_not_treat_explicit_n_as_unset(self):
        helper = load('cache_config')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = root / 'packageinfo'
            metadata.write_text('Package: probe\nKernel-Config: CONFIG_PROBE CONFIG_OVERRIDE=y\n')
            config = root / 'config'
            for source in os.environ['CACHE_CONFIG_SOURCES'].split(os.pathsep):
                source = Path(source)
                # Inspect actual production consumers, then execute only the Perl
                # metadata query. No source preparation, make defconfig or build.
                self.assertIn('-include $(TOPDIR)/.config', (source / 'rules.mk').read_text())
                self.assertIn('package-metadata.pl kconfig', (source / 'include/kernel-defaults.mk').read_text())
                outputs = {}
                for value in ('missing', 'unset', 'y', 'm', 'n'):
                    raw = (b'# CONFIG_PACKAGE_probe is not set\n' if value == 'unset' else
                           b'' if value == 'missing' else f'CONFIG_PACKAGE_probe={value}\n'.encode())
                    def invoke(data):
                        config.write_bytes(data)
                        return subprocess.run(['perl', str(source / 'scripts/package-metadata.pl'), 'kconfig',
                                               str(metadata), str(config), '6.18'], text=True,
                                              capture_output=True, check=True).stdout
                    outputs[value] = invoke(raw)
                    self.assertEqual(outputs[value], invoke(helper.fingerprint_bytes(raw)))
                self.assertEqual(outputs['missing'], outputs['unset'])
                self.assertEqual(outputs['unset'], '# CONFIG_PROBE is not set\n')
                for value in ('y', 'm', 'n'):
                    self.assertEqual(outputs[value], 'CONFIG_OVERRIDE=y\nCONFIG_PROBE=m\n')


if __name__ == '__main__':
    unittest.main()
