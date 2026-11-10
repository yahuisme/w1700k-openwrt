"""Verify the final FIT's embedded newc bytes, not a staging rootfs only."""
import hashlib
import io
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import installer_payload
from installer_fit_fixture import make_fit


class EmbeddedInstaller(unittest.TestCase):
    def fixture(self, work, fault=''):
        files = work / 'files'; files.mkdir()
        content = {'installer/install.sh': b'#!/bin/sh\nexit 0\n',
                   'lib/preinit/00_installer': b'/installer/install.sh\n',
                   'installer/sysupgrade.itb': b'formal-sysupgrade',
                   'installer/recovery.itb': b'formal-recovery'}
        expected = {}
        for name, data in content.items():
            path = files / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data); path.chmod(0o755 if not name.endswith('.itb') else 0o644)
            expected[name] = 'sha256:' + hashlib.sha256(data).hexdigest()
        if fault == 'changed': (files / 'installer/sysupgrade.itb').write_bytes(b'wrong-sysupgrade')
        if fault == 'missing': (files / 'installer/recovery.itb').unlink()
        if fault == 'nonexecutable': (files / 'installer/install.sh').chmod(0o644)
        if fault == 'symlink':
            (files / 'installer/recovery.itb').unlink()
            (files / 'installer/recovery.itb').symlink_to('sysupgrade.itb')
        names = sorted(str(p.relative_to(files)) for p in files.rglob('*'))
        if fault == 'duplicate': names.append('installer/install.sh')
        cpio = subprocess.check_output(['cpio', '--quiet', '-o', '-H', 'newc'],
                                       input=('\n'.join(names)+'\n').encode(), cwd=files)
        if fault in ('nested', 'symlink-nested'):
            (files / 'carrier').write_bytes(cpio)
            if fault == 'symlink-nested':
                (files / 'installer/install.sh').unlink()
                (files / 'installer/install.sh').symlink_to('../carrier')
                names = ['installer/install.sh', 'carrier']
            else:
                names = ['carrier']
            cpio = subprocess.check_output(['cpio', '--quiet', '-o', '-H', 'newc'],
                                           input=('\n'.join(names)+'\n').encode(), cwd=files)
        if fault == 'later-overlay':
            (files / 'installer/install.sh').write_bytes(b'wrong later overlay')
            cpio += subprocess.check_output(['cpio', '--quiet', '-o', '-H', 'newc'],
                                            input=b'installer/install.sh\n', cwd=files)
        if fault == 'truncated': cpio = cpio[:-1024]
        kernel = b'fake arm64 kernel header\0' + b'070701 not an archive\0'
        kernel += bytes((-len(kernel)) % 4) + cpio
        fit = work / 'fit'; fit.mkdir()
        image = work / 'installer.itb'
        compressed = lzma.compress(kernel, format=lzma.FORMAT_ALONE)
        if fault == 'compressed-truncated': compressed = compressed[:-8]
        image.write_bytes(make_fit(fit, external=False, kernel=compressed))
        return image, expected

    def test_final_fit_matches_every_frozen_input(self):
        verify = getattr(installer_payload, 'verify_embedded', None)
        self.assertTrue(callable(verify), 'missing final installer content verification')
        for fault in ('', 'changed', 'missing', 'nonexecutable', 'symlink', 'duplicate', 'truncated', 'compressed-truncated', 'nested', 'symlink-nested', 'later-overlay'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                image, expected = self.fixture(Path(tmp), fault)
                if fault:
                    with self.assertRaises(ValueError): verify(image, expected)
                else:
                    verify(image, expected)
