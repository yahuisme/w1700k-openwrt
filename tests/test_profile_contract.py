"""Shared profile injection/defaults contract, executed in isolated directories."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'user/default'


class ProfileContract(unittest.TestCase):
    def test_overlay_and_regdb_copy(self):
        text = (PROFILE / 'custom.sh').read_text()
        commands = [line for line in text.splitlines()
                    if line.startswith('cp ') and ('$DK_PROFILE/tree/.' in line or '610-' in line)]
        self.assertEqual(len(commands), 2)
        self.assertIn('--no-preserve=ownership', commands[0])
        self.assertIn('610-w1700k-power-30.patch', commands[1])
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'package/firmware/wireless-regdb/patches').mkdir(parents=True)
            subprocess.run(['bash', '-ec', '\n'.join(commands)], cwd=work,
                           env=dict(os.environ, DK_PROFILE=str(PROFILE)), check=True)
            for source in (PROFILE / 'tree').rglob('*'):
                if source.is_file():
                    self.assertEqual(source.read_bytes(), (work / source.relative_to(PROFILE / 'tree')).read_bytes())
            self.assertEqual((PROFILE / 'patches/610-w1700k-power-30.patch').read_bytes(),
                             (work / 'package/firmware/wireless-regdb/patches/610-w1700k-power-30.patch').read_bytes())

    def test_no_unimplemented_fq_override(self):
        self.assertFalse((PROFILE / 'files/etc/sysctl.d/10-bbr.conf').exists())
        self.assertIn('CONFIG_PACKAGE_kmod-tcp-bbr=y', (PROFILE / 'config.diff').read_text().splitlines())

    def test_workflow_installs_rootfs_overlay(self):
        import yaml
        workflow = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())
        block = next(s['run'] for s in workflow['jobs']['build']['steps']
                     if s.get('id') == 'inputs')
        commands = [line.strip() for line in block.splitlines()
                    if line.strip().startswith('cp ') and '$DK_PROFILE/files/' in line]
        self.assertEqual(len(commands), 1)
        self.assertNotIn('$DK_PROFILE/tree/', block)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['bash', '-ec', commands[0]], cwd=tmp,
                           env=dict(os.environ, DK_PROFILE=str(PROFILE)), check=True)
            for source in (PROFILE / 'files').rglob('*'):
                if source.is_file():
                    copied = Path(tmp) / 'files' / source.relative_to(PROFILE / 'files')
                    self.assertEqual(source.read_bytes(), copied.read_bytes())

    def test_defaults_policy(self):
        text = (PROFILE / 'files/etc/uci-defaults/99-w1700k-defaults').read_text()
        self.assertIn("uci -q set dhcp.lan.dhcpv6='disabled'", text)
        self.assertIn("uci -q set dhcp.lan.ra='server'", text)
        self.assertNotIn('uci -q delete wireless.${IFACE_', text)

    def test_union_migration_cleanup(self):
        text = (PROFILE / 'files/etc/uci-defaults/90-bridge-hw-offload').read_text()
        paths = ['/usr/share/bridge-flow-offload/apply-rules.sh',
                 '/etc/hotplug.d/iface/51-bridge-flow-offload',
                 '/etc/hotplug.d/iface/51-bridge-hw-offload',
                 '/etc/hotplug.d/net/50-bridge-hw-offload',
                 '/usr/share/nftables.d/ruleset-post/30-bridge-offload.nft']
        with tempfile.TemporaryDirectory() as tmp:
            for name in paths:
                self.assertIn(name, text)
                target = Path(tmp + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
                text = text.replace(name, tmp + name)
            for _ in range(2):
                result = subprocess.run(['busybox', 'ash', '-c', 'uci() { printf "%s\\n" "$*"; };\n' + text], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('-q delete firewall.bridge_flow_offload', result.stdout)
                self.assertTrue(all(not Path(tmp + name).exists() for name in paths))


if __name__ == '__main__':
    unittest.main()
