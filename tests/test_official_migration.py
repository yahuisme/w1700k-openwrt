"""Official-source migration contract; optional real prepared-tree checks."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OfficialMigrationTests(unittest.TestCase):
    def test_single_standard_official_source(self):
        workflow = (ROOT / '.github/workflows/W1700K.yaml').read_text()
        self.assertIn('REPO_URL="https://github.com/openwrt/openwrt"', workflow)
        self.assertIn('REPO_BRANCH="main"', workflow)
        self.assertIn("cron: '0 4 * * *'", workflow)
        for removed in ('matrix.target', 'ubi2-oc', 'w1700k.github.io', 'vermagic.txt'):
            self.assertNotIn(removed, workflow)
        self.assertLess(workflow.index('git clean -ffdx'), workflow.index('./scripts/feeds update'))
        custom = (ROOT / 'user/default/custom.sh').read_text()
        self.assertNotIn('OpenWRT-fanboy', custom)
        self.assertIn('cp -a --no-preserve=ownership "$DK_PROFILE/tree/." .', custom)

    def test_minimal_kernel_delta(self):
        tree = ROOT / 'user/default/tree'
        patches = sorted(p.name for p in tree.glob('target/linux/airoha/patches-*/*.patch'))
        self.assertEqual([p[:3] for p in patches], ['745', '746', '940'])
        self.assertEqual(len(list(tree.glob('package/kernel/mt76/patches/*.patch'))), 2)
        self.assertFalse((tree / 'package/network/config/firewall4').exists())
        self.assertFalse(list(tree.rglob('939-*')))

    @unittest.skipUnless(os.environ.get('OPENWRT_SOURCE'), 'set OPENWRT_SOURCE to real prepared official tree')
    def test_real_defconfig_and_clean_removes_preseeded_inputs(self):
        source = Path(os.environ['OPENWRT_SOURCE'])
        config = set((source / '.config').read_text().splitlines())
        for line in (ROOT / 'user/default/config.diff').read_text().splitlines():
            if line.startswith('CONFIG_PACKAGE_') and line.endswith('=y'):
                self.assertIn(line, config)
        for app in ('wifi7', 'airoha-npu', 'airoha-flowsense', 'airoha-fancontrol', 'wol', 'ttyd'):
            self.assertIn(f'CONFIG_PACKAGE_luci-app-{app}=y', config)
            self.assertIn(f'CONFIG_PACKAGE_luci-i18n-{app}-zh-cn=y', config)
        self.assertIn('CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi=y', config)
        with tempfile.TemporaryDirectory() as tmp:
            clone = Path(tmp) / 'source'
            subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(source), str(clone)], check=True)
            subprocess.run(['git', '-C', str(clone), 'checkout', '--quiet', 'HEAD'], check=True)
            for path in ('files/etc/vermagic.txt', 'files/etc/apk/repositories.d/distfeeds.list',
                         'package/obsolete/Makefile', 'feeds/old/.git/config', 'build_dir/stale'):
                p = clone / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('preseeded\n')
            subprocess.run(['git', '-C', str(clone), 'clean', '-ffdx'], check=True, capture_output=True)
            for path in ('files', 'package/obsolete', 'feeds', 'build_dir'):
                self.assertFalse((clone / path).exists())
