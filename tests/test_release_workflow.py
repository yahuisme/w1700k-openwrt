"""Execute whole stage/release blocks with local fixtures and an executable gh stub."""
import json
import os
from pathlib import Path
import subprocess
import re
import tempfile
import unittest
from test_cache_workflow import STEPS, step, render

IMAGE = 'openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb'
CONFIG = ('CONFIG_TARGET_airoha=y\nCONFIG_TARGET_airoha_an7581=y\n'
          'CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi=y\n')
CONFIG += ''.join(f'CONFIG_PACKAGE_{package}=y\n'
                  for app in ('wifi7', 'airoha-npu', 'airoha-flowsense', 'airoha-fancontrol', 'wol', 'ttyd')
                  for package in (f'luci-app-{app}', f'luci-i18n-{app}-zh-cn'))

CONFIG += ''.join(f'CONFIG_PACKAGE_{pkg}=y\n' for pkg in ('etherwake', 'ttyd', 'wpad-openssl'))


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

    def run_block(self, base, name, **extra):
        env = dict(os.environ, DK_OPENWRT=str(base), RUNNER_TEMP=str(base),
                   GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='fixture/repo',
                   LOG=str(base / 'calls'), PATH=str(base / 'bin') + ':' + os.environ['PATH'])
        env.update(extra)
        block = render(step(name)['run'], {})
        return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c',
                               'sudo() { :; }; docker_exec() { shift; "$@"; };\n' + block],
                              cwd=base, env=env, capture_output=True, text=True)

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
                    result = self.run_block(base, 'Validate and stage firmware')
                    if state in ('y', 'm'):
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('Forbidden package: ' + package, result.stdout + result.stderr)
                        self.assertFalse((base / 'firmware').exists())
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
                result = self.run_block(base, 'Validate and stage firmware')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(package, result.stdout + result.stderr)

    def test_stage_full_block(self):
        cases = ('good', 'missing_app', 'missing_translation', 'config_board', 'config_soc', 'config_missing', 'config_multi',
                 'missing', 'empty', 'wrong_name', 'extra', 'other_target', 'symlink',
                 'profile_missing', 'profile_empty', 'profile_bad_json', 'profile_board',
                 'profile_target', 'profile_name', 'profile_multi_image', 'profile_no_image',
                 'profile_extra_file')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                target, data = self.fixture(base)
                image = target / IMAGE
                config = base / '.config'
                images = data['profiles']['gemtek_w1700k-ubi']['images']
                if case == 'missing_app': config.write_text(CONFIG.replace('CONFIG_PACKAGE_luci-app-wifi7=y\n', ''))
                if case == 'missing_translation': config.write_text(CONFIG.replace('CONFIG_PACKAGE_luci-i18n-wifi7-zh-cn=y\n', ''))
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
                result = self.run_block(base, 'Validate and stage firmware')
                if case == 'good':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((base / 'firmware' / IMAGE).read_bytes(), image.read_bytes())
                    self.assertEqual((base / 'firmware/profiles.json').read_bytes(), profiles.read_bytes())
                    self.assertIn('官方 snapshot 标准版', (base / 'firmware/release-notes.md').read_text())
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse((base / 'firmware/version.txt').exists())

    def test_publication_after_cache_tail_and_failure_isolation(self):
        stage = step('Validate and stage firmware')
        publish = step('Publish firmware and prune releases')
        cache_tail = STEPS[STEPS.index(step('Package build caches')):
                           STEPS.index(step('Prune old download caches')) + 1]
        self.assertEqual(stage.get('id'), 'stage')
        self.assertEqual(publish.get('if'), "${{ !cancelled() && steps.stage.outcome == 'success' }}")
        self.assertLess(STEPS.index(stage), STEPS.index(cache_tail[0]))
        self.assertLess(STEPS.index(cache_tail[-1]), STEPS.index(publish))
        self.assertEqual(publish['env'], {'GH_TOKEN': '${{ secrets.RELEASE_TOKEN }}'})
        cases = ['', 'Compile firmware', stage['name'], publish['name'], 'cancel_before_compile',
                 'cancel_after_stage'] + [s['name'] for s in cache_tail]
        for fault in cases:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                target, data = self.fixture(base)
                (target / 'profiles.json').write_text(json.dumps(data))
                if fault == stage['name']:
                    (base / '.config').write_text('invalid target\n')
                (base / 'bin').mkdir()
                gh = base / 'bin/gh'
                gh.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$LOG"
case "$1 $2" in
  'api '*) printf '%s\\n' "$GITHUB_SHA" ;;
  'release create') [ "$FAULT" != 'Publish firmware and prune releases' ] ;;
  'release list') : ;;
  *) exit 99 ;;
esac
''')
                gh.chmod(0o755)
                cc = base / 'staging_dir/host/bin/ccache'
                cc.parent.mkdir(parents=True)
                cc.write_text('#!/bin/bash\nexit 0\n')
                cc.chmod(0o755)
                # Execute actual YAML shell blocks, mocking only external build,
                # cache, sudo and GitHub commands. Never invoke a host compiler.
                stubs = '''
sudo() { if [ "$1" = python3 ]; then "$@"; fi; }
nproc() { printf '1\\n'; }
make() { [ "$FAULT" != 'Compile firmware' ]; }
python3() {
  [ "$STEP_NAME" != "$FAULT" ] || return 23
  if [ "$2" = admit ]; then printf 'save=true\\n' >> "$GITHUB_OUTPUT"; else printf 'save=true\\n'; fi
}
docker_exec() {
  shift
  [ "$STEP_NAME" != 'Package build caches' ] || [ "$FAULT" != "$STEP_NAME" ] || return 23
  "$@"
}
export -f sudo nproc make python3 docker_exec
'''
                env = dict(os.environ, DK_OPENWRT=tmp, RUNNER_TEMP=tmp,
                           GITHUB_OUTPUT=str(base / 'output'), GITHUB_SHA='a' * 40,
                           GITHUB_REPOSITORY='fixture/repo', LOG=str(base / 'calls'),
                           PATH=str(base / 'bin') + ':' + os.environ['PATH'], FAULT=fault)
                values = {'steps.tc.outputs.cache-hit': 'false'}
                successful = True
                cancelled = fault == 'cancel_before_compile'
                executed, saved, outcomes = [], [], {}
                for current in STEPS[STEPS.index(step('Compile firmware')):]:
                    # Evaluate the real if expression, including GitHub's implicit
                    # success() when no status function appears. No copied gate.
                    expr = current.get('if', 'True').removeprefix('${{').removesuffix('}}').strip()
                    has_status = re.search(r'\b(success|failure|cancelled|always)\(', expr)
                    for name, value in {'success()': successful and not cancelled,
                                        'failure()': not successful, 'cancelled()': cancelled,
                                        'always()': True}.items():
                        expr = expr.replace(name, repr(value))
                    expr = re.sub(r"hashFiles\('[^']+'\)", "'fixture-archive'", expr)
                    expr = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), expr)
                    expr = re.sub(r'!(?!=)', 'not ', expr).replace('&&', ' and ').replace('||', ' or ')
                    # Trusted local YAML and repr-quoted fixture values only;
                    # no event/network input or builtins reach this evaluator.
                    eligible = (bool(has_status) or (successful and not cancelled)) and eval(
                        expr, {'__builtins__': {}})
                    name = current['name']
                    outcome = 'skipped'
                    if eligible:
                        executed.append(name)
                        if 'run' in current:
                            result = subprocess.run(['bash', '-eo', 'pipefail', '-c',
                                                     stubs + render(current['run'], values)],
                                                    cwd=base, env=dict(env, STEP_NAME=name),
                                                    text=True, capture_output=True)
                            outcome = 'success' if result.returncode == 0 else 'failure'
                            if current.get('id') and (base / 'output').exists():
                                for line in (base / 'output').read_text().splitlines():
                                    key, value = line.split('=', 1)
                                    values[f"steps.{current['id']}.outputs.{key}"] = value
                                (base / 'output').unlink()
                        else:
                            self.assertEqual(current['uses'], 'actions/cache/save@main')
                            outcome = 'failure' if name == fault else 'success'
                            if outcome == 'success':
                                saved.append(current['with']['path'])
                        successful = successful and outcome == 'success'
                    outcomes[name] = outcome
                    if current.get('id'):
                        values[f"steps.{current['id']}.outcome"] = outcome
                    if name == stage['name'] and fault == 'cancel_after_stage':
                        cancelled = True
                should_publish = fault not in ('Compile firmware', stage['name'],
                                               'cancel_before_compile', 'cancel_after_stage')
                self.assertEqual(publish['name'] in executed, should_publish, (fault, outcomes))
                calls = (base / 'calls').read_text() if (base / 'calls').exists() else ''
                self.assertEqual('release create' in calls, should_publish)
                if not fault or fault == publish['name']:
                    self.assertEqual(saved, ['ccarchive', 'tcarchive', 'dlarchive'])
                if fault in [s['name'] for s in cache_tail]:
                    self.assertEqual(outcomes[fault], 'failure')
                    self.assertEqual(outcomes[publish['name']], 'success')
                    after = cache_tail.index(step(fault)) + 1
                    self.assertTrue(all(outcomes[s['name']] == 'skipped' for s in cache_tail[after:]))
                self.assertEqual(successful, not fault or fault.startswith('cancel_'))

    def test_release_full_block_and_retired_oc_retention(self):
        for case in ('current', 'stale', 'api_failure', 'empty', 'malformed', 'create_failure'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                target, data = self.fixture(base)
                (target / 'profiles.json').write_text(json.dumps(data))
                self.assertEqual(self.run_block(base, 'Validate and stage firmware').returncode, 0)
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
                result = self.run_block(base, 'Publish firmware and prune releases', CASE=case)
                self.assertEqual(result.returncode, 24 if case == 'create_failure' else 0, result.stderr)
                calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
                if case not in ('current', 'create_failure'):
                    self.assertEqual(len(calls), 1)
                    # Successful skip leaves already-saved caches untouched.
                    self.assertEqual(result.returncode, 0)
                else:
                    create = calls[1]
                    self.assertEqual(create[:2], ['release', 'create'])
                    self.assertEqual(create[create.index('--target') + 1], 'a' * 40)
                    self.assertEqual(create[3], 'firmware/' + IMAGE)
                    deletes = [c[-1] for c in calls if c[:2] == ['release', 'delete']]
                    prefix = 'W1700K-OpenWrt'
                    self.assertEqual(set(deletes), {prefix + '_r1', prefix + '-r1-old', 'W1700K-ubi2_old'} if case == 'current' else set())


if __name__ == '__main__':
    unittest.main()
