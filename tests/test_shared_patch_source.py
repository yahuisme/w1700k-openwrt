"""Run the complete customization script using exact sources and local clone boundaries."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from patch_source import PATCHES
from scripts.select_distribution import select
from test_device_runtime import FLASH_RUN, node
from test_ttyd_compat import PAYLOAD, SOURCE_HASH

ROOT = Path(__file__).resolve().parents[1]
APPS = ('luci-app-wifi7', 'luci-app-airoha-npu', 'luci-app-airoha-flowsense', 'luci-app-airoha-fancontrol')
FAN = 'target/linux/airoha/an7581/base-files/etc/init.d/airoha_fan'
TEMPLATES = tuple('package/base-files/files/' + name for name in (
    'etc/banner', 'etc/device_info', 'etc/openwrt_release', 'etc/openwrt_version',
    'usr/lib/os-release')) + ('include/version.mk',)


@unittest.skipUnless(os.environ.get('TXPOWER_SOURCE'), 'set TXPOWER_SOURCE to exact unpatched official source')
class SharedPatchSource(unittest.TestCase):
    def check_fan_boot(self, script, root):
        # Only redirect sysfs and mock rc.common's board lookup/logging.
        (root / 'lib').mkdir(parents=True)
        (root / 'lib/functions.sh').write_text('board_name() { printf "%s\\n" "$BOARD"; }\n')
        sensors = root / 'hwmon'
        wrong = sensors / 'hwmon5'
        wrong.mkdir(parents=True)
        (wrong / 'name').write_text('unrelated\n')
        (wrong / 'pwm1_enable').write_text('sentinel\n')
        native = sensors / 'hwmon7'
        attrs = {'pwm1_enable': '2', **{f'pwm1_auto_point{i}_temp': str(i * 10000 + 30000)
                                       for i in range(1, 6)},
                 **{f'pwm1_auto_point{i}_pwm': str(v) for i, v in enumerate((54, 69, 95, 199), 1)}}
        body = script.read_text().replace('/sys/class/hwmon/', str(sensors) + '/')
        def boot(board='gemtek,w1700k-ubi', restore='yes'):
            return subprocess.run(['busybox', 'ash', '-c', '''
logger() { printf '%s\\n' "$*" >&2; }
echo() { if [ "$*" = 2 ] && [ "$RESTORE" = no ]; then return 1; fi; command echo "$@"; }
''' + body + '\nboot\n'], env=dict(os.environ, IPKG_INSTROOT=str(root), BOARD=board,
                                   RESTORE=restore), text=True, capture_output=True)

        result = boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NCT7802 not found', result.stderr)
        self.assertEqual((wrong / 'pwm1_enable').read_text(), 'sentinel\n')
        native.mkdir()
        (native / 'name').write_text('nct7802\n')
        result = boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NCT7802 not found', result.stderr)
        self.assertEqual(list(native.iterdir()), [native / 'name'])
        for key in attrs:
            (native / key).write_text('sentinel\n')
        result = boot(board='other,board')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all((native / key).read_text() == 'sentinel\n' for key in attrs))
        result = boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({key: (native / key).read_text().strip() for key in attrs}, attrs)

        failed = native / 'pwm1_auto_point2_temp'
        failed.unlink()
        failed.mkdir()
        later = native / 'pwm1_auto_point3_temp'
        later.write_text('sentinel\n')
        result = boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('failed to set the fan curve', result.stderr)
        self.assertEqual((native / 'pwm1_enable').read_text(), '2\n')
        self.assertEqual(later.read_text(), 'sentinel\n')
        result = boot(restore='no')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to restore automatic control', result.stderr)

    def test_complete_customization_and_invalid_payloads(self):
        source = Path(os.environ['TXPOWER_SOURCE'])
        payloads = sorted(p.relative_to(PATCHES) for p in PATCHES.rglob('*.patch'))
        self.assertEqual(len(payloads), 24, 'update the full production payload matrix')
        cases = [(None, None)] + [(kind, name) for name in payloads
                                  for kind in ('missing', 'empty')]
        for kind, broken in cases:
            with self.subTest(kind=kind, patch=broken), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                recipe = base / 'recipe'
                shutil.copytree(ROOT / 'user', recipe / 'user')
                shutil.copytree(ROOT / 'installer', recipe / 'installer')
                if distro := os.environ.get('TXPOWER_DISTRO'):
                    select(distro, recipe)
                user = recipe / 'user'
                profile = user / 'default'
                distro = json.loads((profile / 'build.json').read_text())['system']
                local_patches = user / PATCHES.name
                if kind == 'missing':
                    assert broken is not None
                    (local_patches / broken).unlink()
                elif kind == 'empty':
                    assert broken is not None
                    (local_patches / broken).write_bytes(b'')
                donor = base / 'apps'
                for app in APPS:
                    (donor / app).mkdir(parents=True)
                work = base / 'source'
                for name in ('package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh',
                             'package/network/config/wifi-scripts/files-ucode/usr/share/ucode/wifi/hostapd.uc',
                             'package/network/services/hostapd/files/hostapd.uc',
                             'target/linux/airoha/dts/an7581-w1700k-ubi.dts',
                             'target/linux/airoha/an7581/config-6.18', FAN):
                    destination = work / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, destination)
                dts = 'target/linux/airoha/dts/an7581-w1700k-ubi.dts'
                if '#include "an7581-gemtek-common.dtsi"' in (source / dts).read_text():
                    common = Path(dts).with_name('an7581-gemtek-common.dtsi')
                    shutil.copyfile(source / common, work / common)
                for name, text in {
                    **{name: (source / name).read_text() for name in TEMPLATES},
                    'feeds/packages/utils/ttyd/Makefile': f'PKG_VERSION:=1.7.7\nPKG_RELEASE:=1\nPKG_HASH:={SOURCE_HASH}\n',
                    'feeds/luci/modules/luci-base/po/zh_Hans/base.po': Path(os.environ['DEVICE_BASE_PO']).read_text()
                        if os.environ.get('DEVICE_BASE_PO') else 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n',
                }.items():
                    destination = work / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(text)
                for directory in ('package/kernel/mt76',):
                    shutil.copytree(source / directory, work / directory)
                for name in ('package/kernel/linux/modules/crypto.mk',
                             'target/linux/airoha/patches-6.18/609-02-clk-en7523-add-support-for-dedicated-PCIe-PERSTOUT-r.patch',
                             'target/linux/airoha/patches-6.18/924-net-airoha-npu-use-coherent-mailbox-dma.patch'):
                    target = work / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, target)
                official_templates = {p: (work / p).read_bytes() for p in TEMPLATES}
                # Real native view is a required customization input, not an
                # isolated stub that could let the complete script fail early.
                flash = Path(os.environ.get('DEVICE_FLASH_JS', source /
                    'feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js'))
                destination = work / 'feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js'
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(flash, destination)
                for directory in ('package/firmware/wireless-regdb/patches',
                                  'package/network/config/firewall4/patches'):
                    if (source / directory).is_dir():
                        shutil.copytree(source / directory, work / directory)
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
                # A rejected payload may not install overlays or mutate direct inputs.
                # Flash reconnect defaults, app copies and revision recording precede
                # patch preflight and are the only permitted earlier writes.
                def protected_files():
                    return {str(p.relative_to(work)): (p.read_bytes(), p.stat().st_mode & 0o777)
                            for p in work.rglob('*') if p.is_file()
                            and p.relative_to(work).parts[:2] not in
                                [('package', app) for app in APPS]
                            and p != destination and p.name != '.custom-revisions.tsv'}
                before = protected_files()
                result = subprocess.run(['bash', '-ec', stub + 'bash "$CUSTOM"'], cwd=work,
                    env=dict(os.environ, DONOR=str(donor), CALLS=str(base / 'calls'),
                             CUSTOM=str(profile / 'custom.sh'), DK_PROFILE=str(profile), DK_USER=str(user)),
                    text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, broken is None, result.stdout + result.stderr)
                self.assertEqual(list(work.rglob('*.orig')), [], 'patch backups must not enter package payloads')
                reached_aurora = broken is None
                self.assertEqual((base / 'calls').read_text(),
                                 'packages\naurora-prepare\n' if reached_aurora else 'packages\n')
                if broken is None:
                    self.assertIn('Custom commands completed', result.stdout)
                    self.check_fan_boot(work / FAN, base / 'fan-runtime')
                    self.assertEqual(official_templates, {p: (work / p).read_bytes()
                                                        for p in official_templates})
                    kernel_config = (work / 'target/linux/airoha/an7581/config-6.18').read_text().splitlines()
                    self.assertEqual(kernel_config,
                                     (source / 'target/linux/airoha/an7581/config-6.18').read_text().splitlines(),
                                     'watchdog cadence repair must not override the official kernel config')
                    node(FLASH_RUN, destination, '192.168.8.1')
                    for original in (PATCHES / 'tree').rglob('*.patch'):
                        self.assertEqual(original.read_bytes(), (work / original.relative_to(PATCHES / 'tree')).read_bytes())
                    self.assertEqual((PATCHES / 'patches/610-w1700k-power-30.patch').read_bytes(),
                                     (work / 'package/firmware/wireless-regdb/patches/610-w1700k-power-30.patch').read_bytes())
                    self.assertEqual((PATCHES / 'patches/998-single-wiphy.patch').read_bytes(),
                                     (work / 'feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch').read_bytes())
                    self.assertEqual((PATCHES / 'patches' / PAYLOAD).read_bytes(),
                                     (work / 'feeds/packages/utils/ttyd/patches' / PAYLOAD).read_bytes())
                    self.assertIn('per_interface_txpower', (work / 'package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh').read_text())
                    self.assertIn("'fixed ' + int(config.txpower) * 100",
                                  (work / 'package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh').read_text())
                    self.assertIn('123'.zfill(40), (work / '.custom-revisions.tsv').read_text())
                    if distro == 'immortalwrt':
                        fw4 = work / 'package/network/config/firewall4/patches/001-firewall4-add-support-for-fullcone-nat.patch'
                        self.assertEqual(fw4.read_bytes(), (user / 'immortalwrt/firewall4-fullcone.patch').read_bytes())
                        removed = 'package/firmware/wireless-regdb/patches/600-custom-change-txpower-and-dfs.patch'
                        self.assertTrue((source / removed).is_file())
                        self.assertFalse((work / removed).exists())
                else:
                    self.assertIn('ERROR: Required patch missing or empty: ' + str(broken), result.stderr)
                    self.assertEqual(protected_files(), before)
                    self.assertNotIn('Custom commands completed', result.stdout)


if __name__ == '__main__':
    unittest.main()
