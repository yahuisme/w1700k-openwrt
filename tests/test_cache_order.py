"""Execute complete cache-tail YAML blocks with local gh/save fixtures only."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import yaml
from test_cache_helper import GH, entry

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())['jobs']['build']['steps']
# Reconstructed from run 34728875877 inventory total and the three recorded
# upload sizes (34706572059, 34711268819, current API). IDs are fixture-only.
REAL = [entry(1, 'tc-v3-ubi2-oc-a8b702', 1564072318),
        entry(2, 'cc-v3-ubi2-oc.34706572059.1', 534728921),
        entry(3, 'cc-v3-ubi2-oc.34711268819.1', 534835080)]


class CacheOrderTests(unittest.TestCase):
    def run_tail(self, entries, target='ubi2-oc', warm=False, cc=535453831,
                 tc=1575367741, fault='', fail_reads=(), delay=0, toolchain_first=False):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'scripts').symlink_to(ROOT / 'scripts')
            state = base / 'state.json'
            state.write_text(json.dumps(dict(entries=entries, calls=[], reads=0,
                                             fail_reads=list(fail_reads), fail_delete=2 if fault == 'delete' else -1)))
            # Keep actual helper/retry execution; expose pending save after N reads.
            gh = GH.replace("entries = s['entries']", """if s.get('pending') and s['reads'] >= s['visible_at']:
        s['entries'].append(s.pop('pending'))
        p.write_text(json.dumps(s))
    entries = s['entries']""")
            (base / 'gh').write_text(gh)
            (base / 'gh').chmod(0o755)
            paths = {'cc': 'ccarchive/ccache.tar.gz', 'tc': 'tcarchive/toolchain.tar.gz', 'dl': 'dlarchive/dl.tar.gz'}
            for kind, size in [('cc', cc), ('tc', tc), ('dl', 100)]:
                p = base / paths[kind]
                p.parent.mkdir()
                if size is not None:
                    with p.open('wb') as f:
                        f.truncate(size)
            values = {'matrix.target': target, 'steps.tc.outputs.cache-hit': 'true' if warm else 'false',
                      'steps.inputs.outputs.key': f'tc-v3-{target}-new',
                      'steps.gh.outputs.cache-primary-key': f'cc-v3-{target}.new',
                      'steps.dl.outputs.cache-primary-key': 'dl-v3.new',
                      'steps.dl_changed.outputs.save': 'true'}
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       MOCK_STATE=str(state), GITHUB_REF='refs/heads/main', GITHUB_OUTPUT=str(base / 'output'))
            def resolve(expr):
                if expr.startswith('hashFiles('):
                    return 'present' if (base / expr.split("'")[1]).exists() else ''
                return values.get(expr, '')
            def condition(expr):
                expr = re.sub(r"hashFiles\('[^']+'\)|(?:steps|matrix)\.[\w.-]+", lambda m: repr(resolve(m[0])), expr)
                # Only trusted repository YAML comparisons and repr-quoted fixture
                # literals reach eval; no event input or network text is evaluated.
                return eval(expr.replace('&&', ' and '), {'__builtins__': {}})
            start = next(i for i, s in enumerate(STEPS) if s.get('id') in ('tc_budget', 'cc_budget'))
            successful = True
            saves, logs = [], []
            tail = STEPS[start:]
            if toolchain_first:
                # Historical ordering comparison, same complete YAML blocks.
                tail = tail[3:6] + tail[:3] + tail[6:]
            for step in tail:
                if not successful or not condition(step.get('if', 'True')):
                    continue
                if 'run' in step:
                    text = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda m: resolve(m[1]), step['run'])
                    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', text], cwd=base, env=env, text=True, capture_output=True)
                    logs.append(step['name'] + '\n' + result.stdout + result.stderr)
                    successful = result.returncode == 0
                    if step.get('id') and (base / 'output').exists():
                        for line in (base / 'output').read_text().splitlines():
                            k, v = line.split('=', 1)
                            values[f"steps.{step['id']}.outputs.{k}"] = v
                        (base / 'output').unlink()
                else:
                    key = re.sub(r'\$\{\{\s*(.*?)\s*\}\}', lambda m: resolve(m[1]), step['with']['key'])
                    kind = step['with']['path'][:2]
                    saves.append(kind)
                    if fault == 'action_failure':
                        successful = False
                        continue
                    s = json.loads(state.read_text())
                    if fault != 'warning':
                        size = (535186562 if cc == 535453831 else cc) if kind == 'cc' else tc if kind == 'tc' else 100
                        new = entry(100 + len(saves), key, size)
                        if fault == 'zero': new['size_in_bytes'] = 0
                        if fault == 'wrong_ref': new['ref'] = 'refs/heads/other'
                        if delay:
                            s.update(pending=new, visible_at=s['reads'] + delay + 1)
                        else:
                            s['entries'].append(new)
                    state.write_text(json.dumps(s))
            return saves, json.loads(state.read_text()), '\n'.join(logs)

    def test_actual_oc_inventory_seeds_both_after_cc_retention(self):
        self.assertEqual(sum(e['size_in_bytes'] for e in REAL), 2633636319)
        saves, state, log = self.run_tail(REAL)
        self.assertEqual(saves, ['cc', 'tc'], log)
        self.assertIn('inventory=2099258880 candidate+margin=1642476605', log)
        self.assertEqual({e['key'] for e in state['entries']}, {'cc-v3-ubi2-oc.new', 'tc-v3-ubi2-oc-new'})

    def test_unconfirmed_upload_blocks_later_admission(self):
        saves, state, log = self.run_tail(REAL, fault='warning')
        self.assertEqual(saves, ['cc'], log)
        self.assertNotIn('Check toolchain cache budget', log)
        self.assertEqual(state['entries'], REAL)

    def test_cold_and_warm_both_groups(self):
        for target in ('ubi2', 'ubi2-oc'):
            for warm in (False, True):
                with self.subTest(target=target, warm=warm):
                    saves, _, log = self.run_tail([], target=target, warm=warm)
                    self.assertEqual(saves, ['cc'] + ([] if warm else ['tc']) + (['dl'] if target == 'ubi2' else []), log)

    def test_budget_denial_allows_smaller_later_candidate(self):
        saves, _, log = self.run_tail([entry(1, 'legacy', 2600000000)], cc=1500000000, tc=100)
        self.assertEqual(saves, ['tc'], log)
        saves, _, log = self.run_tail([entry(1, 'legacy', 2600000000)], target='ubi2', cc=100, tc=2000000001)
        self.assertEqual(saves, ['cc', 'dl'], log)

    def test_missing_archive_and_admission_api_failure_can_continue(self):
        for options in ({'cc': None}, {'fail_reads': [1]}):
            saves, _, log = self.run_tail([], **options)
            self.assertEqual(saves, ['tc'], log)

    def test_upload_and_cleanup_failures_fail_closed(self):
        for options in ({'fault': 'zero'}, {'fault': 'wrong_ref'}, {'fault': 'action_failure'},
                        {'fail_reads': [2]}, {'fail_reads': [3]}, {'fault': 'delete'}):
            with self.subTest(options=options):
                saves, _, log = self.run_tail(REAL, **options)
                self.assertEqual(saves, ['cc'], log)
                self.assertNotIn('Check toolchain cache budget', log)

    def test_delayed_confirmation_then_prune_allows_toolchain(self):
        saves, state, log = self.run_tail(REAL, delay=2)
        self.assertEqual(saves, ['cc', 'tc'], log)
        self.assertEqual(len(state['entries']), 2)

    def test_toolchain_unconfirmed_blocks_download_after_cc_denial(self):
        saves, state, log = self.run_tail([], target='ubi2', cc=None, fault='warning')
        self.assertEqual(saves, ['tc'], log)
        self.assertNotIn('Check download cache budget', log)
        self.assertEqual(state['entries'], [])

    def test_actual_warm_inventory_and_peer_ref_protection(self):
        for target in ('ubi2', 'ubi2-oc'):
            with self.subTest(target=target):
                entries = [entry(1, f'tc-v3-{target}-new', 1564072318),
                           entry(2, f'cc-v3-{target}.old', 534835080),
                           entry(3, 'cc-v3-ubi2-oc.peer' if target == 'ubi2' else 'cc-v3-ubi2.peer', 100),
                           entry(4, f'cc-v3-{target}.other', 100, 'refs/heads/other')]
                saves, state, log = self.run_tail(entries, target=target, warm=True)
                self.assertEqual(saves, ['cc'] + (['dl'] if target == 'ubi2' else []), log)
                self.assertTrue({1, 3, 4} <= {e['id'] for e in state['entries']})
                self.assertNotIn(2, {e['id'] for e in state['entries']})

    def test_order_is_not_universal_toolchain_priority(self):
        # Explicit synthetic counterexample: cc growth can consume tc headroom.
        entries = [entry(1, 'tc-v3-ubi2-oc-old', 1900000000), entry(2, 'cc-v3-ubi2-oc.old', 100000000)]
        saves, _, log = self.run_tail(entries, cc=1500000000, tc=1900000000)
        self.assertEqual(saves, ['cc'], log)
        self.assertLessEqual(2000000000 + 1900000000 + 67108864, 4000000000)
        before, _, old_log = self.run_tail(entries, cc=1500000000, tc=1900000000,
                                          toolchain_first=True)
        self.assertEqual(before, ['tc', 'cc'], old_log)


if __name__ == '__main__':
    unittest.main()
