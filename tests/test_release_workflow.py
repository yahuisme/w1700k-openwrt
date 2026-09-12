"""Execute whole stage/release blocks with local fixtures and an executable gh stub."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import step, render

IMAGE = 'openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb'
CONFIG = ('CONFIG_TARGET_airoha=y\nCONFIG_TARGET_airoha_an7581=y\n'
          'CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi=y\n')


class ReleaseTests(unittest.TestCase):
    def fixture(self, base):
        target = base / 'openwrt_bin/targets/airoha/an7581'
        target.mkdir(parents=True)
        (base / '.config').write_text(CONFIG)
        (target / IMAGE).write_bytes(b'fixture firmware, not flashable')
        profile = {'target': 'airoha/an7581', 'version_code': 'r36238-fixture',
                   'profiles': {'gemtek_w1700k-ubi': {'images': [
                       {'name': IMAGE, 'type': 'sysupgrade'},
                       {'name': 'chainload-uboot.itb', 'type': 'chainload-uboot'}]}}}
        return target, profile

    def run_block(self, base, name, target='ubi2', **extra):
        env = dict(os.environ, DK_OPENWRT=str(base), RUNNER_TEMP=str(base),
                   GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='fixture/repo',
                   LOG=str(base / 'calls'), PATH=str(base / 'bin') + ':' + os.environ['PATH'])
        env.update(extra)
        block = render(step(name)['run'], {'matrix.target': target})
        return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c',
                               'sudo() { :; }; docker_exec() { shift; "$@"; };\n' + block],
                              cwd=base, env=env, capture_output=True, text=True)

    def test_stage_full_block(self):
        cases = ('good', 'config_board', 'config_soc', 'config_missing', 'config_multi',
                 'missing', 'empty', 'wrong_name', 'extra', 'other_target', 'symlink',
                 'profile_missing', 'profile_empty', 'profile_bad_json', 'profile_board',
                 'profile_target', 'profile_name', 'profile_multi_image', 'profile_no_image',
                 'profile_extra_file')
        for variant in ('ubi2', 'ubi2-oc'):
            for case in cases:
                with self.subTest(variant=variant, case=case), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    target, data = self.fixture(base)
                    image = target / IMAGE
                    config = base / '.config'
                    images = data['profiles']['gemtek_w1700k-ubi']['images']
                    if case == 'config_board': config.write_text(CONFIG.replace('gemtek_w1700k-ubi', 'wrong'))
                    if case == 'config_soc': config.write_text(CONFIG.replace('airoha', 'mediatek'))
                    if case == 'config_missing': config.unlink()
                    if case == 'config_multi': config.write_text(CONFIG + 'CONFIG_TARGET_airoha_an7581_DEVICE_wrong=y\n')
                    if case == 'missing': image.unlink()
                    if case == 'empty': image.write_bytes(b'')
                    if case == 'wrong_name': image.rename(target / 'wrong-sysupgrade.itb')
                    if case == 'extra': (target / 'other-sysupgrade.bin').write_bytes(b'other')
                    if case == 'other_target':
                        other = base / 'openwrt_bin/targets/mediatek/filogic'
                        other.mkdir(parents=True)
                        (other / IMAGE).write_bytes(b'wrong target')
                    if case == 'symlink':
                        image.rename(target / 'payload')
                        image.symlink_to('payload')
                    if case == 'profile_board': data['profiles']['wrong'] = data['profiles'].pop('gemtek_w1700k-ubi')
                    if case == 'profile_target': data['target'] = 'mediatek/filogic'
                    if case == 'profile_name': images[0]['name'] = 'wrong-sysupgrade.itb'
                    if case == 'profile_multi_image': images.append(dict(images[0]))
                    if case == 'profile_no_image': images.pop(0)
                    profiles = target / 'profiles.json'
                    profiles.write_text(json.dumps(data))
                    if case == 'profile_missing': profiles.unlink()
                    if case == 'profile_empty': profiles.write_text('')
                    if case == 'profile_bad_json': profiles.write_text('{')
                    if case == 'profile_extra_file':
                        other = base / 'openwrt_bin/targets/other/board'
                        other.mkdir(parents=True)
                        (other / 'profiles.json').write_text(json.dumps(data))
                    result = self.run_block(base, 'Validate and stage firmware', variant)
                    if case == 'good':
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual((base / 'firmware' / IMAGE).read_bytes(), image.read_bytes())
                        self.assertEqual((base / 'firmware/profiles.json').read_bytes(), profiles.read_bytes())
                        self.assertIn(variant, (base / 'firmware/release-notes.md').read_text())
                    else:
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertFalse((base / 'firmware/version.txt').exists())

    def test_release_full_block_and_peer_retention(self):
        for variant in ('ubi2', 'ubi2-oc'):
            for case in ('current', 'stale', 'api_failure', 'empty', 'malformed', 'create_failure'):
                with self.subTest(variant=variant, case=case), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    target, data = self.fixture(base)
                    (target / 'profiles.json').write_text(json.dumps(data))
                    self.assertEqual(self.run_block(base, 'Validate and stage firmware', variant).returncode, 0)
                    (base / 'bin').mkdir()
                    gh = base / 'bin/gh'
                    gh.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['LOG'], 'a') as log: log.write(json.dumps(args) + '\\n')
case = os.environ['CASE']
if args[0] == 'api':
    assert args == ['api', 'repos/fixture/repo/git/ref/heads/main', '--jq', '.object.sha']
    if case == 'api_failure': sys.exit(23)
    print({'stale': 'b'*40, 'empty': '', 'malformed': 'null'}.get(case, 'a'*40))
elif args[:2] == ['release', 'list']:
    print('W1700K-OpenWrt_r1\\nW1700K-OpenWrt-OC_r1\\nW1700K-OpenWrt-r1-old\\nW1700K-OpenWrt-OC-r1-old\\nW1700K-ubi2_old\\nW1700K-ubi2-oc_old\\nunrelated')
    print(Path('firmware/version.txt').read_text().strip())
elif args[:2] == ['release', 'create']:
    if case == 'create_failure': sys.exit(24)
elif args[:2] != ['release', 'delete']: sys.exit(99)
''')
                    gh.chmod(0o755)
                    result = self.run_block(base, 'Publish firmware and prune old releases', variant, CASE=case)
                    self.assertEqual(result.returncode, 24 if case == 'create_failure' else 0, result.stderr)
                    calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
                    if case not in ('current', 'create_failure'):
                        self.assertEqual(len(calls), 1)
                        # Successful skip keeps all later cache steps success-eligible.
                        self.assertEqual(result.returncode, 0)
                    else:
                        create = calls[1]
                        self.assertEqual(create[:2], ['release', 'create'])
                        self.assertEqual(create[create.index('--target') + 1], 'a' * 40)
                        self.assertEqual(create[3], 'firmware/' + IMAGE)
                        deletes = [c[-1] for c in calls if c[:2] == ['release', 'delete']]
                        prefix = 'W1700K-OpenWrt' + ('-OC' if variant == 'ubi2-oc' else '')
                        self.assertEqual(set(deletes), {prefix + '_r1', prefix + '-r1-old', 'W1700K-' + variant + '_old'} if case == 'current' else set())


if __name__ == '__main__':
    unittest.main()
