#!/usr/bin/env python3
"""Deletion readback retries use isolated API replies, never live caches."""
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from test_cache_helper import REF, TC, entry, h


def pages(entries, total=None):
    return json.dumps([{'total_count': len(entries) if total is None else total,
                        'actions_caches': entries}])


class ReadbackTests(unittest.TestCase):
    def replay(self, replies, expected, delays, before=None):
        new, old = entry(1, TC + 'new'), entry(2, TC + 'old')
        peer = entry(3, 'unrelated')
        with patch.dict(os.environ, GITHUB_REF=REF), \
                patch.object(h.subprocess, 'check_output',
                             side_effect=[pages([new, old, peer] if before is None else before),
                                          *replies]) as api, \
                patch.object(h.subprocess, 'run') as delete, \
                patch.object(h.time, 'sleep') as sleep, \
                contextlib.redirect_stdout(io.StringIO()) as log:
            self.assertEqual(h.cleanup(TC, TC + 'new'), expected)
        delete.assert_called_once_with(['gh', 'cache', 'delete', '2'], check=True)
        self.assertEqual(api.call_count, 1 + len(replies))
        self.assertEqual([c.args[0] for c in sleep.call_args_list], delays)
        self.assertEqual('cleanup verified:' in log.getvalue(), expected)
        if not expected:
            self.assertIn('already deleted IDs=[2]', log.getvalue())
        return log.getvalue()

    def test_incomplete_post_delete_inventory_recovers_without_redeleting(self):
        after = [entry(1, TC + 'new'), entry(3, 'unrelated')]
        self.replay([pages(after, total=3), pages(after)], True, [2])

    def test_two_inconsistent_snapshots_recover_on_final_attempt(self):
        after = [entry(1, TC + 'new'), entry(3, 'unrelated')]
        changed = json.dumps([
            {'total_count': 3, 'actions_caches': after[:1]},
            {'total_count': 2, 'actions_caches': after[1:]},
        ])
        self.replay([changed, pages(after, total=3), pages(after)], True, [2, 4])

    def test_persistent_incomplete_inventory_fails_closed(self):
        bad = pages([entry(1, TC + 'new')], total=2)
        self.assertIn('incomplete cache inventory',
                      self.replay([bad] * 3, False, [2, 4]))

    def test_normal_readback_has_no_retry_delay(self):
        self.replay([pages([entry(1, TC + 'new'), entry(3, 'unrelated')])], True, [])

    def test_invalid_schema_is_not_retried(self):
        self.replay([pages([entry(1, TC + 'new')], total='1')], False, [])

    def test_api_error_is_not_hidden(self):
        self.replay([OSError('API unavailable')], False, [])

    def test_retry_does_not_weaken_saved_key_or_deletion_checks(self):
        for after in ([], [entry(1, TC + 'new', size=0)],
                      [entry(1, TC + 'new', ref='refs/heads/other')],
                      [entry(1, TC + 'new'), entry(2, TC + 'old')]):
            with self.subTest(after=after):
                self.replay([pages([], total=1), pages(after)], False, [2])

    def test_download_predelete_readback_retries_without_redeleting(self):
        from test_cache_helper import DL
        before = [entry(1, TC + 'seed', 3_000_000_000),
                  entry(2, DL + 'old', 4_000_000_000)]
        after = before[:1]
        for persistent in (False, True):
            replies = [pages(after, total=2)] * (3 if persistent else 2)
            if not persistent:
                replies.append(pages(after))
            with self.subTest(persistent=persistent), \
                    patch.object(h.subprocess, 'check_output', side_effect=replies) as api, \
                    patch.object(h.subprocess, 'run') as delete, \
                    patch.object(h.time, 'sleep') as sleep, \
                    contextlib.redirect_stdout(io.StringIO()):
                if persistent:
                    with self.assertRaisesRegex(ValueError, 'incomplete cache inventory'):
                        h.replace_download(before, DL, DL + 'new', REF, 4_100_000_000)
                else:
                    self.assertEqual(h.replace_download(
                        before, DL, DL + 'new', REF, 4_100_000_000), after)
                delete.assert_called_once_with(['gh', 'cache', 'delete', '2'], check=True)
                self.assertEqual(api.call_count, 3)
                self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_download_retry_still_rejects_unsafe_or_invalid_readback(self):
        from test_cache_helper import DL
        before = [entry(1, TC + 'seed', 3_000_000_000),
                  entry(2, DL + 'old', 4_000_000_000)]
        protected = before[:1]
        cases = {
            'protected_missing': pages([]),
            'old_remains': pages(before),
            'budget_growth': pages(protected + [entry(3, 'unknown', 4_000_000_000)]),
            'malformed': pages([dict(before[0], size_in_bytes='100')]),
            'duplicate': pages(protected * 2),
            'cli_error': h.subprocess.CalledProcessError(13, ['gh', 'api']),
        }
        for label, final in cases.items():
            with self.subTest(case=label), \
                    patch.object(h.subprocess, 'check_output',
                                 side_effect=[pages([], total=1), final]) as api, \
                    patch.object(h.subprocess, 'run') as delete, \
                    patch.object(h.time, 'sleep') as sleep:
                with self.assertRaises((ValueError, h.subprocess.SubprocessError)):
                    h.replace_download(before, DL, DL + 'new', REF, 4_100_000_000)
                delete.assert_called_once_with(['gh', 'cache', 'delete', '2'], check=True)
                self.assertEqual(api.call_count, 2)
                self.assertEqual([c.args[0] for c in sleep.call_args_list], [2])

    def test_retry_preserves_protected_ids_and_other_branch(self):
        new = entry(1, TC + 'new')
        protected = entry(4, TC + 'new')
        other = entry(5, TC + 'other', ref='refs/heads/other')
        before = [new, entry(2, TC + 'old'), protected, other]
        for missing in (None, 4, 5):
            after = [e for e in (new, protected, other) if e['id'] != missing]
            with self.subTest(missing=missing):
                log = self.replay([pages([], total=1), pages(after)], missing is None,
                                  [2], before=before)
                if missing is not None:
                    self.assertIn('retention readback failed', log)

    def test_hard_failure_after_inconsistent_read_stops_immediately(self):
        new = entry(1, TC + 'new')
        faults = {
            'malformed_entry': pages([dict(new, size_in_bytes='100')]),
            'missing_field': pages([{'id': 1}]),
            'duplicate_id': pages([new, new]),
            'invalid_json': '{',
            'cli_error': h.subprocess.CalledProcessError(13, ['gh', 'api']),
        }
        for label, fault in faults.items():
            with self.subTest(fault=label):
                self.replay([pages([], total=1), fault], False, [2])

    def test_incomplete_preflight_never_retries_or_deletes(self):
        with patch.dict(os.environ, GITHUB_REF=REF), \
                patch.object(h.subprocess, 'check_output',
                             return_value=pages([], total=1)) as api, \
                patch.object(h.subprocess, 'run') as delete, \
                patch.object(h.time, 'sleep') as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(h.cleanup(TC, TC + 'new'))
        api.assert_called_once()
        delete.assert_not_called()
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
