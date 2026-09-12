#!/usr/bin/env python3
"""Local-only workflow tests: no Docker, GitHub API, or remote writes."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/W1700K.yaml'
STEPS = yaml.safe_load(WORKFLOW.read_text())['jobs']['build']['steps']


def step(name):
    return next(s for s in STEPS if s.get('name') == name or s.get('id') == name)


def render(text, values):
    return re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda m: values.get(m[1], 'fixture'), text)


class WorkflowTests(unittest.TestCase):
    def test_compile_nested_block(self):
        block = step('Compile')['run']
        for case, hot, pre, main, fallback, expected in (
            ('cold', False, 0, 0, 0, 0), ('hot', True, 0, 0, 0, 0),
            ('precompile_failure', False, 17, 0, 0, 17),
            ('fallback_success', False, 0, 1, 0, 0),
            ('final_failure', True, 0, 1, 23, 23),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory(dir=ROOT / 'tests') as tmp:
                base = Path(tmp)
                cc = base / 'staging_dir/host/bin/ccache'
                cc.parent.mkdir(parents=True)
                stub = base / 'ccache-stub'
                stub.write_text('#!/bin/bash\nprintf "ccache %s\\n" "$*" >> "$LOG"\n[[ "$*" != *-sz ]] || exit 31\n')
                stub.chmod(0o755)
                if hot:
                    cc.write_bytes(stub.read_bytes())
                    cc.chmod(0o755)
                env = dict(os.environ, DK_OPENWRT=tmp, LOG=str(base / 'calls'),
                           PRE=str(pre), MAIN=str(main), FALLBACK=str(fallback), STUB=str(stub))
                prefix = '''
                docker_exec() { shift; "$@"; }
                nproc() { printf '4\\n'; }
                make() {
                  printf 'make %s\\n' "$*" >> "$LOG"
                  if [[ "$*" == tools/ccache/compile* ]]; then
                    [ "$PRE" = 0 ] || return "$PRE"
                    cp "$STUB" staging_dir/host/bin/ccache
                    return 0
                  fi
                  if [[ "$*" == *V=s* ]]; then return "$FALLBACK"; fi
                  return "$MAIN"
                }
                export -f docker_exec make nproc
                '''
                result = subprocess.run(['bash', '-e', '-c', prefix + block], env=env, capture_output=True, text=True)
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
        snapshot = step('Unpack caches')
        check = step('Check downloads')

        self.assertLess(STEPS.index(snapshot), STEPS.index(step('Prepare source')))
        self.assertLess(STEPS.index(step('Compile')), STEPS.index(check))
        self.assertIn('--restored', check['run'])
        admit = step('dl_budget')
        save = next(s for s in STEPS if s.get('uses') == 'actions/cache/save@main' and s['with']['path'] == 'dlarchive')
        for target in ('ubi2', 'ubi2-oc'):
            for changed in ('true', 'false', ''):
                for admitted in ('true', 'false', ''):
                    for archive in ('present', ''):
                        values = {'matrix.target': target, 'steps.dl_changed.outputs.save': changed,
                                  'steps.dl_budget.outputs.save': admitted,
                                  "hashFiles('dlarchive/dl.tar.gz')": archive}
                        for s, expected in (
                            (check, target == 'ubi2'),
                            (admit, target == 'ubi2' and changed == 'true'),
                            (save, target == 'ubi2' and changed == 'true' and admitted == 'true' and bool(archive)),
                        ):
                            condition = s['if']
                            for key in sorted(values, key=len, reverse=True):
                                condition = condition.replace(key, repr(values[key]))
                            # Only trusted local workflow comparisons and fixture literals;
                            # no event input, network data, or builtins are evaluated.
                            self.assertEqual(eval(condition.replace('&&', ' and '), {'__builtins__': {}}), expected)
                values = {'matrix.target': target, 'steps.dl_changed.outputs.save': changed,
                          'steps.tc.outputs.cache-hit': 'true'}
                block = render(step('Pack caches')['run'], values)
                stub = 'docker_exec() { printf "%s\\n" "$*"; }; sudo() { :; };\n'
                result = subprocess.run(['bash', '-e', '-c', stub + block], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('cache.py dl /dlcache' in result.stdout, target == 'ubi2' and changed == 'true')
                self.assertIn('cache.py ccache /ghcache', result.stdout)

    def test_snapshot_and_post_compile_check_blocks(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'tests') as tmp:
            base = Path(tmp)
            (base / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
            dl = base / 'dlcache'
            dl.mkdir()
            source = dl / 'restored.tar'
            source.write_bytes(b'restored')
            output = base / 'output'
            env = dict(os.environ, RUNNER_TEMP=tmp, GITHUB_OUTPUT=str(output))
            def run(name):
                block = render(step(name)['run'], {'steps.dl.outputs.cache-matched-key': 'dl-v3.old',
                                                  'matrix.target': 'ubi2'})
                result = subprocess.run(['bash', '-e', '-c', 'sudo() { "$@"; };\n' + block],
                                        cwd=base, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            run('Unpack caches')
            run('Check downloads')
            self.assertEqual(output.read_text(), 'save=false\n')
            module = dl / 'go-mod-cache/module.zip'
            module.parent.mkdir()
            module.write_bytes(b'added during compile')
            run('Check downloads')
            self.assertEqual(output.read_text(), 'save=false\nsave=true\n')

    def test_cache_restore_contract(self):
        tc = step('tc')
        self.assertNotIn('restore-keys', tc['with'])
        self.assertEqual(tc['with']['path'], 'tcarchive')
        self.assertIn('steps.inputs.outputs.key', tc['with']['key'])
        for name, path, prefix in [('gh', 'ccarchive', 'cc-v3-'), ('dl', 'dlarchive', 'dl-v3.')]:
            restore = step(name)
            self.assertEqual(restore['with']['path'], path)
            self.assertTrue(restore['with']['restore-keys'].startswith(prefix))
            self.assertIn('github.run_id', restore['with']['key'])
            self.assertIn('github.run_attempt', restore['with']['key'])
        self.assertFalse(any('legacy' in s.get('name', '').lower() for s in STEPS))
        self.assertNotIn('stcache', WORKFLOW.read_text())

    def test_short_explicit_step_names(self):
        names = [s.get('name', '') for s in STEPS]
        self.assertTrue(all(names))
        self.assertTrue(all(len(name) <= 24 for name in names))
        self.assertEqual(len(names), len(set(names)))

    def test_unpack_snapshot_writer_only(self):
        for target in ('ubi2', 'ubi2-oc'):
            with tempfile.TemporaryDirectory() as tmp:
                block = render(step('Unpack caches')['run'], {'matrix.target': target})
                stub = 'sudo() { printf "%s\\n" "$*"; };\n'
                result = subprocess.run(['bash', '-e', '-c', stub + block], cwd=tmp,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('dlcache.py snapshot' in result.stdout, target == 'ubi2')

    def test_cache_save_cleanup_order_and_failure_gates(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        self.assertEqual(workflow['concurrency'], {'group': 'w1700k-cache', 'cancel-in-progress': False})
        self.assertEqual(workflow['jobs']['build']['strategy']['matrix']['target'], ['ubi2', 'ubi2-oc'])
        previous = -1
        for kind, path in [('tc', 'tcarchive'), ('cc', 'ccarchive'), ('dl', 'dlarchive')]:
            admission = step(kind + '_budget')
            save = next(s for s in STEPS if s.get('uses') == 'actions/cache/save@main'
                        and s['with']['path'] == path)
            cleanup = step(f'Prune {kind}')
            self.assertLess(previous, STEPS.index(admission))
            self.assertEqual(STEPS.index(save), STEPS.index(admission) + 1)
            self.assertEqual(STEPS.index(cleanup), STEPS.index(save) + 1)
            previous = STEPS.index(cleanup)
            self.assertIn('cache_helper.py admit', admission['run'])
            self.assertIn('cache_helper.py cleanup', cleanup['run'])
            self.assertEqual(cleanup['if'], f"steps.{kind}_budget.outputs.save == 'true'")
            for s in (admission, save, cleanup):
                # Without a status function GitHub supplies success(): failed
                # upload skips cleanup and all subsequent saves. Warning-only
                # uploads reach the helper, whose missing-key test prevents deletion.
                self.assertNotRegex(s.get('if', ''), r'\b(always|failure|cancelled)\(')
                self.assertFalse(s.get('continue-on-error', False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
