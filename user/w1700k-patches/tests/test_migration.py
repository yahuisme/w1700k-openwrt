#!/usr/bin/env python3
"""Verify the payload against both immutable pre-migration Git snapshots."""

import hashlib
import os
import tempfile
from pathlib import Path
import subprocess
import unittest
from migration_baseline import migration_files


ROOT = Path(__file__).resolve().parents[1]
REVISIONS = {
    "openwrt": "b527db7ab1f918f0467056c50c332cafe31df7c8",
    "immortalwrt": "b61b737b26b06b1be1085f356c761cb516aa618e",
}
COMMON = (
    "patches/002-w1700k-cpufreq-resources.patch",
    "patches/920-wifi-non-mlo-ap-txpower.patch",
    "patches/998-single-wiphy.patch",
    "tree/package/kernel/mt76/patches/911-mt76-mt7996-refresh-power-limits-on-txpower-changes.patch",
    "tree/package/network/utils/iwinfo/patches/999-fix-txpower-list.patch",
    "tree/target/linux/airoha/patches-6.18/745-net-pcs-airoha-extend-manual-rx-calib-to-E2-silicon.patch",
    "tree/target/linux/airoha/patches-6.18/746-net-dsa-mt7530-pre-deassert-phy-reset-gpios-before-mdio-scan.patch",
    "tree/target/linux/airoha/patches-6.18/940-pmdomain-airoha-cpu-pll-fallback.patch",
)
POWER = "610-w1700k-power-30.patch"
ADDED = {
    "patches/004-airoha-reset-initialize-value.patch",
    "patches/005-eip93-cbc-dependency.patch",
    "tree/package/kernel/mt76/patches/915-mt76-npu-rx-packet-reassembly.patch",
    "tree/package/kernel/mt76/patches/916-mt76-radiotap-tlv-header.patch",
    "tree/package/kernel/mt76/patches/917-mt76-amsdu-subframe-header.patch",
    "patches/003-airoha-fan-init.patch",
    "patches/110-run-libuv-loop.patch",
    "tree/package/kernel/mt76/patches/913-mt76-mt7996-clean-up-truncated-txfree.patch",
    "tree/package/kernel/mt76/patches/914-mt76-mt7996-free-rro-drop-buffers.patch",
    "tree/package/network/utils/iwinfo/patches/998-fix-multi-radio-scan.patch",
    "tree/package/system/procd/patches/001-watchdog-reconcile-timeout.patch",
}
REMOVED_920_HUNK = (
    b"@@ -95,7 +95,7 @@\n"
    b" \t\trxantenna: config.rxantenna\n"
    b" \t});\n"
    b" \n"
    b"-\tif (config.txpower)\n"
    b"+\tif (config.txpower != null)\n"
    b" \t\tconfig.txpower = 'fixed ' + config.txpower + '00';\n"
    b" \telse\n"
    b" \t\tconfig.txpower = 'auto';\n"
)


class MigrationIntegrity(unittest.TestCase):
    def test_exact_inventory_and_snapshot_bytes(self):
        expected = set(COMMON) | {f"patches/{POWER}"} | ADDED
        actual = {str(p.relative_to(ROOT)) for folder in ('patches', 'tree')
                  for p in (ROOT / folder).rglob("*.patch")}
        self.assertEqual(actual, expected, "central payload inventory differs")
        power_bytes = {}
        baseline = migration_files()
        for distro, revision in REVISIONS.items():
            repo = os.environ.get(f'W1700K_{distro.upper()}_REPO')
            if repo is None:
                originals = {p: data for p, data in baseline.items() if p.startswith(('patches/', 'tree/'))}
                originals[f'patches/{POWER}'] = baseline[f'{distro}/{POWER}']
            else:
                prefix = 'user/default/'
                source_paths = subprocess.check_output(
                    ['git', '-C', repo, 'ls-tree', '-r', '--name-only', revision,
                     prefix + 'patches', prefix + 'tree'], text=True).splitlines()
                originals = {p.removeprefix(prefix): subprocess.check_output(
                    ['git', '-C', repo, 'show', f'{revision}:{p}'])
                    for p in source_paths if p.endswith('.patch')}
            self.assertEqual(set(originals), set(COMMON) | {f"patches/{POWER}"})
            for source, original in sorted(originals.items()):
                with self.subTest(distro=distro, source=source):
                    destination = source
                    if source == f"patches/{POWER}":
                        destination = f"patches/{POWER}"
                        power_bytes[distro] = original
                        if distro == "immortalwrt":
                            original = power_bytes["openwrt"]
                    if source == "patches/920-wifi-non-mlo-ap-txpower.patch":
                        if repo is not None:
                            self.assertEqual(original.count(REMOVED_920_HUNK), 1)
                            original = original.replace(REMOVED_920_HUNK, b"", 1)
                        old_context = b"@@ -745,7 +745,8 @@\n {\n"
                        self.assertEqual(original.count(old_context), 1)
                        original = original.replace(old_context, b"@@ -745,5 +745,6 @@\n", 1)
                        old_tail = b" \tswitch (radio_reload_class(old_config.radio, config.radio)) {\n"
                        self.assertEqual(original.count(old_tail), 1)
                        original = original.replace(old_tail, b"", 1)
                        # Context-only refresh: preserve upstream's new shutdown
                        # body without changing any added/removed power logic.
                        for before, after in (
                            (b"@@ -1806,6 +1812,31 @@\n", b"@@ -1807,4 +1813,29 @@\n"),
                            (b' \tubus.call("service", "event", { type: `hostapd.${name}.${type}`, data: {} });\n', b''),
                            (b" \tshutdown: function() {\n \t\tfor (let phy in hostapd.data.config)\n",
                             b" \tshutdown: function() {\n"),
                        ):
                            self.assertEqual(original.count(before), 1)
                            original = original.replace(before, after, 1)
                    if source == "tree/package/kernel/mt76/patches/911-mt76-mt7996-refresh-power-limits-on-txpower-changes.patch":
                        # Keep the immutable historical comparison; permit only
                        # the reviewed desired-cache gate and explanatory delta.
                        with tempfile.TemporaryDirectory() as tmp:
                            target = Path(tmp) / 'w1700k-patches' / source
                            target.parent.mkdir(parents=True)
                            target.write_bytes(original)
                            delta = ROOT / 'tests/fixtures/mt76-txpower/911-desired-cache.diff.fixture'
                            self.assertEqual(hashlib.sha256(delta.read_bytes()).hexdigest(),
                                             '51188e8a7e6169bcf2048126987daf743947f657c15ac705da32f7f75c08dece')
                            # Every admitted old hunk must match exactly once;
                            # never normalize an ambiguous or already-updated input.
                            hunks = delta.read_bytes().split(b'\n@@ ')[1:]
                            self.assertEqual(len(hunks), 2)
                            for hunk in hunks:
                                lines = hunk.splitlines(keepends=True)[1:]
                                preimage = b''.join(line[1:] for line in lines
                                                    if line[:1] in (b' ', b'-'))
                                self.assertEqual(original.count(preimage), 1)
                            result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0',
                                                     '--no-backup-if-mismatch', '-i', str(delta)],
                                                    cwd=tmp, capture_output=True, text=True)
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            original = target.read_bytes()
                    if source == "patches/998-single-wiphy.patch":
                        # Exact historical -> native-radio/info/cache/tab delta only.
                        # Keep historical Git bytes; the fixture preimage must be unique.
                        delta = ROOT / 'tests/fixtures/channel-local-info.diff.fixture'
                        lines = delta.read_bytes().splitlines(keepends=True)
                        self.assertEqual(sum(line.startswith(b'@@ ') for line in lines), 1)
                        hunk = next(i for i, line in enumerate(lines) if line.startswith(b'@@ '))
                        preimage = b''.join(line[1:] for line in lines[hunk + 1:]
                                            if line[:1] in (b' ', b'-'))
                        self.assertEqual(original.count(preimage), 1)
                        with tempfile.TemporaryDirectory() as tmp:
                            target = Path(tmp) / 'w1700k-patches' / source
                            target.parent.mkdir(parents=True)
                            target.write_bytes(original)
                            result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0',
                                                     '-i', str(delta)], cwd=tmp,
                                                    capture_output=True, text=True)
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                            original = target.read_bytes()
                    self.assertEqual((ROOT / destination).read_bytes(), original,
                                     f"changed bytes: {distro}/{source}")
        self.assertNotEqual(power_bytes["openwrt"], power_bytes["immortalwrt"],
                             "pre-migration distro inputs are intentionally different")


if __name__ == "__main__":
    unittest.main(verbosity=2)
