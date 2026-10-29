"""Leave LED defaults and diagnostic ownership to the official firmware."""
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

    def test_no_status_alias_override(self):
        profile = ROOT / 'user/default'
        for path in profile.rglob('*'):
            if path.is_file():
                text = path.read_text()
                self.assertNotIn('led_status_', text, str(path))
                self.assertNotIn('led_wan_status', text, str(path))
        for relative in ('files/etc/board.d/01_leds', 'files/etc/config/system'):
            self.assertFalse((profile / relative).exists(), relative)


if __name__ == '__main__':
    unittest.main()
