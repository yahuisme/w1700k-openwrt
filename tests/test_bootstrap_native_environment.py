"""Exact snapshot parse-only consumers. BOOTSTRAP_SOURCE: prepared source, no recipes."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('BOOTSTRAP_SOURCE'), 'requires exact customized source')
class NativeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.source = Path(os.environ['BOOTSTRAP_SOURCE'])
        # Pin the native consumer bytes independently of the helper's REVIEWED set.
        for name, digest in (
                ('include/host-build.mk', '716ff01c7202b08f0361f518a027b639059cf23b10b3604cbb48ef2ef5c93062'),
                ('include/site/cache', 'e4ba9fa208915af904388ee75bb7cc990ab045848392e252af53a81e665f727e'),
                ('include/cmake.mk', 'dab9cb91720a67afb2bab5407038c0d39be0dcb368b656b0c6bb4bb9b5900a6a'),
                ('tools/Makefile', '1e513c33af2ca6d579ddc09a7b900a5ad45e1f2661577276f80e282c01772321')):
            self.assertEqual(hashlib.sha256((self.source / name).read_bytes()).hexdigest(), digest, name)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Empty nested includes isolate the real top-level native consumer.
        # They cannot execute configure, download, prepare, compile or recipes.
        self.includes = self.root / 'include'
        self.includes.mkdir()
        for name in ('download.mk', 'unpack.mk', 'depends.mk', 'quilt.mk', 'autotools.mk'):
            (self.includes / name).write_text('')

    def query(self, body, updates=None):
        query = self.root / 'query.mk'
        query.write_text('INCLUDE_DIR := ' + str(self.includes) + '\n'
                         'HOST_OS := Linux\nPKG_NAME := probe\nPKG_VERSION := 1\n'
                         'BUILD_DIR_HOST := /locked/build/host\n'
                         'STAGING_DIR_HOST := /locked/staging/host\n' + body + '\n'
                         '$(info PROBE_DONE)\n$(error PARSE_ONLY_STOP)\n')
        result = subprocess.run(['make', '-rR', '--no-print-directory', '-f', str(query)],
                                cwd=self.root, env=dict(os.environ, **(updates or {})),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PARSE_ONLY_STOP', result.stderr)
        self.assertIn('PROBE_DONE', result.stdout)
        return result.stdout

    def host_body(self):
        return 'include ' + str(self.source / 'include/host-build.mk') + '\n'

    def test_native_host_paths_and_site_export_condition(self):
        body = self.host_body() + ('$(info BUILD=$(HOST_BUILD_DIR))\n'
                                  '$(info PREFIX=$(HOST_BUILD_PREFIX))\n'
                                  '$(info SITE=$(HOST_CONFIG_SITE))\n'
                                  '$(info BASE=$(HOST_CONFIG_SITE_BASE))\n'
                                  '$(info INHERITED_BASE=$(CONFIG_SITE_BASE))\n'
                                  '$(info EXPORTS=$(call Host/Exports/Default,probe))\n')
        result = self.query(body, {'HOST_BUILD_DIR': '/mutable/build',
                                  'HOST_BUILD_PREFIX': '/mutable/prefix',
                                  'HOST_CONFIG_SITE': '/ignored/site',
                                  'CONFIG_SITE_BASE': '/mutable/base'})
        self.assertIn('BUILD=/mutable/build', result)
        self.assertIn('PREFIX=/mutable/prefix', result)
        # Snapshot resets HOST_CONFIG_SITE: this is NOT a standalone inherited hole.
        self.assertIn('SITE=' + str(self.includes / 'site/cache'), result)
        self.assertNotIn('/ignored/site', result)
        self.assertIn('BASE=\n', result)
        self.assertIn('INHERITED_BASE=/mutable/base', result)
        self.assertNotIn('export CONFIG_SITE_BASE', result)

    def test_native_site_cache_sources_inherited_base_file(self):
        site = self.root / 'base.site'
        for value in ('first', 'changed'):
            site.write_text('ac_cv_bootstrap_probe=' + value + '\n')
            result = subprocess.run(['sh', '-c', '. "$1"; printf "%s\\n" "$ac_cv_bootstrap_probe"',
                                     'site-query', str(self.source / 'include/site/cache')],
                                    env=dict(os.environ, CONFIG_SITE_BASE=str(site),
                                             CONFIGURE_CACHE_FILE=''), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, value + '\n')

    def test_native_cmake_inherited_path_and_appended_options(self):
        body = self.host_body() + 'include ' + str(self.source / 'include/cmake.mk') + '\n'
        body += ('$(info BINARY=$(HOST_CMAKE_BINARY_DIR))\n'
                 '$(info SOURCE=$(HOST_CMAKE_SOURCE_DIR))\n'
                 '$(info OPTIONS=$(CMAKE_HOST_OPTIONS))\n')
        result = self.query(body, {'CMAKE_BINARY_SUBDIR': 'mutable-bin',
                                  'CMAKE_SOURCE_SUBDIR': 'mutable-src',
                                  'CMAKE_HOST_OPTIONS': '-DUNLOCKED=ON'})
        self.assertIn('BINARY=/locked/build/host/probe-1/mutable-bin', result)
        self.assertIn('SOURCE=/locked/build/host/probe-1/mutable-src', result)
        self.assertIn('OPTIONS=-DUNLOCKED=ON ', result)

    def test_native_nonempty_all_tools_and_rust_graph(self):
        body = ('DUMP_TARGET_DB := 1\ninclude ' + str(self.source / 'tools/Makefile') + '\n'
                '$(info TOOLS=$(tools-y))\n$(info BUILD_DIRS=$(tools/builddirs))\n'
                '$(info RUST_BUCKET=$(tools-$(CONFIG_USE_RUST_TOOLCHAIN)))\n'
                '$(info RUST_CONFIG=$(tools_config))\n')
        for value in ('m', 'n'):
            result = self.query(body, {'CONFIG_BUILD_ALL_HOST_TOOLS': value,
                                      'CONFIG_USE_RUST_TOOLCHAIN': value})
            self.assertIn(' liblzo', result)
            self.assertIn('RUST_BUCKET=rust', result)
            self.assertIn('RUST_CONFIG=_', result)
