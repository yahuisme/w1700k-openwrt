"""Execute the production required-payload preflight in an isolated shell."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
from patch_source import PATCHES

NEW = ('912-mt76-mt7996-use-mcu-station-statistics.patch',
       '913-mt76-mt7996-clean-up-truncated-txfree.patch',
       '914-mt76-mt7996-free-rro-drop-buffers.patch')


class Mt76PayloadTests(unittest.TestCase):
    def preflight(self, broken=None, empty=False):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        start = custom.index('# Required patches')
        end = custom.index('cp -a --no-preserve=ownership', start)
        block = custom[start:end]
        names = re.findall(r'    ((?:tree|patches)/[^ ]+\.patch)', block)
        self.assertEqual(set(names), {str(p.relative_to(PATCHES))
                                     for p in PATCHES.rglob('*.patch')})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            donor = root / 'donor/w1700k-patches'
            for name in names:
                path = donor / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('isolated payload\n')
            if broken:
                candidate = donor / broken
                self.assertTrue(candidate.is_file(), 'payload absent from required preflight')
                if empty:
                    candidate.write_text('')
                else:
                    candidate.unlink()
            return subprocess.run(['bash', '-euo', 'pipefail', '-c', block],
                                  cwd=root, env=dict(os.environ, PKG_REPO=str(root / 'donor')),
                                  text=True, capture_output=True)

    def test_missing_or_empty_payload_blocks_before_copy(self):
        for name in sorted(p.relative_to(PATCHES) for p in PATCHES.rglob('*.patch')):
            for empty in (False, True):
                with self.subTest(patch=name, empty=empty):
                    result = self.preflight(name, empty)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(str(name), result.stderr)

    def test_complete_payload_passes(self):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        for name in NEW:
            self.assertIn('tree/package/kernel/mt76/patches/' + name, custom)
        result = self.preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in NEW:
            self.assertGreater((PATCHES / 'tree/package/kernel/mt76/patches' / name).stat().st_size, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
