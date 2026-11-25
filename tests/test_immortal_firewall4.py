"""Replay the selected ImmortalWrt FullCone patch against exact upstream sources."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = 'package/network/config/firewall4/patches/001-firewall4-add-support-for-fullcone-nat.patch'
START = '# Refresh the ImmortalWrt FullCone patch for firewall4 3722eadc.\n'
END = '# End firewall4 patch refresh.\n'


class ImmortalFirewall4(unittest.TestCase):
    def materialize(self, root, system):
        for folder in ('user', 'installer', 'scripts'):
            shutil.copytree(ROOT / folder, root / folder)
        subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', system],
                       cwd=root, check=True)
        return (root / 'user/default/custom.sh').read_text()

    def test_refresh_is_selected_only_for_immortalwrt(self):
        for system in ('openwrt', 'immortalwrt'):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                custom = self.materialize(root, system)
                self.assertEqual(custom.count(START), int(system == 'immortalwrt'))
                self.assertEqual(custom.count(END), int(system == 'immortalwrt'))
                if system == 'immortalwrt':
                    self.assertIn('"$DK_USER/immortalwrt/firewall4-fullcone.patch"', custom)

    @unittest.skipUnless(os.environ.get('FIREWALL4_SOURCE'),
                         'set FIREWALL4_SOURCE to exact firewall4 3722eadc source')
    def test_selected_refresh_applies_without_fuzz_and_preserves_fullcone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom = self.materialize(root, 'immortalwrt')
            self.assertIn(START, custom)
            refresh = custom[custom.index(START):custom.index(END) + len(END)]
            tree = root / 'firewall4'
            shutil.copytree(os.environ['FIREWALL4_SOURCE'], tree)
            destination = tree / PATCH
            destination.parent.mkdir(parents=True)
            result = subprocess.run(['bash', '-ec', refresh], cwd=tree,
                                    env=dict(os.environ, DK_USER=str(root / 'user')),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(destination.read_bytes(),
                             (root / 'user/immortalwrt/firewall4-fullcone.patch').read_bytes())
            result = subprocess.run(['patch', '-p1', '--fuzz=0', '--no-backup-if-mismatch'],
                                    cwd=tree, input=destination.read_text(),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('fuzz', result.stdout)
            self.assertFalse(list(tree.rglob('*.rej')))
            self.assertFalse(list(tree.rglob('*.orig')))
            config = (tree / 'root/etc/config/firewall').read_text()
            for option, value in (('flow_offloading', 1), ('flow_offloading_hw', 1),
                                  ('fullcone', 1), ('fullcone6', 0)):
                self.assertRegex(config, rf'option {option}\s+{value}\n')
            fw4 = (tree / 'root/usr/share/ucode/fw4.uc').read_text()
            self.assertIn('zone.related_l3devs = related_l3devs;', fw4)
            self.assertIn('function nft_try_fullcone()', fw4)
            for family in ('IPv4', 'IPv6'):
                self.assertIn(f"{family} fullcone enabled for zone '", fw4)
            rules = (tree / 'root/usr/share/firewall4/templates/ruleset.uc').read_text()
            self.assertEqual(rules.count('include("zone-fullcone.uc"'), 4)
            self.assertTrue((tree / 'root/usr/share/firewall4/templates/zone-fullcone.uc').is_file())
            # A missing refresh input must stop customization, not retain stale upstream patches.
            (root / 'user/immortalwrt/firewall4-fullcone.patch').unlink()
            result = subprocess.run(['bash', '-ec', refresh + '\ntouch reached'], cwd=tree,
                                    env=dict(os.environ, DK_USER=str(root / 'user')),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((tree / 'reached').exists())

    @unittest.skipUnless(os.environ.get('FIREWALL4_SOURCE'),
                         'set FIREWALL4_SOURCE to exact firewall4 3722eadc source')
    def test_fullcone_probe_and_fallback_for_both_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / 'firewall4'
            shutil.copytree(os.environ['FIREWALL4_SOURCE'], tree)
            result = subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '--no-backup-if-mismatch',
                                     '-i', str(ROOT / 'user/immortalwrt/firewall4-fullcone.patch')],
                                    cwd=tree, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            fw4 = tree / 'root/usr/share/ucode/fw4.uc'
            # Load the patched native parser unchanged. Stub module loading and
            # the external capability probe so the test cannot run nft or UCI.
            harness = r'''
global.require = function(name) { return {}; };
let probes = 0;
let status = 0;
global.system = function(cmd) {
    assert(index(cmd, "/usr/sbin/nft -c ") == 0, "unexpected shell command");
    probes++;
    return status;
};
let fw4 = loadfile(FW4)();
for (let flags in [["0", "0"], ["1", "0"], ["0", "1"], ["1", "1"]]) {
    let enabled = flags[0] == "1" || flags[1] == "1";
    for (status in [1, 0]) {
        fw4.state = {};
        probes = 0;
        fw4.parse_defaults({fullcone: flags[0], fullcone6: flags[1]});
        assert(!!fw4.default_option("fullcone") == (!status && flags[0] == "1"),
               "IPv4 FullCone must fall back on a failed probe");
        assert(!!fw4.default_option("fullcone6") == (!status && flags[1] == "1"),
               "IPv6 FullCone must fall back on a failed probe");
        assert(probes == (enabled ? 1 : 0), "only probe when FullCone is requested");
    }
}
'''
            result = subprocess.run(['ucode', '-D', f'FW4={fw4}', '-e', harness],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
