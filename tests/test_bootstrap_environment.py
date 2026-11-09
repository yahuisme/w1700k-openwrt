"""Named inherited-native-environment regressions; no build or configure execution."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/bootstrap_cache.py'


class BootstrapFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'source'
        self.root.mkdir()
        (self.root / '.config').write_text('CONFIG_CCACHE=y\n')
        for name in ('scripts', 'tools'):
            (self.root / name).mkdir()
            (self.root / name / 'Makefile').write_text('# fixture\n')
        spec = importlib.util.spec_from_file_location('bootstrap_environment', SCRIPT)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def assert_rejected_cli(self, name, value='/unlocked/input'):
        env = dict(os.environ, **{name: value})
        result = subprocess.run([sys.executable, str(SCRIPT), 'key', str(self.root),
                                 str(self.root / 'cache'), 'builder', 'tc-one'],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, name + ' emitted a key')
        self.assertEqual(result.stdout, '', name)
        self.assertIn('environment overrides', result.stderr, name)
        # Empty environment values do not change the producer contract.
        env[name] = ''
        empty = subprocess.run([sys.executable, str(SCRIPT), 'key', str(self.root),
                                str(self.root / 'cache'), 'builder', 'tc-one'],
                               env=env, capture_output=True, text=True)
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertRegex(empty.stdout, r'^[0-9a-f]{64}\n$')
        with patch.dict(os.environ, {name: ''}):
            self.assertEqual(empty.stdout.strip(), self.module.key(self.root, 'builder', 'tc-one'))



class BootstrapEnvironmentTests(BootstrapFixture):
    def test_config_site_base_file_changes_and_whitespace_reject_without_stdout(self):
        site = self.root.parent / 'external.site'
        for text in ('ac_cv_external=first\n', 'ac_cv_external=changed\n'):
            site.write_text(text)
            self.assert_rejected_cli('CONFIG_SITE_BASE', str(site))
        self.assert_rejected_cli('CONFIG_SITE_BASE', str(self.root / 'missing.site'))
        self.assert_rejected_cli('CONFIG_SITE_BASE', ' ')

    def test_host_build_directory_rejects_without_stdout(self):
        self.assert_rejected_cli('HOST_BUILD_DIR')

    def test_configure_cache_directory_rejects_without_stdout(self):
        self.assert_rejected_cli('CONFIGURE_CACHE_DIR')

    def test_inherited_config_selector_rejects_without_stdout(self):
        self.assert_rejected_cli('CONFIG_BUILD_ALL_HOST_TOOLS', 'n')

    def test_named_native_paths_commands_flags_and_graph_controls(self):
        # Explicit consumers, not a loop over the implementation's guard list.
        for name in (
                'HOST_BUILD_PREFIX', 'HOST_CONFIG_SITE', 'HOST_JOBS', 'HOST_MAKE_PATH',
                'HOST_UNPACK', 'HOST_PATCH_DIR', 'PATCH_DIR', 'UNPACK_CMD', 'PKG_CAT',
                'PKG_SUBDIRS', 'PKG_PROGRAMS', 'PKG_FILE_DEPENDS', 'HOST_PREPARED_DEPENDS',
                'PKG_SOURCE_SUBDIR', 'PKG_SOURCE_URL_FILE', 'PKG_SOURCE_SUBMODULES',
                'PKG_SOURCE_DATE', 'PKG_SOURCE_VERSION', 'PKG_SOURCE_PROTO', 'PKG_MD5SUM',
                'PKG_MIRROR_MD5SUM', 'PKG_SOURCE_MIRROR', 'PKG_MIRROR', 'PKG_SKIP_DOWNLOAD',
                'PKG_HOST_ONLY', 'DL_SUBDIR', 'HOST_USE_NINJA', 'CMAKE_HOST_OPTIONS',
                'CMAKE_BINARY_SUBDIR', 'CMAKE_SOURCE_SUBDIR', 'MESON_USE_STAGING_PYTHON',
                'HOST_FIXUP', 'PKG_FIXUP', 'HOST_LIBTOOL_PATHS', 'HOST_AUTOMAKE_PATHS',
                'HOST_MACRO_PATHS', 'HOST_REMOVE_FILES', 'PKG_LIBTOOL_PATHS',
                'PKG_AUTOMAKE_PATHS', 'PKG_MACRO_PATHS', 'PKG_REMOVE_FILES',
                'CONFIGURE_PATH', 'HOST_QUILT', 'QUILT', 'NO_RECONFIGURE',
                'HOST_BUILD_PARALLEL', 'HOST_CONFIGURE_PARALLEL', 'YEAR_2038',
                'FORCE_HOST_INSTALL', 'tools-core', 'tools-dep', 'tools-', 'tools/ccache',
                'buildtypes-host', 'DUMP', 'DUMP_TARGET_DB', 'CHECK', 'CHECK_ALL', 'FIXUP',
                'NO_DEPS', 'SDK', 'IB', 'FORCE', 'STAMP_PREPARED', 'STAMP_BUILT',
                'NO_TRACE_MAKE', 'ORIG_PATH', 'MAKE', 'SUBMAKE', 'OPENWRT_BUILD',
                'BUILD_TOOLCHAIN', 'BUILD_ISL', 'BUILD_B43_TOOLS', 'BUILD_BZIP2_TOOLS',
                'BUILD_LZ4_TOOLS', 'BUILD_LZO_TOOLS', '__rules_inc', '__autotools_inc',
                '__quilt_inc', '__prereq_inc', 'Hooks/HostConfigure/Pre',
                'Host/Configure', 'Build/Prepare', 'Download/source', 'DownloadMethod/git',
                'ac_cv_func_malloc_0_nonnull', 'gl_cv_func_getcwd_null', 'am_cv_func_iconv',
                'CMAKE_PREFIX_PATH', 'CMAKE_TOOLCHAIN_FILE'):
            with self.subTest(variable=name):
                self.assert_rejected_cli(name)

    def test_rust_and_all_tools_nonempty_selectors_bind_full_toolchain(self):
        m = self.module
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        baseline = 'CONFIG_CCACHE=y\n'
        # Native $(if)/ifdef tests nonempty, including explicit n/m and quoted empty.
        for symbol in ('BUILD_ALL_HOST_TOOLS', 'USE_RUST_TOOLCHAIN', 'USE_RUST_BUILD',
                       'USE_RUST_PREBUILT', 'USE_RUST_HOST', 'BUILD_BINDGEN',
                       'USE_CBINDGEN', 'USE_CORROSION', 'RUST_SCCACHE'):
            for value in ('y', 'm', 'n', '0', '""'):
                with self.subTest(selector=symbol, value=value):
                    (self.root / '.config').write_text(baseline + 'CONFIG_' + symbol + '=' + value + '\n')
                    self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                                        m.key(self.root, 'builder', 'tc-two'))
        (self.root / '.config').write_text(baseline + '# CONFIG_USE_RUST_BUILD is not set\n')
        self.assertEqual(m.key(self.root, 'builder', 'tc-one'),
                         m.key(self.root, 'builder', 'tc-two'))

    def test_rust_host_path_binds_full_toolchain_except_empty_default(self):
        m = self.module
        setattr(m, 'REVIEWED', {m.inventory(self.root)})
        baseline = 'CONFIG_CCACHE=y\n'
        for value in ('"/unlocked/rust"', '"relative-rust"', '" "', 'n'):
            with self.subTest(path=value):
                (self.root / '.config').write_text(baseline + 'CONFIG_RUST_TOOLCHAIN_HOST_PATH=' + value + '\n')
                self.assertNotEqual(m.key(self.root, 'builder', 'tc-one'),
                                    m.key(self.root, 'builder', 'tc-two'))
        for suffix in ('', 'CONFIG_RUST_TOOLCHAIN_HOST_PATH=""\n'):
            (self.root / '.config').write_text(baseline + suffix)
            self.assertEqual(m.key(self.root, 'builder', 'tc-one'),
                             m.key(self.root, 'builder', 'tc-two'))

    def test_empty_and_unrelated_environment_preserve_reviewed_independence(self):
        m = self.module
        # Predicate-only fixture approval; never a new production source lock.
        m.REVIEWED = {m.inventory(self.root)}
        baseline = m.key(self.root, 'builder', 'tc-one')
        with patch.dict(os.environ, {'HOST_BUILD_DIR': '', 'CONFIG_SITE_BASE': '',
                                    'CONFIGURE_CACHE_DIR': '', 'CONFIG_TEST_UNUSED': '',
                                    'UNRELATED_BOOTSTRAP_TEST': 'nonempty'}):
            self.assertEqual(baseline, m.key(self.root, 'builder', 'tc-two'))


@unittest.skipUnless(os.environ.get('BOOTSTRAP_SOURCE'), 'requires customized source')
class PreparedEnvironmentTests(BootstrapFixture):
    def test_real_cli_environment_and_selector_boundaries(self):
        import re
        import shutil
        m = self.module
        source = Path(os.environ['BOOTSTRAP_SOURCE'])
        for name in ('tools', 'scripts'):
            shutil.rmtree(self.root / name)
            shutil.copytree(source / name, self.root / name, symlinks=True)
        for name in (*m.FIXED_INPUTS, '.config', '.external-packages.mk'):
            src, dst = source / name, self.root / name
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        self.assertIn(m.inventory(self.root), m.REVIEWED)

        def cli(tc='tc-one'):
            result = subprocess.run([sys.executable, str(SCRIPT), 'key', str(self.root),
                                     str(self.root / 'cache'), 'builder', tc],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(result.stdout, r'^[0-9a-f]{64}\n$')
            return result

        baseline = cli()
        self.assertIn('reviewed-independent', baseline.stderr)
        self.assertEqual(baseline.stdout, cli('tc-two').stdout)
        for name in ('HOST_BUILD_DIR', 'HOST_CONFIG_SITE', 'HOST_BUILD_PREFIX',
                     'CONFIG_SITE_BASE', 'CONFIGURE_CACHE_DIR',
                     'CONFIG_BUILD_ALL_HOST_TOOLS', 'CMAKE_BINARY_SUBDIR',
                     'Hooks/HostConfigure/Pre', 'tools-core', '__rules_inc'):
            with self.subTest(native_override=name):
                self.assert_rejected_cli(name)
        cfg = self.root / '.config'
        original = cfg.read_text()
        for name in ('BUILD_ALL_HOST_TOOLS', 'USE_RUST_TOOLCHAIN', 'USE_RUST_BUILD',
                     'USE_RUST_PREBUILT', 'USE_RUST_HOST', 'BUILD_BINDGEN',
                     'USE_CBINDGEN', 'USE_CORROSION', 'RUST_SCCACHE',
                     'RUST_TOOLCHAIN_HOST_PATH'):
            clean = re.sub(r'^(?:CONFIG_' + name + r'=.*|# CONFIG_' + name +
                           r' is not set)\n?', '', original, flags=re.M)
            choices = ('"/unlocked/rust"',) if name == 'RUST_TOOLCHAIN_HOST_PATH' else ('y', 'm', 'n')
            for value in choices:
                with self.subTest(selector=name, value=value):
                    cfg.write_text(clean + '\nCONFIG_' + name + '=' + value + '\n')
                    a, b = cli(), cli('tc-two')
                    self.assertIn('full-toolchain-bound', a.stderr)
                    self.assertNotEqual(a.stdout, b.stdout)
        cfg.write_text(original)
        self.assertEqual(baseline.stdout, cli().stdout)


if __name__ == '__main__':
    unittest.main()
