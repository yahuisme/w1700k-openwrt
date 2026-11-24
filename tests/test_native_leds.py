"""Keep native diagnostic ownership with only upgrade/running color changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DTS_DIR = Path('target/linux/airoha/dts')
BOARD = 'an7581-w1700k-ubi.dts'
COMMON = 'an7581-gemtek-common.dtsi'
INCLUDE = f'#include "{COMMON}"'
NATIVE = '''/ {
	aliases {
		led-boot = &led_status_red;
		led-failsafe = &led_status_blue;
		led-upgrade = &led_status_blue;
		led-running = &led_status_green;
	};
};
'''
SPLIT = f'/dts-v1/;\n\n{INCLUDE}\n\n/ {{\n\tmodel = "Gemtek W1700K";\n}};\n'
OVERRIDE = b'\n&{/aliases} {\n\tled-upgrade = &led_status_green;\n\tled-running = &led_status_white;\n};\n'


def expected_status_dts(board):
    if INCLUDE.encode() in board.splitlines():
        return board + OVERRIDE
    return board.replace(b'led-upgrade = &led_status_blue;', b'led-upgrade = &led_status_green;').replace(
        b'led-running = &led_status_green;', b'led-running = &led_status_white;')


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

    def check_status_dts(self, board, common=None, *, error=None):
        script = (ROOT / 'user/default/custom.sh').read_text()
        start = script.index('# Status LED colors:')
        end = script.index('# End status LED colors', start)
        fragment = script[start:end]
        expected = board if error else expected_status_dts(board)
        with tempfile.TemporaryDirectory() as directory:
            dts = Path(directory) / DTS_DIR / BOARD
            dts.parent.mkdir(parents=True)
            dts.write_bytes(board)
            if common is not None:
                dts.with_name(COMMON).write_bytes(common)
            for _ in range(1 if error else 2):
                result = subprocess.run(['bash', '-ec', fragment], cwd=directory,
                                        capture_output=True, text=True)
                if error:
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(error, result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotEqual(board, expected)
                self.assertEqual(dts.read_bytes(), expected)
                if common is not None:
                    self.assertEqual(dts.with_name(COMMON).read_bytes(), common)

    def test_standalone_status_colors_and_idempotence(self):
        self.check_status_dts(NATIVE.encode())

    def test_split_status_colors_and_idempotence(self):
        self.check_status_dts(SPLIT.encode(), NATIVE.encode())

    def test_missing_shared_include_fails_without_editing(self):
        self.check_status_dts(SPLIT.encode(), error='LED alias source missing')

    def test_unexpected_native_alias_fails_without_editing(self):
        wrong = NATIVE.replace('led-boot = &led_status_red;', 'led-boot = &led_status_white;')
        self.check_status_dts(wrong.encode(), error='LED alias mismatch: boot')
        self.check_status_dts(SPLIT.encode(), wrong.encode(), error='LED alias mismatch: boot')

    def test_duplicate_native_alias_fails_without_editing(self):
        alias = '\t\tled-running = &led_status_green;\n'
        self.check_status_dts(NATIVE.replace(alias, alias * 2).encode(), error='LED alias mismatch: running')

    def test_conflicting_board_override_fails_without_editing(self):
        for local in (
            b'&{/aliases} {\n\tled-running = &led_status_blue;\n};\n',
            b'&{/aliases} { led-boot = &led_status_white; };\n',
            b'&{/aliases} { led-boot\n = &led_status_white; };\n',
            b'&{/aliases} { /delete-property/ led-boot; };\n',
        ):
            for existing in (b'', OVERRIDE):
                with self.subTest(local=local, previously_applied=bool(existing)):
                    self.check_status_dts(SPLIT.encode() + local + existing, NATIVE.encode(),
                                          error='LED alias mismatch: W1700K override')

    @unittest.skipUnless(os.environ.get('LED_DTS_SOURCE'), 'requires pinned official DTS')
    def test_captured_upstream_dts(self):
        upstream = Path(os.environ['LED_DTS_SOURCE'])
        board = upstream.read_bytes()
        common = upstream.with_name(COMMON).read_bytes() if INCLUDE.encode() in board.splitlines() else None
        self.check_status_dts(board, common)


if __name__ == '__main__':
    unittest.main()
