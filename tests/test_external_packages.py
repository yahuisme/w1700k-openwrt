"""Signed Aurora APK assembly on real rolling-source fixtures; no builds."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location('external_packages', ROOT / 'scripts/external_packages.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExternalPackageTests(unittest.TestCase):
    def test_snapshot_precedes_cache_key_and_covers_shared_device_resolver(self):
        fixture = os.environ.get('AURORA_SOURCE_FIXTURE')
        self.assertTrue(fixture, 'set AURORA_SOURCE_FIXTURE to the real distro source fixture')
        assert fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(fixture, root, dirs_exist_ok=True)
            helper().prepare(root)
            package = (root / 'package/Makefile').read_text()
            self.assertIn('$(curdir)/install: $(curdir)/aurora-snapshot', package)
            self.assertIn('$(curdir)/aurora-snapshot: FORCE $(TMP_DIR)/.build $(curdir)/merge-index', package)
            self.assertIn('$(EXTERNAL_PACKAGES)', package)
            cache = package.split('define rootfs_cache_key\n')[1].split('endef')[0]
            self.assertIn('.external-packages/eamonxg/packages.adb', cache)
            common = (root / 'include/rootfs.mk').read_text()
            self.assertIn('$(EXTERNAL_REPOSITORIES)', common)
            self.assertIn('--no-network', common)
            self.assertIn('external_packages.py verify-root $(1)', common)
            self.assertNotIn('honk', (root / '.external-packages.mk').read_text())
            self.assertEqual((root / 'include/image.mk').read_bytes(), (Path(fixture) / 'include/image.mk').read_bytes())
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            helper().prepare(root)
            self.assertEqual(before, {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_official_snapshot_and_updatable_rootfs(self):
        fixture = os.environ.get('AURORA_APK_FIXTURE')
        self.assertTrue(fixture, 'set AURORA_APK_FIXTURE to the verified native APK fixture')
        assert fixture
        fixture = Path(fixture)
        module = helper()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.config').write_text('CONFIG_USE_APK=y\nCONFIG_TARGET_ARCH_PACKAGES="aarch64_cortex-a53"\n')
            repositories = {'eamonxg': dict(module.REPOSITORIES['eamonxg'],
                url=(fixture / 'eamonxg-mirror').as_uri(), key=(fixture / 'keys/eamonxg.pem').as_uri())}
            module.snapshot(root, fixture / 'apk-wrapper', repositories)
            record = root / '.external-packages/provenance.json'
            self.assertEqual(len(json.loads(record.read_text())['packages']), 3)
            image = root / 'rootfs'
            pristine = os.environ.get('AURORA_ROOT_FIXTURE')
            self.assertTrue(pristine, 'set AURORA_ROOT_FIXTURE to a pristine verified OpenWrt rootfs')
            assert pristine
            shutil.copytree(pristine, image, symlinks=True,
                            ignore=shutil.ignore_patterns('dev', 'proc', 'sys'))
            before = set((image / 'etc/apk/world').read_text().splitlines())
            command = [str(fixture / 'apk-wrapper'), '--root', str(image), '--keys-dir',
                       str(root / '.external-packages/keys'), '--arch', module.ARCH,
                       '--repositories-file', '/dev/null', '--no-scripts', '--no-logfile', '--no-network',
                       '--repository-config', '@eamonxg ' + (root / '.external-packages/eamonxg/packages.adb').as_uri()]
            wanted = [p + '@eamonxg' for p in module.REPOSITORIES['eamonxg']['packages']]
            subprocess.run(command + ['add', *wanted], check=True, capture_output=True, text=True)
            shutil.copytree(root / 'files', image, dirs_exist_ok=True)
            path = image / 'etc/apk/repositories.d/customfeeds.list'
            path.parent.mkdir(exist_ok=True)
            path.write_text('@eamonxg ' + module.REPOSITORIES['eamonxg']['url'] + '/packages.adb\n')
            module.verify_root(image, record)
            world = set((image / 'etc/apk/world').read_text().splitlines())
            self.assertEqual(world - before, set(wanted))
            self.assertFalse(before - world)
            subprocess.run(command + ['upgrade', '--simulate', 'luci-theme-aurora', 'luci-app-aurora-config'],
                           check=True, capture_output=True, text=True)
            query = [arg for arg in command if arg != '--no-scripts']
            result = subprocess.run(query + ['query', '--fields', 'all', '--format', 'json', '--available', '*'],
                                    check=True, capture_output=True, text=True)
            self.assertIn('luci-theme-aurora', result.stdout)
            path.write_text('file:///builder/private/packages.adb\n')
            with self.assertRaisesRegex(ValueError, 'Build-only'):
                module.verify_root(image, record)

    def test_native_make_refreshes_snapshot_before_cached_rootfs_decision(self):
        fixture = os.environ.get('AURORA_SOURCE_FIXTURE')
        self.assertTrue(fixture)
        assert fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(fixture, root, dirs_exist_ok=True)
            helper().prepare(root)
            text = (root / 'package/Makefile').read_text()
            snapshot = text.split('$(curdir)/aurora-snapshot:')[1].split('\n\n')[0]
            cache = text.split('define rootfs_cache_key\n')[1].split('\nendef')[0]
            stage = root / 'host/bin'
            stage.mkdir(parents=True)
            for name in ('apk', 'tar', 'gzip'):
                (stage / name).write_text('native input\n')
            (root / 'packages').mkdir()
            (root / 'packages/packages.adb').write_text('local package index\n')
            (root / '.config').write_text('CONFIG_USE_APK=y\n')
            (root / 'tmp').mkdir()
            (root / 'tmp/.build').touch()
            script = root / 'snapshot.py'
            script.write_text('''import sys
from pathlib import Path
root=Path(sys.argv[2]); index=root/'.external-packages/eamonxg/packages.adb'
index.parent.mkdir(parents=True,exist_ok=True)
index.write_text(str(int(index.read_text())+1) if index.exists() else '1')
''')
            hash_script = root / 'mkhash'
            hash_script.write_text('#!/bin/sh\n[ "$1" = sha256 ] || exit 1\nsha256sum | cut -d " " -f 1\n')
            hash_script.chmod(0o755)
            makefile = root / 'probe.mk'
            makefile.write_text('TOPDIR:=' + tmp + '\nINCLUDE_DIR:=' + tmp + '/include\n'
                'curdir:=package\nTMP_DIR:=' + tmp + '/tmp\nSTAGING_DIR_HOST:=' + tmp + '/host\n'
                'PACKAGE_DIR_ALL:=' + tmp + '/packages\nMKHASH:=' + str(hash_script) + '\n'
                'define rootfs_cache_key\n' + cache + '\nendef\n'
                '.PHONY: FORCE package/merge-index package/install\n'
                'package/merge-index:\n\t@:\n'
                '$(curdir)/aurora-snapshot:' + snapshot.replace('/cache-scripts/external_packages.py', str(script)) + '\n'
                '$(curdir)/install: $(curdir)/aurora-snapshot\n'
                '\t$(eval ROOTFS_KEY:=$(call rootfs_cache_key,test))\n'
                '\t@echo $(ROOTFS_KEY) > result\n')
            keys = []
            for expected in ('1', '2'):
                result = subprocess.run(['make', '-s', '-f', str(makefile), 'package/install'], cwd=root, check=True,
                                        capture_output=True, text=True)
                self.assertTrue((root / 'result').read_text().strip(), result.stderr + makefile.read_text())
                self.assertEqual((root / '.external-packages/eamonxg/packages.adb').read_text(), expected)
                keys.append((root / 'result').read_text())
            self.assertNotEqual(*keys)


if __name__ == '__main__':
    unittest.main()
