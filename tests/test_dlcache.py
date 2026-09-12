#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/dlcache.py'


class DownloadCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dlcache-', dir=ROOT / 'tests')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.dl = self.base / 'dlcache'
        self.dl.mkdir()
        self.state = self.base / 'before.json'

    def run_helper(self, mode, restored='dl-v3.previous'):
        args = [sys.executable, str(HELPER), mode, str(self.dl), str(self.state)]
        if mode == 'check':
            args += ['--restored', restored]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_hot_unchanged(self):
        (self.dl / 'source.tar').write_bytes(b'source')
        self.run_helper('snapshot')
        self.assertEqual(self.run_helper('check'), 'save=false')

    def test_cold_nonempty_even_without_changes(self):
        (self.dl / 'legacy.tar').write_bytes(b'legacy')
        self.run_helper('snapshot')
        self.assertEqual(self.run_helper('check', ''), 'save=true')

    def test_empty_cold_and_hot(self):
        (self.dl / 'empty-directory').mkdir()
        self.run_helper('snapshot')
        for restored in ('', 'dl-v3.previous'):
            self.assertEqual(self.run_helper('check', restored), 'save=false')

    def test_add_delete_modify_rename_and_mtime(self):
        source = self.dl / 'source.tar'
        source.write_bytes(b'abcd')
        module = self.dl / 'go-mod-cache/cache/download/module/@v'
        for change in ('mtime', 'modify', 'add', 'delete', 'rename'):
            with self.subTest(change=change):
                self.run_helper('snapshot')
                if change == 'mtime':
                    os.utime(source, (100, 100))
                elif change == 'modify':
                    source.write_bytes(b'efgh')
                    os.utime(source, (100, 100))
                elif change == 'add':
                    module.mkdir(parents=True)
                    (module / 'v1.zip').write_bytes(b'compile-time download')
                elif change == 'delete':
                    source.unlink()
                else:
                    module.rename(module.with_name('renamed'))
                self.assertEqual(self.run_helper('check'),
                                 'save=false' if change == 'mtime' else 'save=true')

    def test_delete_last_file_skips(self):
        source = self.dl / 'source.tar'
        source.write_bytes(b'')
        self.run_helper('snapshot')
        source.unlink()
        self.assertEqual(self.run_helper('check'), 'save=false')

    def test_zero_byte_file_is_nonempty_cache(self):
        self.run_helper('snapshot')
        (self.dl / 'zero').touch()
        self.assertEqual(self.run_helper('check', ''), 'save=true')

    def test_symlink_fails_closed(self):
        (self.dl / 'linked').symlink_to(self.base)
        result = subprocess.run([sys.executable, str(HELPER), 'snapshot',
                                 str(self.dl), str(self.state)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'unsupported linked download', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
