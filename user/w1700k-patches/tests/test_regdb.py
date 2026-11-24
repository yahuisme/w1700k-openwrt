"""Unified regdb delta must preserve both previous complete databases."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest
from migration_baseline import migration_files

ROOT = Path(__file__).resolve().parents[1]
NAME = '610-w1700k-power-30.patch'


class UniversalRegdb(unittest.TestCase):
    def test_single_payload(self):
        self.assertTrue((ROOT / 'patches' / NAME).is_file())
        self.assertFalse((ROOT / 'openwrt').exists())
        self.assertFalse((ROOT / 'immortalwrt').exists())

    def test_both_complete_databases_unchanged(self):
        archive = Path(os.environ['REGDB_ARCHIVE'])
        shared = ROOT / 'patches' / NAME
        baseline = migration_files()
        results = []
        for distro, old_sha in [('openwrt', 'b527db7ab1f918f0467056c50c332cafe31df7c8'),
                               ('immortalwrt', 'b61b737b26b06b1be1085f356c761cb516aa618e')]:
            source = Path(os.environ['REGDB_SOURCE_' + distro.upper()])
            recipe = (source / 'package/firmware/wireless-regdb/Makefile').read_text()
            match = re.search(r'^PKG_HASH:=([0-9a-f]{64})$', recipe, re.M)
            assert match is not None
            expected = match[1]
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), expected)
            repo = os.environ.get('W1700K_' + distro.upper() + '_REPO')
            if repo is not None:
                old_patch = subprocess.check_output(['git', '-C', repo, 'show',
                                                     f'{old_sha}:user/default/patches/{NAME}'])
            else:
                old_patch = baseline[f'{distro}/{NAME}']
            with tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                old = base / 'old'; new = base / 'new'
                for target in (old, new):
                    target.mkdir()
                    with tarfile.open(archive) as tf:
                        member = next(m for m in tf.getmembers() if m.name.endswith('/db.txt'))
                        stream = tf.extractfile(member)
                        assert stream is not None
                        (target / 'db.txt').write_bytes(stream.read())
                (base / 'old.patch').write_bytes(old_patch)
                official = source / 'package/firmware/wireless-regdb/patches'
                for patch in sorted(official.glob('*.patch')):
                    self.apply(old, patch)
                    if patch.name != '600-custom-change-txpower-and-dfs.patch':
                        self.apply(new, patch)
                self.apply(old, base / 'old.patch')
                self.apply(new, shared)
                self.assertEqual((old / 'db.txt').read_bytes(), (new / 'db.txt').read_bytes(), distro)
                results.append((new / 'db.txt').read_bytes())
        self.assertEqual(*results)

    def apply(self, root, patch):
        result = subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '-i', str(patch)],
                                cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
