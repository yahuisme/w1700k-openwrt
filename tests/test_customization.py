"""Source native Aurora defaults with BusyBox ash and a private UCI fixture."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / 'user/default/files/etc/uci-defaults/99-w1700k-aurora'


class AuroraDefaultsTests(unittest.TestCase):
    def run_defaults(self, retained='', section='aurora', fail=''):
        self.assertTrue(DEFAULTS.is_file(), 'native post-Aurora defaults script is missing')
        initial = {
            'aurora.theme.nav_type': 'mega-menu',
            'aurora.theme.struct_radius_base': '0.5rem',
            'aurora.theme.light_brand': '#0086bf',
            'aurora.theme.config_version': '7',
            'aurora.theme.toolbar_enabled': '1',
            'luci.main.mediaurlbase': '/luci-static/aurora',
        }
        if section:
            initial['aurora.theme'] = section
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / DEFAULTS.name
            text = DEFAULTS.read_text()
            for name in ('/sysupgrade.tgz', '/tmp/sysupgrade.tar'):
                private = root / Path(name).name
                if retained == name:
                    private.touch()
                text = text.replace(name, str(private))
            script.write_text(text)
            state = root / 'state.json'
            state.write_text(json.dumps(initial))
            fixture = root / 'uci_fixture.py'
            fixture.write_text('''import json, os, sys
from pathlib import Path
root = Path(os.environ['FIXTURE_ROOT'])
args = sys.argv[1:]
with (root / 'calls').open('a') as log:
    log.write(json.dumps(args) + '\\n')
assert args[0] == '-q', args
state = json.loads((root / 'state.json').read_text())
if args[1] == 'get':
    if args[2] not in state: sys.exit(1)
    print(state[args[2]])
elif args[1] == 'set':
    key, value = args[2].split('=', 1)
    if key == os.environ['FAIL']: sys.exit(1)
    state[key] = value
    (root / 'state.json').write_text(json.dumps(state))
else:
    sys.exit(99)
''')
            # Real boot sources scripts on the left of &&, commits at the caller,
            # and removes successful scripts. Only the fixture can receive UCI.
            boundary = '''
uci() { python3 "$UCI_FIXTURE" "$@"; }
[ -f "$SCRIPT" ] || exit 0
( . "$SCRIPT" ) && { rm "$SCRIPT"; exit 0; }
exit 1
'''
            env = dict(os.environ, FIXTURE_ROOT=str(root), SCRIPT=str(script),
                       UCI_FIXTURE=str(fixture), FAIL=fail)
            result = subprocess.run(['/usr/bin/busybox', 'ash', '-c', boundary],
                                    env=env, capture_output=True, text=True)
            calls = [json.loads(x) for x in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
            final = json.loads(state.read_text())
            exists = script.exists()
            # A successful native default never runs again on later boots or
            # package upgrades; simulate the next boot with the same caller.
            if result.returncode == 0:
                second = subprocess.run(['/usr/bin/busybox', 'ash', '-c', boundary],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(json.loads(state.read_text()), final)
                self.assertEqual([json.loads(x) for x in (root / 'calls').read_text().splitlines()]
                                 if (root / 'calls').exists() else [], calls)
            return result, initial, final, calls, exists

    def test_after_package_initialization_only_two_defaults_change(self):
        self.assertGreater(DEFAULTS.name, '80_aurora')
        result, initial, final, calls, exists = self.run_defaults()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(final, initial | {
            'aurora.theme.nav_type': 'sidebar',
            'aurora.theme.struct_radius_base': '0.125rem',
        })
        self.assertFalse(exists)
        self.assertEqual([c for c in calls if c[1] != 'get'], [
            ['-q', 'set', 'aurora.theme.nav_type=sidebar'],
            ['-q', 'set', 'aurora.theme.struct_radius_base=0.125rem'],
        ])

    def test_retained_upgrade_is_untouched_before_any_uci_access(self):
        for retained in ('/sysupgrade.tgz', '/tmp/sysupgrade.tar'):
            with self.subTest(retained=retained):
                result, initial, final, calls, exists = self.run_defaults(retained=retained)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(final, initial)
                self.assertEqual(calls, [])
                self.assertFalse(exists)

    def test_missing_or_unknown_section_is_not_created_or_overwritten(self):
        for section in ('', 'unknown'):
            with self.subTest(section=section):
                result, initial, final, calls, exists = self.run_defaults(section=section)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(final, initial)
                self.assertTrue(exists)
                self.assertFalse(any(c[1] == 'set' for c in calls))

    def test_each_failed_write_retains_script_and_stops(self):
        for index, key in enumerate(('aurora.theme.nav_type', 'aurora.theme.struct_radius_base')):
            with self.subTest(key=key):
                result, initial, final, calls, exists = self.run_defaults(fail=key)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(exists)
                writes = [c for c in calls if c[1] == 'set']
                self.assertEqual(len(writes), index + 1)
                self.assertEqual(final[key], initial[key])


if __name__ == '__main__':
    unittest.main()
