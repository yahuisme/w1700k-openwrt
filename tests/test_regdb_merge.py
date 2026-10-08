"""Single local regdb delta, with an optional exact-source application check."""
import hashlib
import os
import re
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
    def test_exact_source_preserves_unrelated_regdb(self):
        archive = Path(os.environ['REGDB_ARCHIVE'])
        source = Path(os.environ['OPENWRT_SOURCE'])
        recipe = (source / 'package/firmware/wireless-regdb/Makefile').read_text()
        expected = re.search(r'^PKG_HASH:=([0-9a-f]{64})$', recipe, re.M)
        assert expected is not None
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), expected[1])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'db.txt'
            with tarfile.open(archive) as tf:
                member = next(m for m in tf.getmembers() if m.name.endswith('/db.txt'))
                stream = tf.extractfile(member)
                assert stream is not None
                target.write_bytes(stream.read())
            official = source / 'package/firmware/wireless-regdb/patches/500-world-regd-5GHz.patch'
            before = None
            for patch in (official, PATCH):
                if patch == PATCH:
                    before = target.read_text()
                result = subprocess.run(['patch', '--batch', '-p1', '--fuzz=0', '-i', str(patch)],
                                        cwd=tmp, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            def countries(text):
                return {code: block for block, code in re.findall(
                    r'(^country ([A-Z0-9]+):.*?)(?=^country |\Z)', text, re.M | re.S)}
            assert before is not None
            old, new = countries(before), countries(target.read_text())
            self.assertEqual(set(old), set(new))
            for country in old:
                if country not in ('CN', 'US'):
                    self.assertEqual(old[country], new[country], country)
            self.assertIn('(5730 - 5895 @ 160), (30), AUTO-BW', new['US'])
            self.assertIn('(5925 - 7125 @ 320), (30), NO-OUTDOOR', new['US'])
            self.assertIn('(2400 - 2483.5 @ 40), (30)', new['CN'])
