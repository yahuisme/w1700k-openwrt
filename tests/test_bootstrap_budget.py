#!/usr/bin/env python3
"""Bootstrap quota/retention regressions; sparse archives and isolated gh only."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_cache_helper as safety

h = safety.h
TB = 'tb-v1-ubi2-'
TC, CC, DL = safety.TC, safety.CC, safety.DL
REF = safety.REF
entry = safety.entry


class BootstrapBudgetTests(unittest.TestCase):
    # Reuse the established isolated, paginated gh fixture, not live GitHub.
    setUp = safety.HelperTests.setUp
    reset = safety.HelperTests.reset
    snapshot = safety.HelperTests.snapshot
    run_helper = safety.HelperTests.run_helper
    admit = safety.HelperTests.admit
    deletes = safety.HelperTests.deletes

    env: dict
    log: str

    def cleanup(self, key=TB + 'new', prefix=TB):
        with patch.dict(os.environ, self.env), patch.object(h.time, 'sleep'):
            return h.cleanup(prefix, key)

    def test_bootstrap_admit_then_verified_save_prunes_only_own_branch(self):
        self.assertEqual(h.owner(TB + 'new'), TB)
        self.assertEqual(h.SLOTS[TB], 1_000_000_000)
        inventory = [entry(1, TB + 'old', 1_000_000_000),
                     entry(2, TC + 'old'), entry(3, CC + 'old'), entry(4, DL + 'old'),
                     entry(5, TB + 'other', ref='refs/heads/other'),
                     entry(6, 'tc-v3-ubi2-oc-retired'), entry(7, 'unowned')]
        self.reset(inventory)
        self.assertTrue(self.admit(1_000_000_000, TB), self.log)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.snapshot()['entries'], inventory)
        # Upload visibility is simulated only after admission; cleanup uses the
        # real helper's API readback and the fixture's stateful delete command.
        new = entry(8, TB + 'new', 1_000_000_000 + h.HEADROOM)
        self.reset(inventory + [new])
        self.assertTrue(self.cleanup())
        self.assertEqual(self.deletes(), [['cache', 'delete', '1']])
        self.assertEqual(self.snapshot()['entries'], inventory[1:] + [new])
        self.assertEqual(self.snapshot()['reads'], 2)

    def test_bootstrap_invalid_size_and_key_fail_without_inventory_or_delete(self):
        for size in (None, 0, 1_000_000_001):
            with self.subTest(size=size):
                self.reset([])
                self.assertFalse(self.admit(size, TB), self.log)
                self.assertEqual(self.snapshot()['calls'], [])
        for prefix, key in ((TB, TB), (TB, TC + 'new'),
                            (TC, TB + 'new'), ('tb-v1-ubi2', TB + 'new')):
            with self.subTest(prefix=prefix, key=key):
                self.reset([])
                self.assertFalse(self.admit(1, prefix, key), self.log)
                self.assertEqual(self.snapshot()['calls'], [])

    def test_missing_empty_wrong_ref_upload_never_prunes_old_seed(self):
        old = entry(1, TB + 'old', 1_000_000_000)
        peer = entry(2, DL + 'old', 4_000_000_000)
        for pending in ([], [entry(3, TB + 'new', 0)],
                        [entry(3, TB + 'new', 100, 'refs/heads/other')]):
            with self.subTest(pending=pending):
                inventory = [old, peer] + pending
                self.reset(inventory)
                self.assertFalse(self.cleanup())
                self.assertEqual(self.deletes(), [])
                self.assertEqual(self.snapshot()['entries'], inventory)
                self.assertEqual(self.snapshot()['reads'], 3)

    def test_bootstrap_api_failure_preserves_old_and_other_namespaces(self):
        old = entry(1, TB + 'old', 1_000_000_000)
        peer = entry(2, DL + 'old', 4_000_000_000)
        inventory = [old, peer]
        self.reset(inventory, fail_reads=[1])
        self.assertFalse(self.admit(1_000_000_000, TB), self.log)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.snapshot()['entries'], inventory)
        for inventory, faults in (([old, peer], {'fail_reads': [1]}),
                                  ([old, peer], {'fail_reads': [2]}),
                                  ([old, peer, entry(3, TB + 'new')], {'fail_delete': 1})):
            with self.subTest(faults=faults):
                self.reset(inventory, **faults)
                self.assertFalse(self.cleanup())
                self.assertEqual(self.snapshot()['entries'], inventory)
                self.assertFalse(any(c[2] == '2' for c in self.deletes()))

    def test_bootstrap_readback_failure_is_reported_not_claimed_success(self):
        inventory = [entry(1, TB + 'old'), entry(2, TB + 'new'), entry(3, DL + 'old')]
        self.reset(inventory, fail_reads=[2])
        self.assertFalse(self.cleanup())
        self.assertEqual(self.deletes(), [['cache', 'delete', '1']])
        self.assertEqual(self.snapshot()['entries'], inventory[1:])

    def test_bootstrap_budget_exact_boundary_counts_every_ref_and_legacy(self):
        for extra, accepted in ((0, True), (1, False)):
            inventory = [entry(1, TB + 'old', 1_000_000_000),
                         entry(2, TB + 'branch', 1_000_000_000, 'refs/heads/other'),
                         entry(3, 'retired-or-unknown',
                               h.BUDGET - 3_000_000_000 - h.HEADROOM + extra)]
            self.reset(inventory)
            self.assertEqual(self.admit(1_000_000_000, TB), accepted, self.log)
            self.assertEqual(self.deletes(), [])
            self.assertEqual(self.snapshot()['entries'], inventory)

    def test_measured_snapshots_bootstrap_first_generation_and_replacement(self):
        fixture = json.loads((safety.ROOT / 'tests/fixtures/download-cache-inventory.json').read_text())
        self.assertEqual(h.PROFILE['cache_prefix'], {'tc': TC, 'cc': CC, 'dl': DL})
        self.assertEqual(h.SLOTS, {TC: 2_000_000_000, CC: 3_000_000_000,
                                   DL: 4_000_000_000, TB: 1_000_000_000})
        self.assertEqual(h.BUDGET, 10_000_000_000)
        self.assertEqual(h.HEADROOM, 64 * 1024 * 1024)
        self.assertIsNone(h.owner('tc-v3-ubi2-oc-retired'))
        for distro, pages in fixture['snapshots'].items():
            inventory = [dict(e) for page in pages for e in page['actions_caches']]
            self.assertEqual(len(inventory), pages[0]['total_count'])
            for old_bootstrap in (False, True):
                with self.subTest(distro=distro, old_bootstrap=old_bootstrap):
                    entries = inventory + ([entry(1, TB + 'old', 1_000_000_000 + h.HEADROOM)]
                                           if old_bootstrap else [])
                    for prefix, size in ((TB, 1_000_000_000), (DL, 4_000_000_000)):
                        self.reset(entries)
                        self.assertTrue(self.admit(size, prefix), self.log)
                        self.assertEqual(self.deletes(), [])
                        self.assertEqual(self.snapshot()['entries'], entries)
            # Measured tc/cc plus a capped old download and bootstrap: the
            # next capped download no longer fits, even though its tier cap does.
            entries = [dict(e, size_in_bytes=4_000_000_000 + h.HEADROOM)
                       if h.owner(e['key']) == DL else dict(e) for e in inventory]
            entries.append(entry(1, TB + 'old', 1_000_000_000 + h.HEADROOM))
            self.reset(entries)
            self.assertFalse(self.admit(4_000_000_000, DL), self.log)
            self.assertEqual(self.deletes(), [])
            self.assertEqual(self.snapshot()['entries'], entries)

    def test_recent_inventory_conservative_envelope_does_not_promise_dl_rollover(self):
        # Synthetic conservative envelope for the parent's recent ~5.75/5.71 GB
        # observations, NOT an invented API snapshot. Exact historic snapshots
        # are exercised separately above. Every old wrapper is charged in full.
        base = [entry(1, TC + 'old', 1_570_000_000),
                entry(2, CC + 'old', 1_120_000_000),
                entry(3, DL + 'old', 3_074_000_000)]
        for prefix, size, accepted in ((TB, 1_000_000_000, True),
                                       (TC, 2_000_000_000, True),
                                       (CC, 3_000_000_000, True),
                                       (DL, 4_000_000_000, False)):
            inventory = base + [entry(4, TB + 'old', 1_000_000_000 + h.HEADROOM)]
            with self.subTest(prefix=prefix):
                self.reset(inventory)
                self.assertEqual(self.admit(size, prefix), accepted, self.log)
                self.assertEqual(self.deletes(), [])
                self.assertEqual(self.snapshot()['entries'], inventory)

    def test_maximal_population_bootstrap_and_replacements_decline(self):
        # Three capped old tiers already leave too little space for bootstrap.
        # This ordinary admission path never borrows download pre-delete credit.
        base = [entry(i, prefix + 'old', size + h.HEADROOM)
                for i, (prefix, size) in enumerate(((TC, 2_000_000_000),
                                                   (CC, 3_000_000_000),
                                                   (DL, 4_000_000_000)), 1)]
        self.reset(base)
        self.assertFalse(self.admit(1_000_000_000, TB), self.log)
        self.assertEqual(self.deletes(), [])
        inventory = base + [entry(4, TB + 'old', 1_000_000_000 + h.HEADROOM)]
        self.assertGreater(sum(int(e['size_in_bytes']) for e in inventory), h.BUDGET)
        for prefix, size in h.SLOTS.items():
            with self.subTest(prefix=prefix):
                self.reset(inventory)
                self.assertFalse(self.admit(size, prefix), self.log)
                self.assertIn('repository budget exceeded', self.log)
                self.assertEqual(self.deletes(), [])
                self.assertEqual(self.snapshot()['entries'], inventory)


if __name__ == '__main__':
    unittest.main()
