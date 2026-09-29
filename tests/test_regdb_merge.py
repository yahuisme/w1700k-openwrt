"""Single local regdb delta, with an optional exact-source application check."""
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'user/default'
PATCH = PROFILE / 'patches/610-w1700k-cn-us-power-30.patch'


class RegdbMergeTests(unittest.TestCase):
    def test_single_local_delta(self):
        self.assertFalse((PROFILE / 'tree/package/firmware/wireless-regdb/patches/555-w1700k-fix.patch').exists())
        text = PATCH.read_text()
        self.assertIn('+\t(5730 - 5895 @ 160), (30), AUTO-BW', text)
        self.assertIn('+\t(5925 - 7125 @ 320), (30), NO-OUTDOOR', text)

    @unittest.skipUnless(os.environ.get('REGDB_ARCHIVE') and os.environ.get('OPENWRT_SOURCE'),
                         'requires exact regdb archive and prepared official source')
    def test_exact_source_matches_previous_result(self):
        archive = Path(os.environ['REGDB_ARCHIVE'])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         '8a27bfc081bafed8c24dd70fab0d96f098e5a0bfcd08d3da672595f225ab8993')
        source = Path(os.environ['OPENWRT_SOURCE'])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'db.txt'
            with tarfile.open(archive) as tf:
                member = next(m for m in tf.getmembers() if m.name.endswith('/db.txt'))
                stream = tf.extractfile(member)
                assert stream is not None
                target.write_bytes(stream.read())
            official = source / 'package/firmware/wireless-regdb/patches/500-world-regd-5GHz.patch'
            for patch in (official, PATCH):
                result = subprocess.run(['patch', '-p1', '--fuzz=0', '-i', str(patch)],
                                        cwd=tmp, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('offset', result.stdout)
            # Recorded from official 500 + the original 555 + original 610.
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),
                             '6f5038045809ced25535b0faeb96bba75905d1b0afaf3262423839ed5406e918')
