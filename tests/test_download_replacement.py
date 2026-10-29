"""Authorized download replacement; sparse candidates and private gh only."""
import json
from pathlib import Path
import unittest

import test_cache_helper as safety
from test_cache_workflow import step

h, entry = safety.h, safety.entry
DL, TC, CC = safety.DL, safety.TC, safety.CC
TB = 'tb-v1-ubi2-'


class DownloadReplacementTests(unittest.TestCase):
    archive: Path
    base: Path
    out: Path
    setUp = safety.HelperTests.setUp
    reset = safety.HelperTests.reset
    snapshot = safety.HelperTests.snapshot
    run_helper = safety.HelperTests.run_helper
    deletes = safety.HelperTests.deletes

    def admit(self, size, prefix=DL, key=None):
        if size is not None:
            with self.archive.open('wb') as out:
                out.truncate(size)
        else:
            self.archive.unlink(missing_ok=True)
        self.log = self.run_helper('admit', prefix, str(self.archive), key or prefix + 'new',
                                   '--replace-download')
        return self.out.read_text().splitlines()[-1] == 'save=true'

    def test_measured_first_and_steady_replacements_preserve_other_tiers(self):
        # Read-only API inventory and actual inner gzip sizes from the reviewed runs.
        for tc, cc, tb, old, candidate in (
                (1_566_769_350, 1_087_484_641, 216_877_128, 3_074_984_344, 3_748_957_315),
                (1_566_850_926, 1_079_492_879, 216_817_510, 3_062_899_975, 3_738_752_266)):
            for steady in (False, True):
                with self.subTest(tc=tc, steady=steady):
                    protected = [entry(1, TC+'seed', tc), entry(2, CC+'seed', cc),
                                 entry(3, TB+'seed', tb)]
                    download = entry(4, DL+'old', candidate + h.HEADROOM if steady else old)
                    self.reset(protected + [download])
                    self.assertTrue(self.admit(candidate), self.log)
                    self.assertEqual(self.deletes(), [['cache', 'delete', '4']] if steady else [])
                    self.assertEqual(self.snapshot()['entries'], protected if steady else protected + [download])
                    self.assertEqual(self.snapshot()['reads'], 2 if steady else 1)

    def test_only_minimum_same_branch_download_ids_are_deleted(self):
        protected = [entry(1, TC+'seed', 2_000_000_000), entry(2, CC+'seed', 2_000_000_000),
                     entry(3, TB+'seed', 100_000_000), entry(4, DL+'peer', 100_000_000,
                                                        'refs/heads/other'),
                     entry(5, 'dl-legacy.seed', 200_000_000)]
        old = [entry(6, DL+'older', 1_500_000_000), entry(7, DL+'old', 1_500_000_000)]
        self.reset(protected + old)
        self.assertTrue(self.admit(4_000_000_000), self.log)
        self.assertEqual(self.deletes(), [['cache', 'delete', '6']])
        self.assertEqual(self.snapshot()['entries'], protected + old[1:])

    def test_largest_first_avoids_deleting_extra_seeds_or_empty_entries(self):
        protected = [entry(1, TC+'seed', 3_000_000_000),
                     entry(2, CC+'seed', 2_000_000_000)]
        old = [entry(3, DL+'empty', 0), entry(4, DL+'small', 100_000_000),
               entry(5, DL+'large', 2_000_000_000)]
        self.reset(protected + old)
        self.assertTrue(self.admit(4_000_000_000), self.log)
        self.assertEqual(self.deletes(), [['cache', 'delete', '5']])
        self.assertEqual(self.snapshot()['entries'], protected + old[:2])

    def test_does_not_delete_when_all_eligible_seeds_cannot_make_room(self):
        entries = [entry(1, TC+'seed', 5_000_000_000),
                   entry(2, CC+'seed', 2_000_000_000), entry(3, DL+'old', 1_000_000_000)]
        self.reset(entries)
        self.assertFalse(self.admit(4_000_000_000), self.log)
        self.assertEqual(self.deletes(), [])
        self.assertEqual(self.snapshot()['entries'], entries)
        self.assertIn('cannot fit', self.log)

    def test_missing_empty_oversized_linked_or_wrong_tier_never_deletes(self):
        entries = [entry(1, DL+'old', 4_000_000_000), entry(2, TC+'seed', 3_000_000_000)]
        for size, prefix in ((None, DL), (0, DL), (4_000_000_001, DL), (1, TC), (1, CC), (1, TB)):
            with self.subTest(size=size, prefix=prefix):
                self.reset(entries)
                self.assertFalse(self.admit(size, prefix), self.log)
                self.assertEqual(self.snapshot()['calls'], [])
        self.archive.unlink()
        target = self.base / 'target'
        target.write_bytes(b'download')
        self.archive.symlink_to(target)
        self.reset(entries)
        self.log = self.run_helper('admit', DL, str(self.archive), DL+'new', '--replace-download')
        self.assertIn('save=false', self.out.read_text())
        self.assertEqual(self.snapshot()['calls'], [])

    def test_existing_candidate_key_never_deletes_a_seed(self):
        entries = [entry(1, DL+'new', 100), entry(2, DL+'old', 4_000_000_000),
                   entry(3, TC+'seed', 3_000_000_000)]
        self.reset(entries)
        self.assertFalse(self.admit(4_000_000_000), self.log)
        self.assertIn('already exists', self.log)
        self.assertEqual(self.deletes(), [])

    def test_inventory_failure_or_malformed_pages_never_deletes(self):
        entries = [entry(1, DL+'old', 4_000_000_000), entry(2, TC+'seed', 3_000_000_000)]
        for faults in ({'fail_reads': [1]}, {'raw_pages': []},
                       {'raw_pages': [{'total_count': 3, 'actions_caches': entries}]}):
            with self.subTest(faults=faults):
                self.reset(entries, **faults)
                self.assertFalse(self.admit(4_000_000_000), self.log)
                self.assertEqual(self.deletes(), [])

    def test_delete_failure_and_readback_faults_deny_upload(self):
        entries = [entry(1, DL+'old', 4_000_000_000), entry(2, TC+'seed', 3_000_000_000)]
        for faults in ({'fail_delete': 1}, {'ignore_delete': True}, {'fail_reads': [2]},
                       {'lose_read': 2, 'lose_id': 2}):
            with self.subTest(faults=faults):
                self.reset(entries, **faults)
                self.assertFalse(self.admit(4_000_000_000), self.log)
                self.assertEqual(self.deletes(), [['cache', 'delete', '1']])
                self.assertNotIn(['cache', 'delete', '2'], self.snapshot()['calls'])

    def test_no_seed_is_deleted_for_cold_or_fitting_cache(self):
        for entries in ([], [entry(1, DL+'old', 1_000_000_000)]):
            self.reset(entries)
            self.assertTrue(self.admit(4_000_000_000), self.log)
            self.assertEqual(self.deletes(), [])
            self.assertEqual(self.snapshot()['entries'], entries)

    def test_replacement_exact_budget_and_growth_readback_fail_closed(self):
        size = 4_000_000_000
        reserve = size + h.HEADROOM
        for extra, accepted in ((0, True), (1, False)):
            self.reset([entry(1, TC+'seed', h.BUDGET-reserve+extra),
                        entry(2, DL+'old', 1_000_000_000)])
            self.assertEqual(self.admit(size), accepted, self.log)
            self.assertEqual(self.deletes(), [['cache', 'delete', '2']] if accepted else [])
        from unittest.mock import patch
        before = [entry(1, TC+'seed', 3_000_000_000), entry(2, DL+'old', 4_000_000_000)]
        after = [before[0], entry(3, 'unknown-new', 4_000_000_000)]
        with patch.object(h, 'inv', return_value=after), patch.object(h.subprocess, 'run') as delete:
            with self.assertRaisesRegex(ValueError, 'budget changed'):
                h.replace_download(before, DL, DL+'new', safety.REF, reserve)
            delete.assert_called_once_with(['gh', 'cache', 'delete', '2'], check=True)

    def test_production_download_step_opts_in_without_changing_other_tiers(self):
        self.assertEqual(step('Check download cache budget')['run'].strip(),
                         "python3 scripts/cache_helper.py admit 'dl-v3.' dlarchive/dl.tar.gz "
                         "'${{ steps.dl.outputs.cache-primary-key }}' --replace-download")
        for name in ('Prepare build caches', 'Check toolchain cache budget', 'Check bootstrap cache budget'):
            self.assertNotIn('--replace-download', step(name)['run'])
        self.assertEqual(step('Check download cache budget')['if'], "steps.dl_changed.outputs.save == 'true'")


if __name__ == '__main__':
    unittest.main()
