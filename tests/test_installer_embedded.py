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


def rewrite_newc(archive, edit):
    """Edit explicit newc records without GNU cpio hardlink normalization."""
    records, position = [], 0
    while True:
        header = archive[position:position + 110]
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        name = archive[position + 110:position + 110 + fields[11] - 1].decode()
        body = (position + 110 + fields[11] + 3) & ~3
        records.append((fields, name, archive[body:body + fields[6]]))
        position = (body + fields[6] + 3) & ~3
        if name == 'TRAILER!!!': break
    result = bytearray()
    for fields, name, data in edit(records[:-1]) + records[-1:]:
        fields = fields.copy()
        encoded = name.encode() + b'\0'
        fields[6], fields[11] = len(data), len(encoded)
        result += b'070701' + ''.join(f'{value:08x}' for value in fields).encode() + encoded
        result += bytes((-len(result)) % 4) + data
        result += bytes((-len(result)) % 4)
    return bytes(result)


class EmbeddedInstaller(unittest.TestCase):
    def fixture(self, work, fault='', paths=None, archive=None):
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
        if archive is not None: cpio = rewrite_newc(cpio, archive)
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
        for root in (None, '.', './'):
            for prefix in ('', './'):
                with self.subTest(root=root, prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                    def edit(records):
                        fields = next(fields for fields, name, data in records
                                      if name.removeprefix('./') == 'installer/recovery.itb').copy()
                        fields[0] ^= 0x80000000
                        return records + [(fields, prefix + 'root-input', b'root-level frozen input')]
                    image, expected = self.fixture(
                        Path(tmp), paths=lambda names, content, files:
                        ([] if root is None else [root]) + [prefix + name for name in names], archive=edit)
                    expected['root-input'] = 'sha256:' + hashlib.sha256(b'root-level frozen input').hexdigest()
                    installer_payload.verify_fit(image)
                    installer_payload.verify_embedded(image, expected)

    def test_frozen_inputs_require_single_link(self):
        targets = ('installer/install.sh', 'lib/preinit/00_installer',
                   'installer/sysupgrade.itb', 'installer/recovery.itb',
                   'installer/payload.sha256')
        for target in targets:
            for nlink in (0, 2):
                with self.subTest(target=target, nlink=nlink), tempfile.TemporaryDirectory() as tmp:
                    def edit(records):
                        for fields, name, data in records:
                            if name == target: fields[4] = nlink
                        return records
                    image, expected = self.fixture(Path(tmp), archive=edit)
                    installer_payload.verify_fit(image)
                    with self.assertRaisesRegex(ValueError, 'Hardlinked embedded input: ' + target):
                        installer_payload.verify_embedded(image, expected)

    def test_frozen_identities_cannot_join_hardlink_groups(self):
        targets = ('installer/install.sh', 'lib/preinit/00_installer',
                   'installer/sysupgrade.itb', 'installer/recovery.itb',
                   'installer/payload.sha256')
        for target in targets:
            for nlink in (1, 2):
                for before in (True, False):
                    for body in (b'', b'overwritten through another pathname\n'):
                        with self.subTest(target=target, nlink=nlink, before=before, body=body), tempfile.TemporaryDirectory() as tmp:
                            def edit(records):
                                fields = next(fields for fields, name, data in records if name == target)
                                fields[4] = nlink
                                linked = fields.copy(); linked[4] = 2
                                linked[1] ^= 0o077  # Permissions do not separate Linux hardlink groups.
                                alias = (linked, 'installer/link-alias', body)
                                return [alias] + records if before else records + [alias]
                            image, expected = self.fixture(Path(tmp), archive=edit)
                            installer_payload.verify_fit(image)
                            with self.assertRaisesRegex(ValueError, 'Hardlink.*embedded input'):
                                installer_payload.verify_embedded(image, expected)

    def test_native_unrelated_hardlinks_and_distinct_identities(self):
        # Kernel hardlink keys use device, inode and file type, not permissions.
        for difference in ('unrelated', 'devmajor', 'devminor', 'type', 'single-link'):
            with self.subTest(difference=difference), tempfile.TemporaryDirectory() as tmp:
                def edit(records):
                    fields = next(fields for fields, name, data in records if name == 'installer/install.sh').copy()
                    fields[4] = 2
                    if difference == 'unrelated': fields[0] ^= 0x80000000
                    if difference == 'devmajor': fields[7] ^= 1
                    if difference == 'devminor': fields[8] ^= 1
                    if difference == 'type': fields[1] = 0o020600
                    if difference == 'single-link': fields[4] = 1
                    alias_body = b'' if difference == 'type' else b'native hardlink contents\n'
                    return records + [(fields, 'installer/link-a', b''),
                                      (fields.copy(), 'installer/link-b', alias_body)]
                image, expected = self.fixture(Path(tmp), archive=edit)
                installer_payload.verify_fit(image)
                installer_payload.verify_embedded(image, expected)

    def test_rejects_canonical_duplicate_paths(self):
        targets = ('installer/install.sh', 'lib/preinit/00_installer',
                   'installer/sysupgrade.itb', 'installer/recovery.itb',
                   'installer/payload.sha256', 'installer', 'lib', 'lib/preinit')
        for target in targets:
            for prefix in ('', './'):
                for mode in (0o100755, 0o040755, 0o120777):
                    with self.subTest(target=target, prefix=prefix, mode=oct(mode)), tempfile.TemporaryDirectory() as tmp:
                        def edit(records):
                            fields = next(fields for fields, name, data in records if name == target).copy()
                            fields[1], fields[4] = mode, 1
                            return records + [(fields, prefix + target, b'')]
                        image, expected = self.fixture(Path(tmp), archive=edit)
                        installer_payload.verify_fit(image)
                        with self.assertRaisesRegex(ValueError, 'Duplicate embedded newc path: ' + target):
                            installer_payload.verify_embedded(image, expected)

    def test_frozen_parent_entries_must_remain_directories(self):
        for parent in ('installer', 'lib', 'lib/preinit'):
            for before in (True, False):
                for mode, body in ((0o100644, b''), (0o120777, b'elsewhere'),
                                   (0o020600, b''), (0o040755, b'not a directory record')):
                    with self.subTest(parent=parent, before=before, mode=oct(mode)), tempfile.TemporaryDirectory() as tmp:
                        def edit(records):
                            fields = next(fields for fields, name, data in records if name == parent).copy()
                            fields[1], fields[4] = mode, 1
                            records = [record for record in records if record[1] != parent]
                            replacement = (fields, parent, body)
                            return [replacement] + records if before else records + [replacement]
                        image, expected = self.fixture(Path(tmp), archive=edit)
                        installer_payload.verify_fit(image)
                        diagnostic = ('Non-directory embedded input parent: ' + parent if before else
                                      'Missing/late embedded input parent: ')
                        with self.assertRaisesRegex(ValueError, diagnostic):
                            installer_payload.verify_embedded(image, expected)

    def test_frozen_parent_directories_must_precede_children(self):
        for parent in ('installer', 'lib', 'lib/preinit'):
            for fault in ('missing', 'late'):
                with self.subTest(parent=parent, fault=fault), tempfile.TemporaryDirectory() as tmp:
                    def edit(records):
                        directory = next(record for record in records if record[1] == parent)
                        remaining = [record for record in records if record[1] != parent]
                        return remaining if fault == 'missing' else remaining + [directory]
                    image, expected = self.fixture(Path(tmp), archive=edit)
                    installer_payload.verify_fit(image)
                    with self.assertRaisesRegex(ValueError, 'Missing/late embedded input parent: '):
                        installer_payload.verify_embedded(image, expected)

    def test_frozen_parent_directory_requires_its_own_parent_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            def edit(records):
                preinit = next(record for record in records if record[1] == 'lib/preinit')
                lib = next(record for record in records if record[1] == 'lib')
                return [preinit, lib] + [record for record in records if record[1] not in ('lib', 'lib/preinit')]
            image, expected = self.fixture(Path(tmp), archive=edit)
            installer_payload.verify_fit(image)
            with self.assertRaisesRegex(ValueError, 'Missing/late embedded input parent: lib/preinit'):
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
