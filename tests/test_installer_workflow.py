"""Installer assembly ordering and explicit native dependencies."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class InstallerWorkflow(unittest.TestCase):
    def test_native_recovery_is_explicit_and_overlay_is_isolated(self):
        config = (ROOT / 'user/default/config.diff').read_text().splitlines()
        self.assertIn('CONFIG_TARGET_ROOTFS_INITRAMFS=y', config)
        self.assertIn('CONFIG_PACKAGE_u-boot-an7581_gemtek_w1700k=y', config)
        self.assertFalse((ROOT / 'user/default/files/installer').exists())
        workflow = yaml.safe_load((ROOT / '.github/workflows/build-firmware.yaml').read_text())
        steps = workflow['jobs']['build']['steps']
        names = [s['name'] for s in steps]
        self.assertLess(names.index('Compile firmware'), names.index('Build installer'))
        self.assertLess(names.index('Prepare build caches'), names.index('Build installer'))
        self.assertLess(names.index('Build installer'), names.index('Validate and stage firmware'))
        self.assertLess(names.index('Validate and stage firmware'), names.index('Collect build record'))
        build = next(s['run'] for s in steps if s['name'] == 'Build installer')
        self.assertIn('/cache-scripts/build_installer.py', build)
        self.assertNotIn('git clone', build)
        prepare = next(s['run'] for s in steps if s['name'] == 'Prepare build environment')
        self.assertIn('$PWD/installer:/installer:ro', prepare)
        publish = next(s['run'] for s in steps if s['name'] == 'Publish firmware and prune releases')
        self.assertIn('firmware/*.itb', publish)
        self.assertNotIn('firmware/*sysupgrade.itb', publish)
