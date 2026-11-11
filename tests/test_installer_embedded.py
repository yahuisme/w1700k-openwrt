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
    def fixture(self, work, fault='', paths=None):
        files = work / 'files'; files.mkdir()
        content = {'installer/install.sh': b'#!/bin/sh\nexit 0\n',
                   'lib/preinit/00_installer': b'/installer/install.sh\n',
                   'installer/sysupgrade.itb': b'formal-sysupgrade',
                   'installer/recovery.itb': b'formal-recovery'}
        content['installer/payload.sha256'] = ''.join(
            hashlib.sha256(content['installer/' + name]).hexdigest() + '  ' + name + '\n'
            for name in ('sysupgrade.itb', 'recovery.itb')).encode()
        expected = {}
        for name, data in content.items():
            path = files / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data); path.chmod(0o755 if name in ('installer/install.sh', 'lib/preinit/00_installer') else 0o644)
            expected[name] = 'sha256:' + hashlib.sha256(data).hexdigest()
        if fault == 'changed': (files / 'installer/sysupgrade.itb').write_bytes(b'wrong-sysupgrade')
        if fault == 'missing': (files / 'installer/recovery.itb').unlink()
        if fault == 'manifest-changed': (files / 'installer/payload.sha256').write_bytes(b'changed')
        if fault == 'manifest-missing': (files / 'installer/payload.sha256').unlink()
        if fault == 'nonexecutable': (files / 'installer/install.sh').chmod(0o644)
        if fault == 'symlink':
            (files / 'installer/recovery.itb').unlink()
            (files / 'installer/recovery.itb').symlink_to('sysupgrade.itb')
        names = sorted(str(p.relative_to(files)) for p in files.rglob('*'))
        if paths is not None: names = paths(names, content, files)
        if fault == 'duplicate': names.append('installer/install.sh')
        if fault == 'manifest-duplicate': names.append('installer/payload.sha256')
        cpio = subprocess.check_output(['cpio', '--quiet', '--absolute-filenames', '-o', '-H', 'newc'],
                                       input=('\n'.join(names)+'\n').encode(), cwd=files)
        if paths is not None:
            # GNU cpio strips leading ./; restore requested spellings so the
            # matrix tests archive names, not cpio's input normalization.
            records, position = [], 0
            for name in names:
                header = bytearray(cpio[position:position + 110])
                size = int(header[54:62], 16)
                namesize = int(header[94:102], 16)
                body = (position + 110 + namesize + 3) & ~3
                encoded = name.encode() + bytes(1)
                header[94:102] = f'{len(encoded):08x}'.encode()
                record = bytes(header) + encoded
                record += bytes((-len(record)) % 4) + cpio[body:body + size]
                records.append(record + bytes((-len(record)) % 4))
                position = (body + size + 3) & ~3
            cpio = b''.join(records) + cpio[position:]
        if fault in ('nested', 'symlink-nested'):
            (files / 'carrier').write_bytes(cpio)
            if fault == 'symlink-nested':
                (files / 'installer/install.sh').unlink()
                (files / 'installer/install.sh').symlink_to('../carrier')
                names = ['installer/install.sh', 'carrier']
            else:
                names = ['carrier']
            cpio = subprocess.check_output(['cpio', '--quiet', '--absolute-filenames', '-o', '-H', 'newc'],
                                           input=('\n'.join(names)+'\n').encode(), cwd=files)
        if fault == 'later-overlay':
            (files / 'installer/install.sh').write_bytes(b'wrong later overlay')
            cpio += subprocess.check_output(['cpio', '--quiet', '--absolute-filenames', '-o', '-H', 'newc'],
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

    def test_rejects_path_alias_matrix(self):
        aliases = {
            'internal-dot': lambda name, files: name.replace('/', '/./', 1),
            'double-slash': lambda name, files: name.replace('/', '//', 1),
            'parent': lambda name, files: 'installer/../' + name,
            'absolute': lambda name, files: str(files / name),
            'repeated-dot': lambda name, files: '././' + name,
        }
        targets = ('installer/install.sh', 'lib/preinit/00_installer',
                   'installer/sysupgrade.itb', 'installer/recovery.itb',
                   'installer/payload.sha256')
        for target in targets:
            for kind, alias in aliases.items():
                for before in (True, False):
                    with self.subTest(target=target, kind=kind, before=before), tempfile.TemporaryDirectory() as tmp:
                        alias_name = alias(target, Path(tmp) / 'files')
                        def paths(names, content, files):
                            self.assertEqual(set(targets), set(content))
                            return [alias_name] + names if before else names + [alias_name]
                        image, expected = self.fixture(Path(tmp), paths=paths)
                        installer_payload.verify_fit(image)
                        with self.assertRaises(ValueError) as caught:
                            installer_payload.verify_embedded(image, expected)
                        self.assertEqual(str(caught.exception),
                                         'Invalid embedded newc path: ' + alias_name.removeprefix('./'))

    def test_native_root_and_single_dot_prefix(self):
        for root in ('.', './'):
            for prefix in ('', './'):
                with self.subTest(root=root, prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                    image, expected = self.fixture(
                        Path(tmp), paths=lambda names, content, files: [root] + [prefix + name for name in names])
                    installer_payload.verify_fit(image)
                    installer_payload.verify_embedded(image, expected)

    def test_final_fit_matches_every_frozen_input(self):
        verify = getattr(installer_payload, 'verify_embedded', None)
        self.assertTrue(callable(verify), 'missing final installer content verification')
        for fault in ('', 'changed', 'missing', 'nonexecutable', 'symlink', 'duplicate', 'truncated', 'compressed-truncated', 'nested', 'symlink-nested', 'later-overlay',
                      'manifest-changed', 'manifest-missing', 'manifest-duplicate'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                image, expected = self.fixture(Path(tmp), fault)
                if fault:
                    with self.assertRaises(ValueError): verify(image, expected)
                else:
                    verify(image, expected)
