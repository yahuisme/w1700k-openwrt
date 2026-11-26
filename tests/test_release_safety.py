"""Execute complete stage/publish shell blocks, real files and local gh stub only."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_cache_workflow import ROOT, render, step, MATRIX
import test_cache_key as cache_tests
from record_fixture import READBACK, installer_fixture

load, SCRIPT = cache_tests.load, cache_tests.SCRIPT

IMAGE = MATRIX['system'] + '-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb'
CONFIG = '''CONFIG_TARGET_airoha=y
CONFIG_TARGET_airoha_an7581=y
CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi=y
CONFIG_TARGET_BOARD="airoha"
CONFIG_TARGET_SUBTARGET="an7581"
CONFIG_TARGET_ROOTFS_INITRAMFS=y
CONFIG_PACKAGE_u-boot-an7581_gemtek_w1700k=y
CONFIG_PACKAGE_ubi-utils=y
CONFIG_PACKAGE_fitblk=y
'''
for app in ('airoha-fancontrol', 'airoha-flowsense', 'airoha-npu', 'wifi7', 'wol', 'ttyd'):
    CONFIG += f'CONFIG_PACKAGE_luci-app-{app}=y\nCONFIG_PACKAGE_luci-i18n-{app}-zh-cn=y\n'


CONFIG += ''.join(f'CONFIG_PACKAGE_{pkg}=y\n' for pkg in (
    'curl', 'etherwake', 'ttyd', 'wpad-openssl', 'kmod-nft-tproxy', 'kmod-tun', 'kmod-inet-diag',
    'kmod-netlink-diag'))
if MATRIX['system'] == 'immortalwrt':
    CONFIG += 'CONFIG_PACKAGE_kmod-crypto-hw-eip93=y\nCONFIG_PACKAGE_kmod-crypto-cbc=y\n'


class ReleaseTests(unittest.TestCase):
    def fixture(self, base):
        (base / 'scripts').symlink_to(ROOT / 'scripts')
        output = base / 'openwrt_bin/targets/airoha/an7581'
        output.mkdir(parents=True)
        (base / '.config').write_text(CONFIG)
        if MATRIX['system'] == 'immortalwrt':
            manifest = output / (IMAGE.removesuffix('-squashfs-sysupgrade.itb') + '.manifest')
            manifest.write_text('kmod-crypto-hw-eip93 - 6.18.60-r1\nkmod-crypto-cbc - 6.18.60-r1\n')
        (output / IMAGE).write_bytes(b'fixture-not-firmware')
        data = {'target': 'airoha/an7581', 'version_code': 'r123-abcdef', 'profiles': {
            'gemtek_w1700k-ubi': {'supported_devices': ['gemtek,w1700k-ubi'],
                'titles': [{'vendor': 'Gemtek', 'model': 'W1700K', 'variant': 'UBI'}],
                'images': [{'name': IMAGE, 'type': 'sysupgrade', 'filesystem': 'squashfs', 'size': 20,
                            'sha256': hashlib.sha256(b'fixture-not-firmware').hexdigest()}, installer_fixture(base, output, IMAGE)]}}}
        (output / 'profiles.json').write_text(json.dumps(data))
        return output, data

    def stage(self, base):
        block = 'sudo() { "$@"; }; docker_exec() { shift; "$@"; };\n' + render(step('Validate and stage firmware')['run'], {})
        return subprocess.run(['bash', '-eo', 'pipefail', '-c', block], cwd=base,
                              env=dict(os.environ, DK_OPENWRT=str(base), GITHUB_OUTPUT=str(base / 'output')), text=True, capture_output=True)

    def test_usteer_selection_contract(self):
        packages = ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn')
        for package in packages:
            for state in ('y', 'm', 'n', 'unset', 'absent'):
                with self.subTest(package=package, state=state), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    output, data = self.fixture(base)
                    (output / 'profiles.json').write_text(json.dumps(data))
                    symbol = 'CONFIG_PACKAGE_' + package
                    line = (f'# {symbol} is not set\n' if state == 'unset' else
                            '' if state == 'absent' else f'{symbol}={state}\n')
                    (base / '.config').write_text(CONFIG + line)
                    result = self.stage(base)
                    if state in ('y', 'm'):
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('Forbidden package: ' + package, result.stdout + result.stderr)
                        self.assertFalse((base / 'firmware').exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_required_dependencies_are_enforced_at_formal_and_stage_gates(self):
        from scripts.validate_firmware import validate, finalize
        packages = ('curl', 'kmod-nft-tproxy', 'kmod-tun', 'kmod-inet-diag', 'kmod-netlink-diag')
        for package in packages:
            symbol = 'CONFIG_PACKAGE_' + package
            selected = symbol + '=y\n'
            states = {
                'y': selected,
                'absent': '',
                'm': symbol + '=m\n',
                'n': symbol + '=n\n',
                'unset': '# ' + symbol + ' is not set\n',
                'duplicate': selected * 2,
                'conflicting-m': selected + symbol + '=m\n',
                'conflicting-n': selected + symbol + '=n\n',
                'conflicting-unset': selected + '# ' + symbol + ' is not set\n',
            }
            for state, replacement in states.items():
                with self.subTest(package=package, state=state), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    self.fixture(base)
                    self.assertEqual(CONFIG.count(selected), 1)
                    config = base / '.config'
                    config.write_text(CONFIG.replace(selected, replacement))
                    for checker in (validate, finalize):
                        if state == 'y':
                            self.assertTrue(checker(config, base / 'openwrt_bin/targets', MATRIX['system'])['images'])
                        else:
                            with self.assertRaisesRegex(ValueError, 'required dependency: ' + package):
                                checker(config, base / 'openwrt_bin/targets', MATRIX['system'])
                    result = self.stage(base)
                    self.assertEqual(result.returncode == 0, state == 'y', result.stdout + result.stderr)
                    if state != 'y':
                        self.assertIn('required dependency: ' + package, result.stderr)
                        self.assertFalse((base / 'firmware').exists())

    def test_required_user_packages_cannot_be_omitted(self):
        packages = ['etherwake', 'ttyd', 'wpad-openssl']
        packages += [pkg for app in ('wol', 'ttyd')
                     for pkg in ('luci-app-' + app, 'luci-i18n-' + app + '-zh-cn')]
        for package in packages:
            with self.subTest(package=package), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, data = self.fixture(base)
                (output / 'profiles.json').write_text(json.dumps(data))
                (base / '.config').write_text(CONFIG.replace(f'CONFIG_PACKAGE_{package}=y\n', ''))
                result = self.stage(base)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(package, result.stderr)

    def test_release_notes_link_to_current_default_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.fixture(base)
            result = self.stage(base)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            notes = (base / 'firmware/release-notes.md').read_text()
            self.assertIn('## 默认设置\n', (ROOT / 'README.md').read_text())
            self.assertIn('/w1700k-openwrt#默认设置', notes)
            first_flash = next(line for line in notes.splitlines() if line.startswith('- [首次刷机 / 完整重装（含救砖）]'))
            self.assertIn('/blob/main/w1700k-' + MATRIX['system'] + '-first-flash.md)', first_flash)
            self.assertTrue(first_flash.endswith('：在原厂 U-Boot 刷 `chainload-uboot.itb`，再启动 `initramfs-installer.itb`。'))
            upgrade = next(line for line in notes.splitlines() if line.startswith('- 日常升级：'))
            self.assertEqual(upgrade, '- 日常升级：使用同发行版的 `squashfs-sysupgrade.itb`。')
            self.assertNotIn('\n> ', notes)
            self.assertNotIn('只用 Installer', notes)
            self.assertNotIn('#默认访问', notes)

    def test_stage_contract(self):
        for case in ('valid', 'wrong-config', 'two-devices', 'missing-config', 'missing-target',
                     'wrong-json', 'two-profiles', 'wrong-supported', 'wrong-title', 'wrong-name',
                     'two-images', 'empty', 'missing-image', 'missing-json', 'bad-json', 'size', 'metadata-duplicate',
                     'metadata-name', 'filesystem', 'revision', 'other-target', 'symlink', 'missing-app', 'missing-translation', 'extra-json', 'no-upgrade'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                out, data = self.fixture(base)
                profile = data['profiles']['gemtek_w1700k-ubi']
                config = base / '.config'
                image = out / IMAGE
                if case == 'symlink':
                    image.rename(out / 'payload')
                    image.symlink_to('payload')
                if case == 'missing-app': config.write_text(CONFIG.replace('CONFIG_PACKAGE_luci-app-wifi7=y\n', ''))
                if case == 'missing-translation': config.write_text(CONFIG.replace('CONFIG_PACKAGE_luci-i18n-wifi7-zh-cn=y\n', ''))
                if case == 'extra-json': (base / 'openwrt_bin/targets/profiles.json').write_text('{}')
                if case == 'no-upgrade': profile['images'].pop(0)
                if case == 'wrong-config': config.write_text(CONFIG.replace('airoha', 'mediatek'))
                if case == 'two-devices': config.write_text(CONFIG + 'CONFIG_TARGET_airoha_an7581_DEVICE_other=y\n')
                if case == 'missing-config': config.unlink()
                if case == 'missing-target': config.write_text(CONFIG.replace('CONFIG_TARGET_airoha=y\n', ''))
                if case == 'wrong-json': data['target'] = 'mediatek/filogic'
                if case == 'two-profiles': data['profiles']['other'] = profile
                if case == 'wrong-supported': profile['supported_devices'] = ['other,board']
                if case == 'wrong-title': profile['titles'][0]['model'] = 'other'
                if case == 'wrong-name': image.rename(out / 'other-sysupgrade.itb')
                if case == 'two-images': (out / 'other-sysupgrade.itb').write_bytes(b'x')
                if case == 'empty': image.write_bytes(b'')
                if case == 'missing-image': image.unlink()
                if case == 'size': profile['images'][0]['size'] = 1
                if case == 'metadata-duplicate': profile['images'] *= 2
                if case == 'metadata-name': profile['images'][0]['name'] = 'other-sysupgrade.itb'
                if case == 'filesystem': profile['images'][0]['filesystem'] = 'ext4'
                if case == 'revision': data['version_code'] = None
                if case == 'other-target':
                    other = base / 'openwrt_bin/targets/mediatek/filogic'
                    other.mkdir(parents=True)
                    (other / IMAGE).write_bytes(b'x')
                (out / 'profiles.json').write_text(json.dumps(data))
                if case == 'missing-json': (out / 'profiles.json').unlink()
                if case == 'bad-json': (out / 'profiles.json').write_text('{')
                result = self.stage(base)
                if case == 'valid':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((base / 'final.config').read_text(), CONFIG)
                    self.assertEqual((base / 'firmware' / IMAGE).read_bytes(), b'fixture-not-firmware')
                    expected = json.loads((ROOT / 'user/default/build.json').read_text())['images']
                    self.assertEqual({p.name for p in (base / 'firmware').glob('*.itb')}, set(expected))
                    notes = (base / 'firmware/release-notes.md').read_text()
                    branch = 'main' if MATRIX['system'] == 'openwrt' else 'master'
                    self.assertIn(MATRIX['title'] + ' ' + branch, notes)
                    self.assertIn('https://github.com/' + MATRIX['system'] + '/' + MATRIX['system'], notes)
                    self.assertNotIn('ubi2', notes)
                else:
                    self.assertNotEqual(result.returncode, 0, case)
                    self.assertFalse((base / 'firmware').exists())

    def test_native_digest_required_and_equal_size_corruption_rejected(self):
        for case in ('missing', 'malformed', 'corrupt'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, data = self.fixture(base)
                row = data['profiles']['gemtek_w1700k-ubi']['images'][0]
                image = output / IMAGE
                if case == 'missing':
                    del row['sha256']
                elif case == 'malformed':
                    row['sha256'] = '0' * 63
                else:
                    image.write_bytes(b'fixture-not-firmwarE')
                (output / 'profiles.json').write_text(json.dumps(data))
                result = self.stage(base)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((base / 'firmware').exists())

    def test_final_inventory_matches_the_frozen_native_payload(self):
        from scripts import firmware_images
        from scripts.validate_firmware import finalize

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            output, _ = self.fixture(base)
            paths = (base / '.config', base / 'openwrt_bin/targets', MATRIX['system'])
            images = finalize(*paths)['images']
            assert isinstance(images, list)
            self.assertEqual(len(images), 3)
            collect = firmware_images.collect

            def collect_after_change(*args, **kwargs):
                image = output / IMAGE
                original = image.read_bytes()
                image.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                return collect(*args, **kwargs)

            with patch.object(firmware_images, 'collect', side_effect=collect_after_change):
                with self.assertRaisesRegex(ValueError, 'image digest differs from profiles.json'):
                    finalize(*paths)

    def test_staged_digest_gate_precedes_release_create(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                self.fixture(base)
                self.assertEqual(self.stage(base).returncode, 0)
                if corrupt:
                    image = base / 'firmware' / IMAGE
                    image.write_bytes(b'fixture-not-firmwarE')
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_staged.py'),
                                         'firmware', 'firmware/accepted-images.json',
                                         hashlib.sha256((base / 'firmware/accepted-images.json').read_bytes()).hexdigest()], cwd=base,
                                        env=dict(os.environ, DK_PROFILE='/bld/user/default'),
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not corrupt, result.stderr)

    def test_publish_freshness_and_retired_oc_release_retention(self):
        for case in ('fresh', 'extra-itb', 'stale', 'error', 'empty', 'malformed', 'advance', 'recheck-error', 'create-error'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                self.fixture(base)
                result = self.stage(base)
                self.assertEqual(result.returncode, 0, result.stderr)
                if case == 'extra-itb':
                    (base / 'firmware/unexpected-recovery.itb').write_bytes(b'extra image')
                gh = base / 'gh'
                gh.write_text('''#!/usr/bin/env python3
import os,json,sys
from pathlib import Path
args=sys.argv[1:]; root=Path(os.environ['STUB_ROOT']); mode=os.environ['CASE']
with (root/'calls').open('a') as f: f.write(json.dumps(args)+'\\n')
if args == ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']:
    print((root/'releases.json').read_text())
elif args[0]=='api' and '/releases/tags/' in args[1]:
''' + READBACK + '''
elif args[0]=='api' and '/git/ref/tags/' in args[1]:
    print(json.dumps(dict(object=dict(type='commit',sha=os.environ['GITHUB_SHA']))))
elif args[0]=='api':
    second=(root/'checked').exists(); (root/'checked').touch()
    if mode=='error' or (second and mode=='recheck-error'): sys.exit(1)
    if mode=='empty': sys.exit(0)
    if mode=='malformed': print('null'); sys.exit(0)
    print('b'*40 if mode=='stale' or (second and mode=='advance') else os.environ['GITHUB_SHA'])
elif args[:2]==['release','create']:
    if mode=='create-error': sys.exit(1)
elif args[:2]!=['release','delete']: sys.exit(99)
''')
                gh.chmod(0o755)
                version = (base / 'firmware/version.txt').read_text().strip()
                standard = [f"W1700K-{MATRIX['title']}_24.01.01-08.00.00_r1",
                            f"W1700K-{MATRIX['title']}-r1-24.01.02_08.00.00"]
                if MATRIX['system'] == 'openwrt':
                    standard.append('W1700K-ubi2_24.01.03-08.00.00_r1')
                oc = ['W1700K-OpenWrt-OC_old', 'W1700K-OpenWrt-OC-r1-old', 'W1700K-ubi2-oc_old']
                entries = [dict(tag_name=tag, id=1000 if tag == version else i+1, draft=False, prerelease=False,
                                published_at=f'2026-01-{i+1:02d}T00:00:00Z')
                           for i, tag in enumerate(standard + oc + [version, 'unrelated'])]
                (base / 'releases.json').write_text(json.dumps([entries]))
                env = dict(os.environ, PATH=tmp + ':' + os.environ['PATH'], STUB_ROOT=tmp, CASE=case,
                           GITHUB_SHA='a'*40, GITHUB_REPOSITORY='fixture/repo')
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', render(step('Publish firmware and prune releases')['run'], {
                    'steps.stage.outputs.acceptance': hashlib.sha256((base / 'firmware/accepted-images.json').read_bytes()).hexdigest()})], cwd=base, env=env, text=True, capture_output=True)
                calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
                creates = [c for c in calls if c[:2] == ['release', 'create']]
                deletes = [c[2] for c in calls if c[:2] == ['release', 'delete']]
                self.assertEqual(result.returncode == 0, case in ('fresh', 'stale', 'advance'), result.stderr)
                self.assertEqual(bool(creates), case in ('fresh', 'advance', 'recheck-error', 'create-error'))
                if case == 'extra-itb':
                    self.assertIn('unexpected staged ITB inventory', result.stderr)
                if creates: self.assertEqual(creates[0][creates[0].index('--target') + 1], 'a'*40)
                self.assertEqual(set(deletes), set(standard) if case == 'fresh' else set())
                self.assertEqual(calls[0], ['api', 'repos/fixture/repo/git/ref/heads/main', '--jq', '.object.sha'])
                if case == 'stale':
                    # A successful skipped publication leaves ordinary cache steps runnable.
                    block = 'docker_exec() { printf "%s\\n" "$*"; }; sudo() { :; };\n' + render(step('Prepare build caches')['run'], {'steps.tc_restore.outputs.hit': 'true'})
                    block = block.split('python3 scripts/cache_helper.py admit', 1)[0]
                    packed = subprocess.run(['bash', '-e', '-c', block], cwd=base, env=env, capture_output=True, text=True)
                    self.assertEqual(packed.returncode, 0)
                    self.assertIn('cache.py ccache', packed.stdout)
