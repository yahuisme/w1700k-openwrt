"""Keep official NAND timing and user-visible profile settings."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from patch_source import PATCHES

ROOT = Path(__file__).resolve().parents[1]


class ConvergenceTests(unittest.TestCase):
    def test_usteer_not_requested(self):
        config = (ROOT / 'user/default/config.diff').read_text().splitlines()
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
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
                    'wol', 'ttyd'):
            for package in ('luci-app-' + app, 'luci-i18n-' + app + '-zh-cn'):
                self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for package in ('etherwake', 'ttyd', 'wpad-openssl'):
            self.assertIn('CONFIG_PACKAGE_' + package + '=y', config)
        for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
            for state in ('y', 'm'):
                self.assertNotIn(f'CONFIG_PACKAGE_{package}={state}', config)
        path = 'target/linux/airoha/dts/an7581.dtsi'
        self.assertEqual((source / path).read_bytes(), subprocess.check_output(
            ['git', 'show', 'HEAD:' + path], cwd=source))
        path = 'target/linux/airoha/dts/an7581-w1700k-ubi.dts'
        official = subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=source)
        # Compare the entire DTS, allowing only the actual required CPUFreq
        # payload and two LED aliases, not an inferred/duplicated resource block.
        payload = PATCHES / 'patches/002-w1700k-cpufreq-resources.patch'
        self.assertTrue(payload.is_file() and payload.stat().st_size > 0)
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            target = work / path
            target.parent.mkdir(parents=True)
            target.write_bytes(official)
            result = subprocess.run(['patch', '-p1', '--fuzz=0', '--batch',
                                     '--no-backup-if-mismatch', '-i', str(payload.resolve())],
                                    cwd=work, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            patched = target.read_bytes()
            self.assertNotEqual(official, patched)
            self.assertEqual(list(work.rglob('*.orig')), [])
        expected = patched.replace(b'led-upgrade = &led_status_blue;',
                                    b'led-upgrade = &led_status_green;').replace(
                                    b'led-running = &led_status_green;',
                                    b'led-running = &led_status_white;')
        self.assertNotEqual(patched, expected)
        self.assertEqual((source / path).read_bytes(), expected)
