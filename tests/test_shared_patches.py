"""Shared patch ownership and strict build integration, no build or host I/O."""
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SharedPatchTests(unittest.TestCase):
    def test_one_clone_owns_apps_and_patches(self):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        self.assertEqual(custom.count('git clone --depth=1 https://github.com/yahuisme/packages.git'), 1)
        clone = custom.index('if ! git clone --depth=1 https://github.com/yahuisme/packages.git')
        self.assertIn('PATCH_DIR="$PKG_REPO/w1700k-patches"', custom)
        shared = custom.index('PATCH_DIR="$PKG_REPO/w1700k-patches"')
        apply = custom.index('patch -p1 --fuzz=0')
        self.assertLess(clone, shared)
        self.assertLess(shared, apply)
        self.assertIn('"$PATCH_DIR/tree/."', custom)
        self.assertNotIn('$DK_PROFILE/patches/', custom)
        self.assertNotIn('$DK_PROFILE/tree/', custom)
        self.assertIn('"$PATCH_DIR/patches/610-w1700k-power-30.patch"', custom)
        self.assertIn('"$PATCH_DIR/patches/998-single-wiphy.patch"', custom)

    def test_no_speculative_statistics_or_watchdog_sysfs_override(self):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        self.assertNotIn('912-mt76-mt7996-use-mcu-station-statistics.patch', custom)
        self.assertNotIn('CONFIG_WATCHDOG_SYSFS', custom)

    def test_no_duplicate_patch_payloads(self):
        self.assertFalse(list((ROOT / 'user/default').glob('patches/*.patch')))
        self.assertFalse(list((ROOT / 'user/default/tree').rglob('*.patch')))
        self.assertFalse((ROOT / 'SOURCES.md').exists())
        self.assertIn('packages/tree/main/w1700k-patches/SOURCES.md', (ROOT / 'README.md').read_text())


if __name__ == '__main__':
    unittest.main()
