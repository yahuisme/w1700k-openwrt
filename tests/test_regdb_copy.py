"""Required regdb copy: direct failure propagation in a private tree."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NAME = '610-w1700k-power-30.patch'


class RegdbCopyTests(unittest.TestCase):
    def fragment(self):
        source = (ROOT / 'user/default/custom.sh').read_text()
        start = source.index('mkdir -p package/firmware/wireless-regdb/patches')
        return source[start:source.index('\necho "=============================================="', start)]

    def test_copy_is_direct(self):
        # The mandatory cp already checks source existence and destination errors.
        self.assertNotIn('if [ -f', self.fragment())

    def test_success_and_failures(self):
        for case in ('success', 'missing-source', 'copy-failure', 'invalid-destination'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                profile = root / 'profile'
                (profile / 'patches').mkdir(parents=True)
                payload = (ROOT / 'user/default/patches' / NAME).read_bytes()
                if case != 'missing-source':
                    (profile / 'patches' / NAME).write_bytes(payload)
                if case == 'invalid-destination':
                    (root / 'package/firmware/wireless-regdb').mkdir(parents=True)
                    (root / 'package/firmware/wireless-regdb/patches').write_text('blocked')
                prefix = 'cp() { return 74; };\n' if case == 'copy-failure' else ''
                result = subprocess.run(['bash', '-ec', prefix + self.fragment() + '\necho CONTINUED'],
                                        cwd=root, env=dict(os.environ, DK_PROFILE=str(profile)),
                                        text=True, capture_output=True)
                if case == 'success':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('CONTINUED', result.stdout)
                    self.assertEqual((root / 'package/firmware/wireless-regdb/patches' / NAME).read_bytes(), payload)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('CONTINUED', result.stdout)
                    self.assertNotIn('regdb patch:', result.stdout)
