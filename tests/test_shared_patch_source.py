"""Run the complete customization script using exact sources and local clone boundaries."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from patch_source import PATCHES
from test_device_runtime import FLASH_RUN, node

ROOT = Path(__file__).resolve().parents[1]
APPS = ('luci-app-wifi7', 'luci-app-airoha-npu', 'luci-app-airoha-flowsense', 'luci-app-airoha-fancontrol')
TEMPLATES = tuple('package/base-files/files/' + name for name in (
    'etc/banner', 'etc/device_info', 'etc/openwrt_release', 'etc/openwrt_version',
    'usr/lib/os-release')) + ('include/version.mk',)


@unittest.skipUnless(os.environ.get('TXPOWER_SOURCE'), 'set TXPOWER_SOURCE to exact unpatched official source')
class SharedPatchSource(unittest.TestCase):
    def test_complete_customization_and_missing_payloads(self):
        source = Path(os.environ['TXPOWER_SOURCE'])
        payloads = [p.relative_to(PATCHES) for p in PATCHES.rglob('*.patch')]
        used = payloads
        for missing in (None, *used):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                donor = base / 'donor'
                shutil.copytree(PATCHES, donor / 'w1700k-patches')
                if missing:
                    (donor / 'w1700k-patches' / missing).unlink()
                for app in APPS:
                    shutil.copytree(PATCHES.parent / app, donor / app)
                work = base / 'source'
                for name in ('package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh',
                             'package/network/config/wifi-scripts/files-ucode/usr/share/ucode/wifi/hostapd.uc',
                             'package/network/services/hostapd/files/hostapd.uc',
                             'target/linux/airoha/dts/an7581-w1700k-ubi.dts'):
                    destination = work / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, destination)
                for name, text in {
                    **{name: (source / name).read_text() for name in TEMPLATES},
                    'feeds/luci/modules/luci-base/po/zh_Hans/base.po': '',
                }.items():
                    destination = work / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(text)
                official_templates = {p: (work / p).read_bytes() for p in TEMPLATES}
                # Real native view is a required customization input, not an
                # isolated stub that could let the complete script fail early.
                flash = Path(os.environ.get('DEVICE_FLASH_JS', source /
                    'feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js'))
                destination = work / 'feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js'
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(flash, destination)
                # Source overlays use a directory copy: missing an individual
                # required patch must not silently omit that behavior.
                stub = '''git() {
 if [ "$1" = clone ]; then
  local dest="${@: -1}"
  if [[ "$*" = *yahuisme/packages.git* ]]; then
   printf 'packages\\n' >> "$CALLS"
   cp -a "$DONOR/." "$dest/"
  else
   echo "Unexpected clone: $*" >&2
   return 99
  fi
 elif [[ "$*" = *rev-parse* ]]; then printf '%040d\\n' 123;
 else printf 'https://github.com/yahuisme/packages.git\\n'; fi
}
# APK source preparation has separate real-source integration tests; isolate
# that boundary here while replaying every unrelated customization verbatim.
python3() {
 [ "$#" = 3 ] && [ "$1" = /cache-scripts/external_packages.py ] && \
 [ "$2" = prepare ] && [ "$3" = . ] || return 99
 printf 'aurora-prepare\n' >> "$CALLS"
}
export -f git python3
'''
                result = subprocess.run(['bash', '-ec', stub + 'bash "$CUSTOM"'], cwd=work,
                    env=dict(os.environ, DONOR=str(donor), CALLS=str(base / 'calls'),
                             CUSTOM=str(ROOT / 'user/default/custom.sh'), DK_PROFILE=str(ROOT / 'user/default')),
                    text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, missing is None, result.stdout + result.stderr)
                reached_aurora = missing in (None, Path('patches/610-w1700k-power-30.patch'))
                self.assertEqual((base / 'calls').read_text(),
                                 'packages\naurora-prepare\n' if reached_aurora else 'packages\n')
                if missing is None:
                    self.assertEqual(official_templates, {p: (work / p).read_bytes()
                                                        for p in official_templates})
                    node(FLASH_RUN, destination, '192.168.8.1')
                    for original in (PATCHES / 'tree').rglob('*.patch'):
                        self.assertEqual(original.read_bytes(), (work / original.relative_to(PATCHES / 'tree')).read_bytes())
                    self.assertEqual((PATCHES / 'patches/610-w1700k-power-30.patch').read_bytes(),
                                     (work / 'package/firmware/wireless-regdb/patches/610-w1700k-power-30.patch').read_bytes())
                    self.assertEqual((PATCHES / 'patches/998-single-wiphy.patch').read_bytes(),
                                     (work / 'feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch').read_bytes())
                    self.assertIn('per_interface_txpower', (work / 'package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh').read_text())
                    self.assertIn('123'.zfill(40), (work / '.custom-revisions.tsv').read_text())
                else:
                    self.assertNotIn('Custom commands completed', result.stdout)


if __name__ == '__main__':
    unittest.main()
