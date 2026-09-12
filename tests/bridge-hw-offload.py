#!/usr/bin/env python3
"""Run against a real package's files/ or extracted rootfs with BusyBox ash.

Usage: python3 tests/bridge-hw-offload.py ROOT [--raw]
Default: apply this profile's patch through its custom.sh command first.
Mocks isolate UCI, nft and firewall; no host network state is touched.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(sys.argv[1]).resolve()
RAW = '--raw' in sys.argv[2:]
sys.argv[1:] = []
REPO = Path(__file__).resolve().parents[1]
PACKAGE = Path('package/network/config/bridge-hw-offload')
PATCH = '920-bridge-hw-offload-lifecycle.patch'


def ash(script):
    return subprocess.run(['busybox', 'ash', '-c', script],
                          text=True, capture_output=True)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = self.root / PACKAGE / 'files'
        for name in ('etc/init.d/bridge-hw-offload',
                     'usr/share/bridge-hw-offload/apply-rules.sh'):
            target = self.files / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
        if not RAW:
            result = self.inject()
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.init = (self.files / 'etc/init.d/bridge-hw-offload').read_text()

    def inject(self, profile=None):
        lines = (REPO / 'user/default/custom.sh').read_text().splitlines()
        command, = [line for line in lines if PATCH in line]
        return subprocess.run(['bash', '-ec', command + '\nprintf reached'],
                              cwd=self.root, text=True, capture_output=True,
                              env=dict(os.environ, DK_PROFILE=str(profile or REPO / 'user/default')))

    def test_procd_registration(self):
        result = ash('''procd_open_instance() { echo OPEN; }
procd_set_param() { echo PARAM "$@"; }
procd_close_instance() { echo CLOSE; }
procd_add_reload_trigger() { echo TRIGGER "$@"; }
''' + self.init + '\nstart_service; status=$?; service_triggers; exit "$status"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ['OPEN', 'PARAM command /bin/true', 'CLOSE', 'TRIGGER firewall'])

    def test_rule_lifecycle(self):
        rules = self.root / 'rules'
        rules.mkdir()
        brif = self.root / 'brif'
        live = self.root / 'live-table'
        rule = rules / '30-bridge-offload.nft'
        source = (self.files / 'usr/share/bridge-hw-offload/apply-rules.sh').read_text()
        source = source.replace('/usr/share/nftables.d/ruleset-post', str(rules))
        source = source.replace('/sys/class/net/${BRIDGE}/brif', str(brif))
        source = source.replace('/etc/init.d/firewall reload', 'firewall_reload')
        prelude = f'''uci() {{ printf '%s' "$HW"; }}
logger() {{ :; }}
nft() {{
    [ "$*" = 'delete table bridge fw4' ] || return 99
    [ -f '{live}' ] || return 1
    rm '{live}'
}}
firewall_reload() {{
    if [ -f '{rule}' ]; then cp '{rule}' '{live}'; fi
}}
'''
        # Each no-port case starts with both stale artifacts, then repeats
        # with no live table (nft delete returns 1) to prove idempotence.
        for shape in ('missing', 'empty', 'ports'):
            if shape != 'missing':
                brif.mkdir(exist_ok=True)
            if shape == 'ports':
                (brif / 'lan1').mkdir()
                (brif / 'lan2').mkdir()
                (brif / 'not-a-port').touch()
            for hw in ('', '0', '1'):
                with self.subTest(bridge=shape, hw=hw):
                    rule.write_text('stale')
                    live.write_text('stale')
                    enabled = shape == 'ports' and hw == '1'
                    for repeat in range(2):
                        result = ash(f"HW='{hw}'\n" + prelude + source + '\nstatus=$?; wait; exit "$status"')
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(rule.exists(), enabled)
                        self.assertEqual(live.exists(), enabled)
                        if enabled:
                            text = rule.read_text()
                            self.assertIn('devices = { lan1, lan2 }; flags offload;', text)
                            self.assertTrue(text.startswith('destroy table bridge fw4\n'))
                            self.assertNotIn('not-a-port', text)
                            self.assertEqual(live.read_text(), text)

    def test_reload_propagates_generator_failure(self):
        # Execute the real handler; substitute only its absolute executable.
        result = ash('generator() { return 23; }\n' + self.init.replace(
            '/usr/share/bridge-hw-offload/apply-rules.sh', 'generator') + '\nreload_service')
        self.assertEqual(result.returncode, 23)

    @unittest.skipIf(RAW, 'injection is not used for raw reproduction')
    def test_injection_failure_aborts(self):
        # Already-applied patches must fail closed rather than reverse/skip.
        result = self.inject()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('reached', result.stdout)
        result = self.inject(self.root / 'missing-profile')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('reached', result.stdout)
        shutil.rmtree(self.files)
        result = self.inject()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('reached', result.stdout)


unittest.main(verbosity=2)
