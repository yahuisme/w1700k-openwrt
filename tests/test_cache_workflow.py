#!/usr/bin/env python3
"""Local-only workflow tests: no Docker, GitHub API, or remote writes."""
import os
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
import unittest
import yaml

from workflow_fixture import ENTRY, WORKFLOW, build_job, selected_inputs, workflow

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = workflow()
JOB = build_job(DOCUMENT)
MATRIX = selected_inputs()
WORKFLOW_ENV = {**DOCUMENT['env'], **JOB['env']}
os.environ['SYSTEM'] = WORKFLOW_ENV['SYSTEM']
os.environ['DISTRO_TITLE'] = WORKFLOW_ENV['DISTRO_TITLE']
# Resolve parsed string values, not dumped YAML (which can wrap expressions).
# Only production env is substituted; step outputs remain fixture inputs.
def resolve_production_env(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r'\$\{\{\s*env\.(\w+)\s*\}\}',
                      lambda match: WORKFLOW_ENV[match[1]], value)
    if isinstance(value, list):
        return [resolve_production_env(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_production_env(item) for key, item in value.items()}
    return value


STEPS = resolve_production_env(JOB['steps'])


def step(name):
    return next(s for s in STEPS if s.get('name') == name or s.get('id') == name)


def render(text, values):
    values = {**{'env.' + key: value for key, value in WORKFLOW_ENV.items()}, **values}
    return re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda m: values.get(m[1].strip(), 'fixture'), text)


def render_env(item, values):
    """Render this workflow's trusted boolean/string env expressions only."""
    values = {**{'env.' + key: value for key, value in WORKFLOW_ENV.items()}, **values}
    def value(match):
        expression = match[1].strip()
        if expression in values:
            return values[expression]
        expression = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), expression)
        result = eval(expression.replace('&&', ' and ').replace('||', ' or '), {'__builtins__': {}})
        if not isinstance(result, bool):
            raise ValueError('unsupported workflow environment expression')
        return str(result).lower()
    return {name: re.sub(r'\$\{\{\s*(.*?)\s*\}\}', value, text)
            for name, text in item.get('env', {}).items()}


class WorkflowTests(unittest.TestCase):
    def test_production_env_is_resolved_without_consuming_step_mocks(self):
        self.assertEqual(JOB['env']['SYSTEM'], MATRIX['system'])
        for name, tier in (('TC_PREFIX', 'tc'), ('CC_PREFIX', 'cc'),
                           ('DL_PREFIX', 'dl'), ('TB_PREFIX', 'tb')):
            with self.subTest(name=name):
                self.assertEqual(WORKFLOW_ENV[name], MATRIX[tier])
                text = '${{ env.' + name + ' }}${{ steps.mock.outputs.key }}'
                self.assertEqual(render(text, {'steps.mock.outputs.key': 'mock-key'}),
                                 MATRIX[tier] + 'mock-key')
                self.assertEqual(render_env({'env': {'PREFIX': '${{ env.' + name + ' }}'}}, {}),
                                 {'PREFIX': MATRIX[tier]})
        self.assertIn('steps.inputs.outputs.key', step('tc')['with']['key'])
        self.assertNotIn('env.CC_PREFIX', step('gh')['with']['key'])
        self.assertIn("cache_helper.py admit '" + MATRIX['cc'] + "'", step('cc_budget')['run'])
        for item in STEPS:
            self.assertNotRegex(json.dumps(item), r'\$\{\{\s*env\.')

    def test_compile_nested_block(self):
        block = step('Compile firmware')['run']
        for case, hot, pre, main, fallback, stats, expected in (
            ('cold', False, 0, 0, 0, 0, 0), ('hot', True, 0, 0, 0, 0, 0),
            ('precompile_failure', False, 17, 0, 0, 0, 17),
            ('fallback_success', False, 0, 1, 0, 0, 0),
            ('final_failure', True, 0, 1, 23, 0, 23),
            ('stats_failure', True, 0, 0, 0, 31, 0),
            ('final_and_stats_failure', True, 0, 1, 23, 31, 23),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                cc = base / 'staging_dir/host/bin/ccache'
                cc.parent.mkdir(parents=True)
                stub = base / 'ccache-stub'
                stub.write_text('#!/bin/bash\nprintf "ccache %s\\n" "$*" >> "$LOG"\n[[ "$*" != *-sz ]] || exit "$STATS"\n')
                stub.chmod(0o755)
                if hot:
                    cc.write_bytes(stub.read_bytes())
                    cc.chmod(0o755)
                env = dict(os.environ, DK_OPENWRT=tmp, LOG=str(base / 'calls'),
                           PRE=str(pre), MAIN=str(main), FALLBACK=str(fallback),
                           STATS=str(stats), STUB=str(stub),
                           **render_env(step('Compile firmware'), {
                               'steps.tc_restore.outputs.hit': 'true' if hot else 'false',
                               'steps.tb_restore.outputs.hit': 'true',
                               'steps.tb_inputs.outputs.key': 'tb-fixture'}))
                prefix = '''
                docker_exec() { shift; "$@"; }
                nproc() { printf '4\\n'; }
                make() {
                  printf 'make %s\\n' "$*" >> "$LOG"
                  [ "$CCACHE_MAXSIZE" = 3G ] || { printf 'Expected CCACHE_MAXSIZE=3G, got %s\\n' "$CCACHE_MAXSIZE" >&2; return 98; }
                  if [[ "$*" == tools/ccache/compile* ]]; then
                    [ "$PRE" = 0 ] || return "$PRE"
                    cp "$STUB" staging_dir/host/bin/ccache
                    return 0
                  fi
                  if [[ "$1" == -j1 ]]; then return "$FALLBACK"; fi
                  return "$MAIN"
                }
                export -f docker_exec make nproc
                '''
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + block], env=env, capture_output=True, text=True)
                calls = (base / 'calls').read_text().splitlines()
                want = [] if hot else ['make tools/ccache/compile -j5']
                if not pre:
                    want += ['ccache -d /ghcache --zero-stats', 'make -j5']
                    if main:
                        want += ['make -j1 V=s']
                    want += ['ccache -d /ghcache -sz']
                self.assertEqual(calls, want)
                self.assertEqual(result.returncode, expected, result.stderr)
                print(f'{case}: exit={result.returncode}; ' + ' -> '.join(calls))

    def test_all_run_shell_syntax(self):
        for s in STEPS:
            if 'run' in s:
                result = subprocess.run(['bash', '-n'], input=render(s['run'], {}), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, (s.get('name'), result.stderr))

    def test_download_gates_and_pack(self):
        snapshot = step('Prepare build environment')
        check = step('Check download cache changes')

        self.assertLess(STEPS.index(snapshot), STEPS.index(step('Prepare source and cache key')))
        self.assertLess(STEPS.index(step('Compile firmware')), STEPS.index(check))
        self.assertIn('--restored', check['run'])
        admit = step('dl_budget')
        save = next(s for s in STEPS if s.get('uses') == 'actions/cache/save@v6' and s['with']['path'] == 'dlarchive')
        self.assertNotIn('hashFiles(', admit.get('if', ''))
        self.assertNotIn('hashFiles(', save.get('if', ''))
        for changed in ('true', 'false', ''):
            for admitted in ('true', 'false', ''):
                values = {'steps.dl_changed.outputs.save': changed,
                          'steps.dl_budget.outputs.save': admitted}
                for s, expected in (
                    (check, True),
                    (admit, changed == 'true'),
                    (save, changed == 'true' and admitted == 'true'),
                ):
                    condition = s.get('if', 'True')
                    for key in sorted(values, key=len, reverse=True):
                        condition = condition.replace(key, repr(values[key]))
                    # Only trusted local workflow comparisons and fixture literals;
                    # no event input, network data, or builtins are evaluated.
                    self.assertEqual(eval(condition.replace('&&', ' and '), {'__builtins__': {}}), expected)
            values = {'steps.dl_changed.outputs.save': changed,
                      'steps.tc_restore.outputs.hit': 'true'}
            block = render(step('Prepare build caches')['run'], values)
            # This check isolates packing; complete merged execution is tested separately.
            block = block.split('python3 scripts/cache_helper.py admit', 1)[0]
            stub = 'docker_exec() { printf "%s\\n" "$*"; }; sudo() { :; };\n'
            result = subprocess.run(['bash', '-e', '-c', stub + block], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual('cache.py dl /dlcache' in result.stdout, changed == 'true')
            self.assertIn('cache.py ccache /ghcache', result.stdout)

    def test_snapshot_and_post_compile_check_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
            dl = base / 'dlcache'
            dl.mkdir()
            source = dl / 'restored.tar'
            source.write_bytes(b'restored')
            output = base / 'output'
            env = dict(os.environ, RUNNER_TEMP=tmp, GITHUB_OUTPUT=str(output))
            def run(name):
                block = render(step(name)['run'], {'steps.dl_restore.outputs.matched-key': MATRIX['dl'] + 'old'})
                if name == 'Prepare build environment':
                    block = block.split('[ -f "user/default/config.diff" ]', 1)[0]
                result = subprocess.run(['bash', '-e', '-c', 'sudo() { "$@"; };\n' + block],
                                        cwd=base, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            run('Prepare build environment')
            run('Check download cache changes')
            self.assertEqual(output.read_text().splitlines()[-1], 'save=false')
            module = dl / 'go-mod-cache/module.zip'
            module.parent.mkdir()
            module.write_bytes(b'added during compile')
            run('Check download cache changes')
            self.assertEqual(output.read_text().splitlines()[-1], 'save=true')

    def test_cache_restore_contract(self):
        tc = step('tc')
        self.assertNotIn('restore-keys', tc['with'])
        self.assertEqual(tc['with']['path'], 'tcarchive')
        self.assertIn('steps.inputs.outputs.key', tc['with']['key'])
        for name, path, prefix in [('gh', 'ccarchive', MATRIX['cc']),
                                  ('dl', 'dlarchive', MATRIX['dl'])]:
            restore = step(name)
            self.assertEqual(restore['with']['path'], path)
            self.assertEqual(restore['with']['restore-keys'], prefix)
            self.assertIn('github.run_id', restore['with']['key'])
            self.assertIn('github.run_attempt', restore['with']['key'])

    def test_clear_step_names_and_source_key_grouping(self):
        names = [s.get('name', '') for s in STEPS]
        self.assertTrue(all(names))
        self.assertEqual(len(names), len(set(names)))
        source = step('inputs')
        self.assertEqual(source['name'], 'Prepare source and cache key')
        self.assertNotIn('make download', source['run'])
        self.assertLess(source['run'].index('make defconfig'), source['run'].index('KEY=$(docker_exec'))
        self.assertEqual(STEPS.index(step('tc')), STEPS.index(source) + 1)

    def test_source_key_success_and_failure(self):
        block = render(step('inputs')['run'], {})
        stub = '''docker_exec() {
            if [ "$2" = bash ]; then
                printf 'source\n' >> "$LOG"
                return "$SOURCE_STATUS"
            fi
            printf 'key\n' >> "$LOG"
            [ "$KEY_STATUS" = 0 ] || return "$KEY_STATUS"
            printf 'fixture-key\n'
        }
'''
        for source_status, key_status in ((0, 0), (17, 0), (0, 23)):
            with self.subTest(source=source_status, key=key_status), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output = base / 'output'
                env = dict(os.environ, LOG=str(base / 'calls'), GITHUB_OUTPUT=str(output),
                           SOURCE_STATUS=str(source_status), KEY_STATUS=str(key_status),
                           DK_OPENWRT='/build', BUILDER_FINGERPRINT='fixture-builder')
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', stub + block],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, source_status or key_status, result.stderr)
                self.assertEqual((base / 'calls').read_text().splitlines(),
                                 ['source'] if source_status else ['source', 'key'])
                if source_status or key_status:
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(output.read_text(),
                                     f"key={MATRIX['tc']}fixture-key\n")

    def test_single_profile_config_matches_staged_profile(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        self.assertEqual(workflow['env']['DK_PROFILE'], '/bld/user/default')
        block = step('inputs')['run']
        start = block.index('cp $DK_PROFILE/config.diff .config')
        end = block.index('cp -r', start)
        with tempfile.TemporaryDirectory() as tmp:
            profile = ROOT / 'user/default'
            original = (profile / 'config.diff').read_bytes()
            result = subprocess.run(['bash', '-e', '-c', block[start:end]], cwd=tmp,
                                    env=dict(os.environ, DK_PROFILE=str(profile)),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((Path(tmp) / '.config').read_bytes(),
                             original + b'CONFIG_CCACHE_DIR="/ghcache"\n')
            self.assertEqual((profile / 'config.diff').read_bytes(), original)
            result = subprocess.run(['bash', '-e', '-c', block[start:end]], cwd=tmp,
                                    env=dict(os.environ, DK_PROFILE=tmp),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_unpack_creates_download_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = render(step('Prepare build environment')['run'], {})
            block = block.split('[ -f "user/default/config.diff" ]', 1)[0]
            stub = 'sudo() { printf "%s\\n" "$*"; };\n'
            result = subprocess.run(['bash', '-e', '-c', stub + block], cwd=tmp,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('dlcache.py snapshot', result.stdout)

    def test_cache_save_cleanup_order_and_failure_gates(self):
        workflow = yaml.safe_load(ENTRY.read_text())
        self.assertEqual(workflow['concurrency'], {'group': 'w1700k-cache', 'cancel-in-progress': False})
        self.assertEqual(workflow['jobs']['immortalwrt']['needs'], 'openwrt')
        previous = -1
        for kind, path in [('cc', 'ccarchive'), ('tc', 'tcarchive'), ('dl', 'dlarchive')]:
            admission = step(kind + '_budget')
            save = next(s for s in STEPS if s.get('uses') == 'actions/cache/save@v6'
                        and s['with']['path'] == path)
            cleanup = step('Prune old ' + {'tc': 'toolchain', 'cc': 'compiler', 'dl': 'download'}[kind] + ' caches')
            self.assertLess(previous, STEPS.index(admission))
            self.assertEqual(STEPS.index(save), STEPS.index(admission) + 1)
            self.assertEqual(STEPS.index(cleanup), STEPS.index(save) + 1)
            previous = STEPS.index(cleanup)
            self.assertIn('cache_helper.py admit', admission['run'])
            self.assertIn('cache_helper.py cleanup', cleanup['run'])
            self.assertTrue(cleanup['if'].startswith(f"steps.{kind}_budget.outputs.save == 'true'"))
            for s in (admission, save, cleanup):
                # Without a status function GitHub supplies success(): failed
                # upload skips cleanup and all subsequent saves. Warning-only
                # uploads reach the helper, whose missing-key test prevents deletion.
                self.assertNotRegex(s.get('if', ''), r'\b(always|failure|cancelled)\(')
                self.assertFalse(s.get('continue-on-error', False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
