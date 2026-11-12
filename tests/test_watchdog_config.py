"""Execute the production watchdog kernel-config injection in private files."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path('target/linux/airoha/an7581/config-6.18')


class WatchdogConfigTests(unittest.TestCase):
    def block(self):
        text = (ROOT / 'user/default/custom.sh').read_text()
        marker = '# Expose the native watchdog timeout limit to procd.'
        self.assertIn(marker, text, 'watchdog sysfs must be enabled in the actual target config')
        start = text.index(marker)
        return text[start:text.index('# End watchdog timeout limit', start)]

    def test_target_config_enables_sysfs_once_and_preserves_other_options(self):
        block = self.block()
        for setting in ('', '# CONFIG_WATCHDOG_SYSFS is not set\n',
                        'CONFIG_WATCHDOG_SYSFS=y\n', 'CONFIG_WATCHDOG_SYSFS=n\n'):
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / RELATIVE
                config.parent.mkdir(parents=True)
                config.write_text('CONFIG_AIROHA_WDT=y\n' + setting + 'CONFIG_EXAMPLE=y\n')
                for _ in range(2):
                    result = subprocess.run(['bash', '-eu', '-c', block], cwd=root,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(config.read_text(),
                        'CONFIG_AIROHA_WDT=y\nCONFIG_EXAMPLE=y\nCONFIG_WATCHDOG_SYSFS=y\n')

    def test_missing_target_config_is_fatal_without_creating_it(self):
        block = self.block()
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['bash', '-eu', '-c', block], cwd=directory,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ERROR: Airoha kernel config not found', result.stderr)
            self.assertFalse((Path(directory) / RELATIVE).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
