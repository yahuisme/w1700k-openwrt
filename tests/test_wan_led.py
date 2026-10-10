"""BusyBox ash + real jsonfilter; isolated regular-file sysfs and ubus/UCI.
Set WAN_LED_RUNTIME to an extracted AArch64 OpenWrt rootfs (no compiling).
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'user/default/files'
FIXTURES = ROOT / 'tests/fixtures/wan-led'


class WanLed(unittest.TestCase):
    def setUp(self):
        runtime = Path(os.environ['WAN_LED_RUNTIME'])
        self.assertTrue((runtime / 'usr/bin/jsonfilter').is_file())
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR', '/root/.hermes/cache/scratch'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('sys/class/leds', 'tmp/sysinfo', 'var/run', 'bin', 'etc', 'lib/functions', 'proc/device-tree/aliases'):
            (self.root / name).mkdir(parents=True)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + ':' + os.environ['PATH'], ACTION='ifup', INTERFACE='wan', STATE='true', CALLS=str(self.root / 'calls'))
        self.stub('uci', '''case "$*" in
*wan_led_interface) printf '%s' "$WAN";;
*wan_led) printf '%s' "$ENABLED";;
*leds_off) printf '%s' "$OFF";;
esac
''')
        self.stub('ubus', '''printf '%s\n' "$*" >> "$CALLS"
[ "$FAIL" != 1 ] || exit 1
printf '{"up":%s}\n' "$STATE"
''')
        self.stub('jsonfilter', f'exec "{runtime}/lib/ld-musl-aarch64.so.1" --library-path "{runtime}/lib:{runtime}/usr/lib" "{runtime}/usr/bin/jsonfilter" "$@"\n')
        self.stub('hexdump', 'exec busybox hexdump "$@"\n')
        (self.root / 'tmp/sysinfo/board_name').write_text('gemtek,w1700k-ubi')
        # Build DT/sysfs names from the real official GPIO LED nodes, not an RGB guess.
        dts = (FIXTURES / 'w1700k.dts').read_text()
        for color, index, pin in re.findall(r'led_status_(\w+): led-(\d+) \{.*?gpios = <&en7581_pinctrl (\d+)', dts, re.S):
            self.assertEqual(pin, {'green': '17', 'blue': '19', 'red': '29', 'white': '20'}[color])
            node = self.root / f'proc/device-tree/leds/led-{index}'
            node.mkdir(parents=True)
            (node / 'function').write_bytes(b'status\0')
            (node / 'color').write_bytes(('white', 'red', 'green', 'blue').index(color).to_bytes(4, 'big'))
            led = self.root / f'sys/class/leds/{color}:status'
            led.mkdir()
            for name, value in [('trigger', '[none] timer'), ('brightness', '0'), ('max_brightness', '255'), ('delay_on', '0'), ('delay_off', '0')]:
                (led / name).write_text(value)
        custom = (ROOT / 'user/default/custom.sh').read_text()
        fragment = custom[custom.index('sed -i -e \'s/led-boot'):custom.index('\n# -------------------------------------------------', custom.index('sed -i -e \'s/led-boot'))]
        dtfile = self.root / 'custom.dts'
        dtfile.write_text(dts)
        subprocess.run(['bash', '-ec', 'DTS="$1"\n' + fragment, 'test', str(dtfile)], check=True)
        for state, color in re.findall(r'led-(boot|running|failsafe|upgrade) = &led_status_(\w+);', dtfile.read_text()):
            index = {'green': 0, 'blue': 1, 'red': 2, 'white': 3}[color]
            (self.root / f'proc/device-tree/aliases/led-{state}').write_bytes(f'/leds/led-{index}\0'.encode())
        self.isolate(FIXTURES / 'leds.sh', 'lib/functions/leds.sh')
        self.isolate(FIXTURES / 'diag.sh', 'etc/diag.sh')
        self.script = self.isolate(FILES / 'etc/hotplug.d/iface/95-wan-status-led', 'etc/hotplug.d/iface/95-wan-status-led')
        self.boot = self.isolate(FILES / 'etc/init.d/wan-status-led', 'boot')
        self.upgrade = self.isolate(FILES / 'lib/upgrade/zz-wan-status-led.sh', 'upgrade')
        (self.root / 'var/run/wan-status-led-ready').touch()
        # Sentinel representing untouched physical port-speed LED.
        (self.root / 'sys/class/leds/green:wan').mkdir()
        (self.root / 'sys/class/leds/green:wan/brightness').write_text('42')

    def stub(self, name, text):
        p = self.root / 'bin' / name
        p.write_text('#!/bin/sh\n' + text)
        p.chmod(0o755)

    def isolate(self, source, target):
        text = source.read_text()
        for prefix in ('/sys/class/leds', '/tmp/', '/var/run/', '/etc/diag.sh', '/lib/functions/leds.sh', '/proc/device-tree', '/etc/hotplug.d/iface/95-wan-status-led'):
            text = text.replace(prefix, str(self.root) + prefix)
        p = self.root / target
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def shell(self, text, **env):
        return subprocess.run(['busybox', 'ash', '-c', text], env=dict(self.env, **env), check=True, text=True, capture_output=True)

    def run_led(self, **env):
        self.shell(f'. "{self.script}"; echo continued', **env)
        self.assertEqual((self.root / 'sys/class/leds/green:wan/brightness').read_text(), '42')

    def values(self):
        return tuple((self.root / f'sys/class/leds/{c}:status/brightness').read_text().strip() for c in ('white', 'red', 'green', 'blue'))

    def test_up_down_requery_and_configured_interface(self):
        for action, state, expected in [('ifup', 'true', ('255', '0')), ('ifdown', 'false', ('0', '255')), ('ifdown', 'true', ('255', '0')), ('ifupdate', 'false', ('0', '255'))]:
            self.run_led(ACTION=action, STATE=state)
            self.assertEqual(self.values(), expected + ('0', '0'))
        self.run_led(INTERFACE='wan6', WAN='wan6')
        self.assertIn('network.interface.wan6 status', (self.root / 'calls').read_text())
        self.assertEqual(self.values()[0], '255')

    def test_unknown_keeps_last_state(self):
        self.run_led()
        for env in ({'FAIL': '1'}, {'STATE': 'null'}, {'STATE': '123'}, {'STATE': ''}):
            self.run_led(**env)
            self.assertEqual(self.values(), ('255', '0', '0', '0'))
        self.stub('ubus', 'printf \'{}\'\n')
        self.run_led()
        self.assertEqual(self.values(), ('255', '0', '0', '0'))

    def test_filters_optout_early_boot_and_sourcing(self):
        for env in ({'INTERFACE': 'lan'}, {'INTERFACE': 'wan6'}, {'ACTION': 'iflink'}, {'ENABLED': '0'}, {'OFF': '1'}):
            self.run_led(**env)
        (self.root / 'var/run/wan-status-led-ready').unlink()
        self.run_led()
        self.assertFalse((self.root / 'calls').exists())
        result = self.shell(f'. "{self.script}"; echo continued', INTERFACE='lan')
        self.assertEqual(result.stdout.strip(), 'continued')

    def test_all_user_triggers_and_max_brightness(self):
        for color in ('white', 'red', 'green', 'blue'):
            p = self.root / f'sys/class/leds/{color}:status/trigger'
            p.write_text('none [timer]')
            self.run_led()
            self.assertEqual(self.values(), ('0', '0', '0', '0'))
            p.write_text('[none] timer')
        (self.root / 'sys/class/leds/white:status/max_brightness').write_text('1')
        self.run_led()
        self.assertEqual(self.values()[0], '1')

    def test_native_boot_failsafe_and_upgrade(self):
        # Execute real official diag/LED functions, with only absolute I/O relocated.
        self.shell(f'. "{self.root}/etc/diag.sh"; set_state preinit')
        self.assertEqual((self.root / 'sys/class/leds/green:status/trigger').read_text().strip(), 'timer')
        self.shell(f'. "{self.root}/etc/diag.sh"; set_state failsafe')
        self.assertEqual((self.root / 'sys/class/leds/red:status/delay_on').read_text().strip(), '50')
        # A regular file does not expose kernel [selected] trigger formatting.
        for color in ('white', 'red', 'green', 'blue'):
            (self.root / f'sys/class/leds/{color}:status/trigger').write_text('[none] timer')
        self.run_led(STATE='false')
        self.shell(f'. "{self.upgrade}"; indicate_upgrade')
        self.assertEqual(self.values()[:2], ('0', '0'))
        self.assertEqual((self.root / 'sys/class/leds/blue:status/trigger').read_text().strip(), 'timer')
        self.assertEqual((self.root / 'sys/class/leds/blue:status/delay_on').read_text().strip(), '200')
        for state in ('true', 'false'):
            self.run_led(STATE=state)
            self.assertEqual(self.values()[:2], ('0', '0'))

    def test_upgrade_during_ubus(self):
        self.stub('ubus', f'. "{self.upgrade}"; indicate_upgrade\nprintf \'{{"up":true}}\'\n')
        self.run_led()
        self.assertEqual(self.values()[:2], ('0', '0'))

    def test_rootfs_copy_and_native_enable(self):
        import shutil
        runtime = Path(os.environ['WAN_LED_RUNTIME'])
        image = self.root / 'image'
        subprocess.run(['cp', '-r', str(FILES) + '/', str(image)], check=True)
        for name in ('etc/rc.common', 'lib/functions.sh', 'lib/functions/service.sh'):
            target = image / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(runtime / name, target)
        (image / 'etc/rc.d').mkdir(exist_ok=True)
        subprocess.run(['bash', str(image / 'etc/rc.common'), str(image / 'etc/init.d/wan-status-led'), 'enable'],
                       env=dict(os.environ, IPKG_INSTROOT=str(image)), check=True, capture_output=True)
        link = image / 'etc/rc.d/S97wan-status-led'
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), image / 'etc/init.d/wan-status-led')
        for name in ('etc/hotplug.d/iface/95-wan-status-led', 'lib/upgrade/zz-wan-status-led.sh'):
            self.assertEqual((image / name).read_bytes(), (FILES / name).read_bytes())

    def test_boot_once_and_no_resident_service(self):
        (self.root / 'var/run/wan-status-led-ready').unlink()
        self.shell(f'. "{self.boot}"; boot')
        self.assertEqual(self.values(), ('255', '0', '0', '0'))
        self.assertEqual(len((self.root / 'calls').read_text().splitlines()), 1)
        text = (FILES / 'etc/init.d/wan-status-led').read_text()
        self.assertIn('START=97', text)
        self.assertNotIn('procd', text)
        self.assertTrue((FILES / 'etc/init.d/wan-status-led').stat().st_mode & 0o111)


if __name__ == '__main__':
    unittest.main()
