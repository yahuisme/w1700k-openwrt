"""Bootstrap snapshot producer/consumer boundaries; execute real YAML shell."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml
from test_cache_workflow import render_env

ROOT = Path(__file__).resolve().parents[1]


def steps():
    return yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())['jobs']['build']['steps']


class BootstrapWorkflowTests(unittest.TestCase):
    def test_exact_conditional_restore_and_early_snapshot(self):
        all_steps = steps()
        by_id = {s['id']: s for s in all_steps if 'id' in s}
        self.assertIn('tb_inputs', by_id)
        self.assertIn('tb', by_id)
        self.assertNotIn('restore-keys', by_id['tb']['with'])
        self.assertEqual(by_id['tb']['with']['path'], 'tbarchive')
        self.assertEqual(by_id['tb']['if'], "steps.tc_restore.outputs.hit != 'true'")
        extract = next(s for s in all_steps if s['name'] == 'Extract compiler bootstrap')
        compile_step = next(s for s in all_steps if s['name'] == 'Compile firmware')
        self.assertLess(all_steps.index(by_id['tc']), all_steps.index(by_id['tb_inputs']))
        self.assertLess(all_steps.index(by_id['tb']), all_steps.index(extract))
        self.assertLess(all_steps.index(extract), all_steps.index(compile_step))
        self.assertIn('steps.tb_restore.outputs.hit', compile_step['env']['BOOTSTRAP_SAVE'])
        self.assertIn('steps.tc_restore.outputs.hit', compile_step['env']['BOOTSTRAP_RECHECK'])
        self.assertNotIn('bootstrap_cache.py pack', next(s['run'] for s in all_steps if s['name'] == 'Prepare build caches'))

    def test_production_compile_packs_before_world_and_rechecks_restored_stamps(self):
        item = next(s for s in steps() if s['name'] == 'Compile firmware')
        block = item['run']
        for recheck, save, pack_status, main_status in (
                ('true', 'true', 0, 0), ('true', 'false', 0, 0),
                ('false', 'false', 0, 0), ('true', 'true', 19, 0),
                ('true', 'true', 0, 23)):
            with self.subTest(recheck=recheck, save=save, pack=pack_status, main=main_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cc = root / 'staging_dir/host/bin/ccache'
                cc.parent.mkdir(parents=True)
                cc.write_text('#!/bin/bash\nprintf "ccache %s\\n" "$*" >> "$LOG"\n')
                cc.chmod(0o755)
                values = {'steps.tc_restore.outputs.hit': 'false' if recheck == 'true' else 'true',
                          'steps.tb_restore.outputs.hit': 'false' if save == 'true' else 'true',
                          'steps.tc_restore.outputs.poisoned': 'false',
                          'steps.tb_restore.outputs.poisoned': 'false',
                          'steps.tb_inputs.outputs.key': 'tb-v1-ubi2-test'}
                env = dict(os.environ, **render_env(item, values), DK_OPENWRT=tmp,
                           LOG=str(root / 'calls'), PACK_STATUS=str(pack_status), MAIN_STATUS=str(main_status))
                prefix = '''
                docker_exec() { shift; "$@"; }
                make() {
                  printf 'make %s\\n' "$*" >> "$LOG"
                  [[ "$*" == tools/ccache/compile* ]] || return "$MAIN_STATUS"
                }
                python3() { printf 'pack %s\\n' "$*" >> "$LOG"; return "$PACK_STATUS"; }
                rm() { printf 'remove failed archive\\n' >> "$LOG"; }
                export -f docker_exec make python3 rm
                '''
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + block], env=env,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, main_status, result.stderr)
                calls = (root / 'calls').read_text().splitlines()
                bootstrap = [i for i, line in enumerate(calls) if line.startswith('make tools/ccache/compile')]
                packed = [i for i, line in enumerate(calls) if line.startswith('pack ')]
                world = next(i for i, line in enumerate(calls) if re.match(r'make -j[0-9]+$', line))
                self.assertEqual(bool(bootstrap), recheck == 'true')
                self.assertEqual(bool(packed), save == 'true')
                if packed:
                    self.assertLess(bootstrap[0], packed[0])
                    self.assertLess(packed[0], world)
                self.assertEqual('remove failed archive' in calls, bool(pack_status))

    def test_key_shell_rejects_failure_and_malformed_digest(self):
        block = next(s['run'] for s in steps() if s.get('id') == 'tb_inputs')
        for status, digest in ((0, 'a' * 64), (17, 'a' * 64), (0, 'bad')):
            with self.subTest(status=status, digest=digest), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'output'
                env = dict(os.environ, GITHUB_OUTPUT=str(output), DK_OPENWRT='/build',
                           BUILDER_FINGERPRINT='b' * 64, TOOLCHAIN_KEY='tc-v3-ubi2-test',
                           KEY_STATUS=str(status), DIGEST=digest)
                prefix = 'docker_exec() { printf "%s\\n" "$DIGEST"; return "$KEY_STATUS"; };\n'
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + block],
                                        env=env, text=True, capture_output=True)
                if status or digest == 'bad':
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_text(), 'key=tb-v1-ubi2-' + digest + '\n')

    def test_bootstrap_save_is_confirmed_before_next_tier(self):
        all_steps = steps()
        by_id = {s['id']: s for s in all_steps if 'id' in s}
        self.assertIn('tb_budget', by_id)
        admission = by_id['tb_budget']
        save = next(s for s in all_steps if s.get('uses') == 'actions/cache/save@v6' and s['with']['path'] == 'tbarchive')
        cleanup = next(s for s in all_steps if s['name'] == 'Prune old bootstrap caches')
        self.assertEqual(all_steps.index(save), all_steps.index(admission) + 1)
        self.assertEqual(all_steps.index(cleanup), all_steps.index(save) + 1)
        self.assertLess(all_steps.index(cleanup), all_steps.index(by_id['dl_budget']))
        self.assertIn('tb-v1-ubi2-', admission['run'])
        self.assertIn('tb-v1-ubi2-', cleanup['run'])
        self.assertEqual(cleanup['if'], "steps.tb_budget.outputs.save == 'true'")
        self.assertNotIn('continue-on-error', cleanup)


if __name__ == '__main__':
    unittest.main()
