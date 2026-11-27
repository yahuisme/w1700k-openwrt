#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import cache_recovery, dlcache

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/dlcache.py'


class DownloadCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dlcache-')
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

    def test_cold_seed_checks_types_without_hashing_file_contents(self):
        self.run_helper('prepare')
        (self.dl / 'source.tar').write_bytes(b'new source')
        with patch.object(dlcache.hashlib, 'file_digest', wraps=dlcache.hashlib.file_digest) as digest:
            self.assertTrue(dlcache.changed(self.dl, self.state, ''))
            digest.assert_not_called()
            self.assertTrue(dlcache.changed(self.dl, self.state, 'dl-v3.previous'))
            digest.assert_called_once()
        os.mkfifo(self.dl / 'unexpected')
        with self.assertRaisesRegex(ValueError, 'unsupported download item'):
            dlcache.changed(self.dl, self.state, '')

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

    def test_missing_or_invalid_baseline_disables_save_before_reading_cache(self):
        # The post-build tree is deliberately unfingerprintable; with no usable
        # state we should skip that work entirely, even on a cold raw restore.
        (self.dl / 'linked').symlink_to(self.base)
        for invalid in ('missing', '{', '{}'):
            with self.subTest(state=invalid):
                if invalid != 'missing':
                    self.state.write_text(invalid)
                self.assertEqual(self.run_helper('check', ''), 'save=false')

    def test_prepare_keeps_healthy_input_and_reseeds_after_cold_recovery(self):
        source = self.dl / 'source.tar'
        source.write_bytes(b'warm input')
        self.run_helper('prepare')
        self.assertEqual(source.read_bytes(), b'warm input')
        self.assertEqual(json.loads(self.state.read_text())['files'], 1)
        self.assertEqual(self.run_helper('check'), 'save=false')

        sentinel = self.base / 'untouched'
        sentinel.write_bytes(b'protected')
        (self.dl / 'linked').symlink_to(sentinel)
        result = subprocess.run([sys.executable, str(HELPER), 'prepare', str(self.dl), str(self.state)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unsupported linked download', result.stderr)
        self.assertEqual(list(self.dl.iterdir()), [])
        self.assertEqual(sentinel.read_bytes(), b'protected')
        self.assertEqual(json.loads(self.state.read_text())['files'], 0)
        self.assertEqual(self.run_helper('check'), 'save=false')
        source.write_bytes(b'new upstream download')
        self.assertEqual(self.run_helper('check'), 'save=true')

    def test_prepare_rejects_nonregular_download_and_root_items(self):
        os.mkfifo(self.dl / 'unexpected')
        self.run_helper('prepare')
        self.assertEqual(list(self.dl.iterdir()), [])
        self.dl.rmdir()
        self.dl.write_text('not a download directory')
        self.run_helper('prepare')
        self.assertTrue(self.dl.is_dir())
        self.assertEqual(list(self.dl.iterdir()), [])

    def test_prepare_unrecordable_state_leaves_cold_input_and_no_save(self):
        source = self.dl / 'source.tar'
        source.write_bytes(b'warm input')
        self.state.mkdir()  # Real state-write collision, independent of root privileges.
        result = subprocess.run([sys.executable, str(HELPER), 'prepare', str(self.dl), str(self.state)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('snapshot unavailable', result.stderr)
        self.assertEqual(list(self.dl.iterdir()), [])
        source.write_bytes(b'new upstream download')
        self.assertEqual(self.run_helper('check', ''), 'save=false')

    def test_failed_recovery_propagates_cleanup_error_and_invalidates_old_state(self):
        self.run_helper('snapshot')
        (self.dl / 'broken').symlink_to('missing')
        with patch.object(cache_recovery.shutil, 'rmtree', side_effect=PermissionError('cleanup denied')):
            with self.assertRaisesRegex(PermissionError, 'cleanup denied'):
                dlcache.prepare(self.dl, self.state)
        self.assertFalse(self.state.exists())
        self.assertTrue((self.dl / 'broken').is_symlink())

    def test_post_build_fingerprint_failure_is_reported_with_valid_baseline(self):
        self.run_helper('prepare')
        (self.dl / 'broken').symlink_to('missing')
        result = subprocess.run([sys.executable, str(HELPER), 'check', str(self.dl), str(self.state)],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported linked download', result.stderr)
        self.assertNotIn('save=true', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
