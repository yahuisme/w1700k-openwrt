"""Exercise incremental image assembly with inert make and fwtool boundaries."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


class InstallerBuild(unittest.TestCase):
    def test_same_build_payload_and_formal_inputs_survive_outer_build(self):
        script = ROOT / 'scripts/build_installer.py'
        self.assertTrue(script.is_file(), 'missing native incremental installer assembly')
        spec = importlib.util.spec_from_file_location('build_installer', script)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        for fail in (False, True, 'stale-rootfs', 'restore-failure'):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / 'source'; source.mkdir()
                subprocess.run(['git', 'init', '-q', str(source)], check=True)
                subprocess.run(['git', '-C', str(source), '-c', 'user.name=fixture', '-c',
                                'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture', '--allow-empty'], check=True)
                installer = Path(tmp) / 'installer'
                for path in ('installer/install.sh', 'lib/preinit/00_installer'):
                    target = installer / 'files' / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('#!/bin/sh\nexit 0\n')
                (source / 'files').mkdir()
                (source / 'files/formal').write_bytes(b'formal-overlay')
                (source / 'files/etc/apk/repositories.d').mkdir(parents=True)
                (source / 'files/etc/apk/repositories.d/customfeeds.list').write_text('@eamonxg https://fixture.invalid/packages.adb\n')
                (source / 'files/etc/apk/keys').mkdir(parents=True)
                (source / 'files/etc/apk/keys/eamonxg.pem').write_bytes(b'signing-key')
                package_make = source / 'package/Makefile'
                package_make.parent.mkdir()
                original_make = '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n'
                package_make.write_text(original_make)
                (source / '.external-packages').mkdir()
                (source / '.external-packages/provenance.json').write_text('{"frozen":true}')
                (source / '.config').write_bytes(b'formal-config\n')
                profile = json.loads((ROOT / 'user/default/build.json').read_text())
                prefix = profile['system'] + '-airoha-an7581-gemtek_w1700k-ubi-'
                names = [prefix + s + '.itb' for s in ('squashfs-sysupgrade', 'initramfs-recovery', 'chainload-uboot')]
                directory = source / 'bin/targets' / profile['target']; directory.mkdir(parents=True)
                for name in names:
                    (directory / name).write_bytes(name.encode())
                def manifest():
                    rows = [dict(name=name, size=(directory / name).stat().st_size,
                                 sha256=hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                                 type='initramfs' if 'recovery' in name else 'chainload-uboot' if 'chainload' in name else 'sysupgrade') for name in names]
                    (directory / 'profiles.json').write_text(json.dumps({'profiles': {'gemtek_w1700k-ubi': {'images': rows}}}))
                manifest()
                original = {p.name: p.read_bytes() for p in directory.iterdir()}
                real_run = subprocess.run
                def run(command, **kwargs):
                    if command[0] == 'git':
                        return real_run(command, **kwargs)
                    if 'fwtool' in str(command[0]):
                        Path(command[2]).write_text('{}')
                        return subprocess.CompletedProcess(command, 0)
                    self.assertEqual(command[0], 'make')
                    self.assertEqual(kwargs['env']['FORCE_UNSAFE_CONFIGURE'], '1')
                    self.assertNotIn('external_packages.py snapshot', (source / 'package/Makefile').read_text())
                    self.assertEqual((source / 'files/etc/apk/keys/eamonxg.pem').read_bytes(), b'signing-key')
                    self.assertIn('@eamonxg', (source / 'files/etc/apk/repositories.d/customfeeds.list').read_text())
                    self.assertFalse((source / 'files/formal').exists())
                    for name in names[:2]:
                        self.assertEqual((source / 'files/installer' / name).read_bytes(), original[name])
                    self.assertEqual((source / '.config').read_bytes(), b'formal-config\n')
                    if fail == 'stale-rootfs':
                        return subprocess.CompletedProcess(command, 0)
                    roots = source / 'build_dir/target-test/root-airoha'
                    roots.mkdir(parents=True, exist_ok=True)
                    __import__('shutil').copytree(source / 'files', roots, dirs_exist_ok=True)
                    (directory / names[0]).write_bytes(b'outer-not-production')
                    (directory / names[1]).write_bytes(b'outer-installer')
                    (directory / names[2]).write_bytes(b'outer-chainloader')
                    manifest()
                    if fail is True:
                        raise subprocess.CalledProcessError(9, command)
                    if fail == 'restore-failure':
                        def copytree(a, b, **kw):
                            if str(a).endswith('/formal-target'):
                                raise OSError('injected restore failure')
                            return original_copy(a, b, **kw)
                        helper.shutil.copytree = copytree
                    return subprocess.CompletedProcess(command, 0)
                original_copy = helper.shutil.copytree
                with patch.object(helper, 'verify_fit'), patch.object(helper, 'verify_metadata'), \
                     patch.object(helper.shutil, 'copytree', side_effect=lambda *a, **k: original_copy(*a, **k)), \
                     patch.object(helper.subprocess, 'run', side_effect=run):
                    if fail == 'restore-failure':
                        with self.assertRaisesRegex(OSError, 'restore failure'):
                            helper.build(source, installer, profile)
                    elif fail == 'stale-rootfs':
                        with self.assertRaises(ValueError):
                            helper.build(source, installer, profile)
                    elif fail:
                        with self.assertRaises(subprocess.CalledProcessError):
                            helper.build(source, installer, profile)
                    else:
                        helper.build(source, installer, profile)
                self.assertEqual(package_make.read_text(), original_make)
                self.assertEqual((source / '.external-packages/provenance.json').read_text(), '{"frozen":true}')
                self.assertEqual((source / '.config').read_bytes(), b'formal-config\n')
                self.assertEqual((source / 'files/formal').read_bytes(), b'formal-overlay')
                self.assertFalse((source / 'files/installer').exists())
                if fail == 'restore-failure':
                    backups = list(source.glob('.installer-*/formal-target'))
                    self.assertEqual(len(backups), 1)
                    for name, data in original.items():
                        self.assertEqual((backups[0] / name).read_bytes(), data)
                    continue
                for name, data in original.items():
                    self.assertEqual((directory / name).read_bytes(), data)
                output = directory / (prefix + 'initramfs-installer.itb')
                if fail:
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(output.read_bytes(), b'outer-installer')
                    proof = json.loads((directory / 'installer.json').read_text())
                    self.assertEqual(proof['payload']['digest'], 'sha256:' + hashlib.sha256(original[names[0]]).hexdigest())
                    self.assertEqual(proof['images'][0]['digest'], 'sha256:' + hashlib.sha256(b'outer-installer').hexdigest())
