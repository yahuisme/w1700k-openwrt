#!/usr/bin/env python3
"""Replay the shared power patch on pinned full OpenWrt/ImmortalWrt files."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/hostapd-context'
PATCH = ROOT / 'patches/920-wifi-non-mlo-ap-txpower.patch'
HOST = 'package/network/services/hostapd/files/hostapd.uc'


class HostapdContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((FIXTURES / 'manifest.json').read_text())
        cls.files = {}
        for name, record in cls.manifest['files'].items():
            data = gzip.decompress((FIXTURES / (name + '.gz')).read_bytes())
            if hashlib.sha256(data).hexdigest() != record['sha256']:
                raise AssertionError('fixture checksum mismatch: ' + name)
            cls.files[name] = data
        cls.baseline = gzip.decompress((FIXTURES / '920-baseline.patch.gz').read_bytes())
        if hashlib.sha256(cls.baseline).hexdigest() != cls.manifest['baseline_patch_sha256']:
            raise AssertionError('historical patch checksum mismatch')

    def replay(self, host, patch):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ('mac80211.sh', 'generator.uc', host):
                target = work / self.manifest['files'][name]['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.files[name])
            result = subprocess.run([
                'patch', '-p1', '--fuzz=0', '--no-backup-if-mismatch', '--batch'],
                input=patch, cwd=work, capture_output=True)
            self.assertEqual(list(work.rglob('*.orig')), [])
            files = {str(p.relative_to(work)): p.read_bytes()
                     for p in work.rglob('*') if p.is_file() and p.suffix != '.rej'}
            return result, files

    def test_both_distro_sources_accept_patch_without_changing_old_output(self):
        current = PATCH.read_bytes()
        # A context refresh must not change any added or removed source line.
        payload = lambda data: [line for line in data.splitlines()
                                if line.startswith((b'+', b'-'))]
        self.assertEqual(payload(current), payload(self.baseline))
        for host in ('hostapd-old.uc', 'hostapd-current.uc'):
            with self.subTest(host=host):
                result, files = self.replay(host, current)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn(b'fuzz', result.stdout)
                original, previous = self.replay(host, self.baseline)
                if host == 'hostapd-old.uc':
                    # Previous OpenWrt and current ImmortalWrt share these bytes.
                    self.assertEqual(original.returncode, 0, original.stdout + original.stderr)
                    self.assertEqual(files, previous)
                else:
                    self.assertEqual(original.returncode, 1)
                    self.assertIn(b'Hunk #3 FAILED', original.stdout)
                    before = self.files[host].split(b'\tshutdown: function() {', 1)[1].split(b'\n\t},', 1)[0]
                    after = files[HOST].split(b'\tshutdown: function() {', 1)[1].split(b'\n\t},', 1)[0]
                    self.assertEqual(after, before)
                    self.assertIn(b'hostapd.data.obj?.remove();', after)
                    self.assertIn(b'hostapd.data.auth_obj?.remove();', after)
                self.assertIn(b'function bss_txpower(phy, name)', files[HOST])
                self.assertIn(b'bss_txpower(phy, name);', files[HOST])


if __name__ == '__main__':
    unittest.main(verbosity=2)
