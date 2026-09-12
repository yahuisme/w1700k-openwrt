#!/usr/bin/env python3
"""Safety tests use an isolated gh executable; never contact GitHub."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/cache_helper.py'
spec = importlib.util.spec_from_file_location('cache_helper', HELPER)
assert spec is not None and spec.loader is not None
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
REF = 'refs/heads/main'


def entry(i, key, size=100, ref=REF):
    return dict(id=i, key=key, size_in_bytes=size, ref=ref)


# The stub implements paginated API snapshots and stateful deletion, including
# simulated API/CLI faults. Any unexpected command fails, including delete -y.
GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p = Path(os.environ['MOCK_STATE'])
s = json.loads(p.read_text())
a = sys.argv[1:]
s['calls'].append(a)
if a == ['api', '--paginate', '--slurp', 'repos/{owner}/{repo}/actions/caches?per_page=100']:
    s['reads'] += 1
    p.write_text(json.dumps(s))
    if s['reads'] in s.get('fail_reads', []): sys.exit(13)
    entries = s['entries']
    if s['reads'] == s.get('lose_read'):
        entries = [e for e in entries if e['id'] != s['lose_id']]
        s['entries'] = entries
        p.write_text(json.dumps(s))
    print(json.dumps([{'actions_caches': entries[n:n+2]} for n in range(0, len(entries), 2)] or [{'actions_caches': []}]))
elif len(a) == 3 and a[:2] == ['cache', 'delete'] and a[2].isdigit():
    if int(a[2]) == s.get('fail_delete'):
        p.write_text(json.dumps(s)); sys.exit(19)
    if not s.get('ignore_delete'):
        s['entries'] = [e for e in s['entries'] if e['id'] != int(a[2])]
    p.write_text(json.dumps(s))
else:
    p.write_text(json.dumps(s)); sys.exit(99)
'''


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        gh = self.base / 'gh'
        gh.write_text(GH)
        gh.chmod(0o755)
        self.state = self.base / 'state.json'
        self.out = self.base / 'output'
        self.archive = self.base / 'archive.tar.gz'
        self.env = dict(os.environ, PATH=str(self.base) + os.pathsep + os.environ['PATH'],
                        MOCK_STATE=str(self.state), GITHUB_OUTPUT=str(self.out), GITHUB_REF=REF)
        self.reset([])

    def reset(self, entries, **faults):
        self.state.write_text(json.dumps(dict(entries=entries, calls=[], reads=0, **faults)))

    def snapshot(self):
        return json.loads(self.state.read_text())

    def run_helper(self, *args):
        result = subprocess.run([sys.executable, str(HELPER), *args], env=self.env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def admit(self, size, prefix='cc-v3-ubi2.', key=None):
        if size is not None:
            with self.archive.open('wb') as f:
                f.truncate(size)  # sparse fixture, not multi-GB allocated data
        else:
            self.archive.unlink(missing_ok=True)
        self.log = self.run_helper('admit', prefix, str(self.archive), key or prefix + 'new')
        return self.out.read_text().splitlines()[-1] == 'save=true'

    def deletes(self):
        return [c for c in self.snapshot()['calls'] if c[:2] == ['cache', 'delete']]

    def test_missing_zero_oversize_and_ownership(self):
        for size in (None, 0, h.SLOTS['cc-v3-ubi2.'] + 1):
            with self.subTest(size=size):
                self.assertFalse(self.admit(size))
        self.assertFalse(self.admit(1, 'tc-v3-ubi2-', 'tc-v3-ubi2-oc-new'))
        self.assertFalse(self.admit(1, key='cc-v3-ubi2.'))
        self.assertEqual(self.snapshot()['calls'], [])

    def test_boundary_includes_margin_and_all_generations_refs(self):
        size = 1_000_000_000
        for group, prefix in [('standard', 'cc-v3-ubi2.'), ('oc', 'cc-v3-ubi2-oc.')]:
            used = h.BUDGETS[group] - size - h.HEADROOM
            for extra, expected in [(0, True), (1, False)]:
                self.reset([entry(1, prefix+'old', used//2),
                            entry(2, prefix+'older', used-used//2+extra, 'refs/heads/other')])
                self.assertEqual(self.admit(size, prefix), expected)
                self.assertFalse(self.deletes())

    def test_legacy_unknown_charged_to_each_group(self):
        for prefix in ('cc-v3-ubi2.', 'cc-v3-ubi2-oc.'):
            cap = h.BUDGETS[h.GROUPS[prefix]]
            self.reset([entry(1, 'legacy', cap-1-h.HEADROOM)])
            self.assertTrue(self.admit(1, prefix))
            self.reset([entry(1, 'legacy', cap-h.HEADROOM)])
            self.assertFalse(self.admit(1, prefix))

    def test_warm_inventory_and_cold_updates(self):
        # Explicit synthetic 4.5 GB warm inventory, representative not a live
        # measurement: 0.5 GB tc + 0.8 GB cc per target, 1.9 GB downloads.
        warm = [entry(1, 'tc-v3-ubi2-old', 500_000_000),
                entry(2, 'cc-v3-ubi2.old', 800_000_000),
                entry(3, 'tc-v3-ubi2-oc-old', 500_000_000),
                entry(4, 'cc-v3-ubi2-oc.old', 800_000_000),
                entry(5, 'dl-v3.old', 1_900_000_000)]
        self.assertEqual(sum(e['size_in_bytes'] for e in warm), 4_500_000_000)
        for entries in (warm, []):
            for prefix, size in h.SLOTS.items():
                with self.subTest(warm=bool(entries), prefix=prefix):
                    self.reset(entries)
                    self.assertTrue(self.admit(size, prefix), self.log)
        # Full cold sequential population at all archive caps, including each
        # wrapper allowance, fits independently (no pre-delete credit).
        entries = []
        for prefix, size in h.SLOTS.items():
            self.reset(entries)
            self.assertTrue(self.admit(size, prefix), self.log)
            entries.append(entry(len(entries)+1, prefix+'new', size+h.HEADROOM))
        self.assertLessEqual(sum(e['size_in_bytes'] for e in entries), 10_000_000_000)

    def test_parallel_groups_cannot_spend_peer_headroom(self):
        # Both admit from the SAME snapshot at their exact respective caps.
        size = 1_000_000_000
        entries = [entry(1, 'cc-v3-ubi2.old', 6_000_000_000-size-h.HEADROOM),
                   entry(2, 'cc-v3-ubi2-oc.old', 4_000_000_000-size-h.HEADROOM)]
        for prefix in ('cc-v3-ubi2.', 'cc-v3-ubi2-oc.'):
            self.reset(entries)
            self.assertTrue(self.admit(size, prefix))
            self.assertFalse(self.admit(size+1, prefix))
        self.assertEqual(sum(e['size_in_bytes'] for e in entries)+2*(size+h.HEADROOM), 10_000_000_000)
        self.reset([entry(1, 'cc-v3-ubi2.old', 6_000_000_000)])
        self.assertFalse(self.admit(1))  # total repository still has 4 GB free

    def test_paginated_inventory_and_admission_read_failure(self):
        self.reset([entry(i, 'legacy'+str(i), 2_000_000_000) for i in range(1, 4)])
        self.assertFalse(self.admit(1))  # third entry on page two matters
        self.reset([], fail_reads=[1])
        self.assertFalse(self.admit(1))
        self.assertIn('::warning::', self.log)
        self.assertFalse(self.deletes())

    def caches(self):
        return [entry(1, 'tc-v3-ubi2-new'), entry(2, 'tc-v3-ubi2-old'),
                entry(3, 'tc-v3-ubi2-oc-peer'), entry(4, 'cc-v3-ubi2.peer'),
                entry(5, 'tc-v3-ubi2-older'), entry(6, 'legacy'),
                entry(7, 'tc-v3-ubi2-other', ref='refs/heads/other'),
                entry(8, 'dl-v3.peer')]

    def cleanup(self, key='tc-v3-ubi2-new', prefix='tc-v3-ubi2-'):
        return self.run_helper('cleanup', prefix, key)

    def test_cleanup_success_pagination_and_peer_isolation(self):
        self.reset(self.caches())
        self.assertIn('cleanup verified', self.cleanup())
        self.assertEqual(self.deletes(), [['cache', 'delete', '2'], ['cache', 'delete', '5']])
        self.assertEqual({e['id'] for e in self.snapshot()['entries']}, {1, 3, 4, 6, 7, 8})
        self.assertEqual(self.snapshot()['reads'], 2)
        self.reset(self.caches())
        self.assertIn('cleanup verified', self.cleanup('tc-v3-ubi2-oc-peer', 'tc-v3-ubi2-oc-'))
        self.assertFalse(self.deletes())

    def test_missing_zero_wrong_ref_or_owner_new_key_never_deletes(self):
        for mode in ('missing', 'zero', 'wrong_ref', 'wrong_owner', 'bad_ref'):
            entries = self.caches()
            if mode == 'missing': entries = entries[1:]
            if mode == 'zero': entries[0]['size_in_bytes'] = 0
            if mode == 'wrong_ref': entries[0]['ref'] = 'refs/heads/other'
            self.env['GITHUB_REF'] = 'refs/pull/1/merge' if mode == 'bad_ref' else REF
            self.reset(entries)
            log = self.cleanup('tc-v3-ubi2-oc-peer' if mode == 'wrong_owner' else 'tc-v3-ubi2-new')
            self.assertIn('::warning::', log)
            self.assertFalse(self.deletes())
            self.assertEqual(self.snapshot()['entries'], entries)

    def test_pre_delete_readback_failure_preserves_old(self):
        self.reset(self.caches(), fail_reads=[1])
        log = self.cleanup()
        self.assertIn('retaining old caches', log)
        self.assertFalse(self.deletes())
        self.assertEqual(self.snapshot()['entries'], self.caches())

    def test_peer_cleanup_during_readback_is_allowed(self):
        self.reset(self.caches(), lose_read=2, lose_id=3)
        log = self.cleanup()
        self.assertIn('cleanup verified', log)
        self.assertNotIn('::warning::', log)
        self.assertEqual(self.deletes(), [['cache', 'delete', '2'], ['cache', 'delete', '5']])
        self.assertEqual({e['id'] for e in self.snapshot()['entries']}, {1, 4, 6, 7, 8})

    def test_post_delete_readback_and_delete_failures_warn_honestly(self):
        for fault in ({'fail_reads': [2]}, {'fail_delete': 2},
                      {'ignore_delete': True}, {'lose_read': 2, 'lose_id': 7},
                      {'lose_read': 2, 'lose_id': 1}):
            self.reset(self.caches(), **fault)
            log = self.cleanup()
            self.assertIn('::warning::', log)
            self.assertNotIn('cleanup verified', log)
            if fault.get('lose_id') != 1:
                self.assertIn(1, [e['id'] for e in self.snapshot()['entries']])
            if fault == {'fail_reads': [2]}:
                self.assertIn('already deleted IDs=[2, 5]', log)
            if fault == {'fail_delete': 2}:
                self.assertEqual(self.snapshot()['entries'], self.caches())

    def test_invalid_inventory_fails_closed(self):
        for entries in ([entry(1, 'legacy', -1)], [entry(1, 'legacy', '100')],
                        [entry(1, 'legacy'), entry(1, 'duplicate')]):
            self.reset(entries)
            self.assertFalse(self.admit(1))
            self.assertIn('::warning::', self.cleanup())
            self.assertFalse(self.deletes())


if __name__ == '__main__':
    unittest.main()
