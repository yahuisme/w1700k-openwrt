"""Shared patch ownership and strict build integration, no build or host I/O."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SharedPatchTests(unittest.TestCase):
    def test_apps_are_cloned_and_patches_come_from_the_mounted_checkout(self):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        workflow = (ROOT / '.github/workflows/W1700K.yaml').read_text()
        self.assertEqual(custom.count('git clone --depth=1 https://github.com/yahuisme/packages.git'), 1)
        self.assertNotIn('$PKG_REPO/w1700k-patches', custom)
        self.assertIn('-v "$PWD/user:$DK_USER"', workflow)
        local = custom.index('PATCH_DIR="$DK_USER/w1700k-patches"')
        self.assertLess(local, custom.index('patch -p1 --fuzz=0'))
        self.assertIn('"$PATCH_DIR/tree/."', custom)
        self.assertNotIn('$DK_PROFILE/patches/', custom)
        self.assertNotIn('$DK_PROFILE/tree/', custom)
        self.assertIn('"$PATCH_DIR/patches/610-w1700k-power-30.patch"', custom)
        self.assertIn('"$PATCH_DIR/patches/998-single-wiphy.patch"', custom)

    def test_no_speculative_statistics_or_watchdog_sysfs_override(self):
        custom = (ROOT / 'user/default/custom.sh').read_text()
        self.assertNotIn('912-mt76-mt7996-use-mcu-station-statistics.patch', custom)
        self.assertNotIn('CONFIG_WATCHDOG_SYSFS', custom)

    def test_hostapd_dfs_uses_official_implementation(self):
        from patch_source import PATCHES
        custom = (ROOT / 'user/default/custom.sh').read_text()
        self.assertNotIn('mtk-0015-hostapd-mtk-6G-band-does-not-require-DFS.patch', custom)
        self.assertFalse(list((PATCHES / 'tree/package/network/services/hostapd').rglob('*.patch')))

    def test_no_duplicate_patch_payloads(self):
        self.assertFalse(list((ROOT / 'user/default').glob('patches/*.patch')))
        self.assertFalse(list((ROOT / 'user/default/tree').rglob('*.patch')))
        docs = ROOT / 'user/w1700k-patches/SOURCES.md'
        self.assertTrue(docs.is_file())
        self.assertIn(f'({docs.relative_to(ROOT)})', (ROOT / 'README.md').read_text())


if __name__ == '__main__':
    unittest.main()
