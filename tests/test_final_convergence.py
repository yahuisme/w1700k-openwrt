"""Keep official NAND timing and user-visible profile settings."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConvergenceTests(unittest.TestCase):
    def test_usteer_explicitly_disabled(self):
        config = (ROOT / 'user/default/config.diff').read_text().splitlines()
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
            self.assertIn(f'# CONFIG_PACKAGE_{package} is not set', config)
            for state in ('y', 'm'):
                self.assertNotIn(f'CONFIG_PACKAGE_{package}={state}', config)

    def test_no_nand_downclock_in_local_inputs(self):
        for path in (ROOT / 'user/default').rglob('*'):
            if path.is_file() and path.suffix in ('.sh', '.patch'):
                self.assertNotIn('33000000', path.read_text(), str(path))

    @unittest.skipUnless(os.environ.get('OPENWRT_SOURCE'), 'requires prepared official source')
    def test_prepared_profile(self):
        source = Path(os.environ['OPENWRT_SOURCE'])
        config = set((source / '.config').read_text().splitlines())
        for app in ('wifi7', 'airoha-npu', 'airoha-flowsense', 'airoha-fancontrol',
                    'wol', 'ttyd', 'aurora-config'):
            for package in ('luci-app-' + app, 'luci-i18n-' + app + '-zh-cn'):
                self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for package in ('etherwake', 'ttyd', 'wpad-openssl', 'luci-theme-aurora'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
            for state in ('y', 'm'):
                self.assertNotIn(f'CONFIG_PACKAGE_{package}={state}', config)
        path = 'target/linux/airoha/dts/an7581.dtsi'
        self.assertEqual((source / path).read_bytes(), subprocess.check_output(
            ['git', 'show', 'HEAD:' + path], cwd=source))
        dts = (source / 'target/linux/airoha/dts/an7581-w1700k-ubi.dts').read_text()
        for state, color in (('boot', 'green'), ('failsafe', 'red'), ('running', 'white')):
            self.assertIn(f'led-{state} = &led_status_{color};', dts)
