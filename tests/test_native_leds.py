"""Keep native diagnostic ownership with only upgrade/running color changes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeLEDTests(unittest.TestCase):
    def test_no_custom_led_preset(self):
        profile = ROOT / 'user/default'
        self.assertFalse((profile / 'files/etc/uci-defaults/99-w1700k-led').exists())
        for path in (profile / 'files').rglob('*'):
            if path.is_file():
                self.assertNotIn('led_wan_status', path.read_text(), str(path))

    def test_native_led_ownership(self):
        profile = ROOT / 'user/default'
        for relative in ('files/etc/board.d/01_leds', 'files/etc/config/system'):
            self.assertFalse((profile / relative).exists(), relative)

    def test_status_colors_and_idempotence(self):
        import os
        import subprocess
        import tempfile
        script = (ROOT / 'user/default/custom.sh').read_text()
        self.assertIn('# Status LED colors:', script)
        start = script.index('# Status LED colors:')
        end = script.index('# End status LED colors', start)
        fragment = script[start:end]
        source = Path(os.environ['LED_DTS_SOURCE']).read_text() if os.environ.get('LED_DTS_SOURCE') else (
            'led-boot = &led_status_red;\nled-failsafe = &led_status_blue;\n'
            'led-upgrade = &led_status_blue;\nled-running = &led_status_green;\n')
        expected = source.replace('led-upgrade = &led_status_blue;',
                                  'led-upgrade = &led_status_green;').replace(
                                  'led-running = &led_status_green;',
                                  'led-running = &led_status_white;')
        self.assertNotEqual(source, expected)
        with tempfile.TemporaryDirectory() as directory:
            dts = Path(directory) / 'target/linux/airoha/dts/an7581-w1700k-ubi.dts'
            dts.parent.mkdir(parents=True)
            dts.write_text(source)
            for _ in range(2):
                result = subprocess.run(['bash', '-ec', fragment], cwd=directory,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(dts.read_text(), expected)


if __name__ == '__main__':
    unittest.main()
