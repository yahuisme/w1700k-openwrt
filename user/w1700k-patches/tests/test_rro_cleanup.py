"""RRO raw-buffer ownership SOURCE CONTRACTS, not executed kernel C.

The immutable function is from openwrt/mt76 commit
0936617dc529ff9da0385221d3fa6de732231177, mt7996/mac.c SHA256
 afbb328d9711a5eb335c3f36230b25cbe26fb66154fe9738b157ccff23e9899f.
The fixture preserves that entire function plus one final newline; original
license: BSD-3-Clause-Clear, Copyright (C) 2022 MediaTek Inc.
No compilation, allocation-fault injection, DMA, pagepool or device execution.
"""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'tree/package/kernel/mt76/patches/914-mt76-mt7996-free-rro-drop-buffers.patch'
FIXTURE = Path(__file__).parent / 'fixtures/mt76-rro/mt7996-rro-rx-process.c.fixture'
FIXTURE_SHA256 = '5ab1b08e4f3b70da8d0a4c0ae92cfb33a69d6b5549df2de07ae0bf4cb5b78266'
CHECK = 'if (ls && !mt7996_rx_check(mdev, buf, len))'
FREE = 'mt76_put_page_pool_buf(buf, false);'
# Each is an exact, unique allowed delta in the original function. Never update
# the immutable fixture to repaired bytes or normalize unrelated source changes.
DROP_DELTAS = tuple(
    ('\t\t\t' + condition + '\n\t\t\t\tgoto next_page;\n',
     '\t\t\t' + condition + ' {\n\t\t\t\t' + FREE +
     '\n\t\t\t\tgoto next_page;\n\t\t\t}\n')
    for condition in (CHECK, 'if (!skb)')
)


class RroCleanupSourceContracts(unittest.TestCase):
    def original(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FIXTURE_SHA256)
        return raw.decode()

    def patched(self):
        original = self.original()
        # Missing overlay means the unmodified source, so the initial RED fails
        # on the ownership assertion rather than FileNotFoundError. A separate
        # required-payload contract below rejects removal of the final overlay.
        if not PATCH.is_file():
            return original
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'mt7996/mac.c'
            target.parent.mkdir()
            target.write_text(original)
            result = subprocess.run(
                ['patch', '-p1', '--batch', '--forward', '--fuzz=0',
                 '--no-backup-if-mismatch', '-i', str(PATCH)],
                cwd=tmp, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('fuzz', result.stdout.lower())
            self.assertFalse(list(Path(tmp).rglob('*.rej')))
            self.assertFalse(list(Path(tmp).rglob('*.orig')))
            return target.read_text()

    def assert_released_on_failure(self, source, condition):
        self.assertIn(condition + ' {\n\t\t\t\t' + FREE +
                      '\n\t\t\t\tgoto next_page;\n\t\t\t}', source)

    def test_rx_check_rejection_returns_raw_buffer_before_next_page(self):
        self.assert_released_on_failure(self.patched(), CHECK)

    def test_build_skb_failure_returns_raw_buffer_before_next_page(self):
        self.assert_released_on_failure(self.patched(), 'if (!skb)')

    def assert_only_drop_deltas(self, source):
        for old, new in reversed(DROP_DELTAS):
            self.assertEqual(source.count(new), 1, 'missing/non-unique drop delta')
            source = source.replace(new, old, 1)
        self.assertEqual(source, self.original(), 'unrelated RRO source changed')

    def test_entire_function_normalizes_only_two_explicit_drop_deltas(self):
        self.assert_only_drop_deltas(self.patched())

    def test_required_production_patch_is_nonempty_and_targets_only_mac(self):
        self.assertTrue(PATCH.is_file())
        payload = PATCH.read_text()
        self.assertTrue(payload.strip())
        self.assertEqual([line for line in payload.splitlines()
                          if line.startswith(('--- ', '+++ '))],
                         ['--- a/mt7996/mac.c', '+++ b/mt7996/mac.c'])

    def test_normalization_rejects_missing_or_duplicate_allowed_deltas(self):
        source = self.patched()
        for old, new in DROP_DELTAS:
            for label, mutant in (('missing', source.replace(new, old, 1)),
                                  ('duplicate', source.replace(new, new + new, 1))):
                with self.subTest(delta=old, mutation=label):
                    with self.assertRaises(AssertionError):
                        self.assert_only_drop_deltas(mutant)

    def test_early_session_signature_and_missing_page_gates_remain_exact(self):
        source = self.patched()
        marker = '\t\t\tqid = t->qid;'
        old = self.original()
        self.assertEqual(source[:source.index(marker)], old[:old.index(marker)])
        self.assertIn('if (seq_id > MT7996_RRO_MAX_SESSION)\n\t\treturn;', source)
        self.assertIn('goto update_ack_seq_num;', source)
        self.assertIn('if (!p)\n\t\t\t\t\tcontinue;', source)

    def test_no_owner_and_metadata_handoff_paths_do_not_free_stale_buf(self):
        source = self.patched()
        self.assertIn('if (!t)\n\t\t\t\tgoto next_page;', source)
        self.assertIn('if (!buf)\n\t\t\t\tgoto next_page;', source)
        statements = ('t = mt76_rx_token_release(mdev, rx_token_id);',
                      'buf = t->ptr;',
                      'dma_sync_single_for_cpu(mdev->dma_dev, t->dma_addr,',
                      't->dma_addr = 0;', 't->ptr = NULL;',
                      'mt76_put_rxwi(mdev, t);', 'if (!buf)', CHECK,
                      'skb = build_skb(buf, q->buf_size);')
        positions = [source.index(statement) for statement in statements]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(FREE, source[:source.index('if (!buf)')])
        self.assertEqual(source.count('mt76_rx_token_release('), 1)
        self.assertEqual(source.count('mt76_put_rxwi('), 1)
        # This also locks every untouched DMA/token/early-return byte.
        self.assert_only_drop_deltas(source)

    def test_existing_oversize_and_pending_fragment_drop_paths_remain_exact(self):
        source = self.patched()
        old = self.original()
        for begin, end in (('if (data_len < len + q->buf_offset)',
                            'ls = FIELD_GET(RRO_HIF_DATA1_LS_MASK,'),
                           ('ls = FIELD_GET(RRO_HIF_DATA1_LS_MASK,', CHECK)):
            with self.subTest(branch=begin):
                branch = source[source.index(begin):source.index(end)]
                self.assertEqual(branch, old[old.index(begin):old.index(end)])
                self.assertEqual(branch.count(FREE), 1)
                self.assertIn('dev_kfree_skb(q->rx_head);', branch)
                self.assertIn('q->rx_head = NULL;', branch)
                self.assertEqual(branch.count('goto next_page;'), 1)

    def test_successful_skb_owns_buffer_in_reason_drop_pending_and_delivery(self):
        source = self.patched()
        old = self.original()
        marker = 'skb_reserve(skb, q->buf_offset);'
        success = source[source.index(marker):source.index('next_page:')]
        self.assertEqual(success, old[old.index(marker):old.index('next_page:')])
        self.assertIn('skb_mark_for_recycle(skb);', success)
        self.assertIn('if (ind_reason == 1 || ind_reason == 2) {\n'
                      '\t\t\t\tdev_kfree_skb(skb);\n'
                      '\t\t\t\tgoto next_page;\n\t\t\t}', success)
        self.assertIn('if (!ls) {\n\t\t\t\tq->rx_head = skb;\n'
                      '\t\t\t\tgoto next_page;\n\t\t\t}', success)
        self.assertIn('mt7996_queue_rx_skb(mdev, qid, skb, &info);', success)
        self.assertNotIn('mt76_put_page_pool_buf(', success)

    def test_next_page_recycles_only_separate_msdu_page_not_packet_buffer(self):
        source = self.patched()
        old = self.original()
        tail = source[source.index('next_page:'):]
        self.assertEqual(tail, old[old.index('next_page:'):])
        self.assertIn('mt7996_msdu_page_put_to_cache(dev, p);', tail)
        for forbidden in ('mt76_put_page_pool_buf(', 'dev_kfree_skb(',
                          'build_skb(', 'mt76_rx_token_release('):
            self.assertNotIn(forbidden, tail)
        # Four mutually exclusive raw-owner drops, none after skb takeover.
        self.assertEqual(source.count(FREE), 4)

    def test_negative_controls_kill_missing_and_overbroad_cleanup_source_mutants(self):
        # In-memory source mutations demonstrate assertion sensitivity only.
        # They are not executable C or a simulation of the page pool allocator.
        source = self.patched()
        mutants = {}
        for label, (old, new) in zip(('rx_check_release_removed', 'oom_release_removed'),
                                   DROP_DELTAS):
            self.assertEqual(source.count(new), 1)
            mutants[label] = source.replace(new, old, 1)
        marker = '\t\t\tskb_mark_for_recycle(skb);'
        self.assertEqual(source.count(marker), 1)
        mutants['raw_release_after_skb_takeover'] = source.replace(
            marker, marker + '\n\t\t\t' + FREE, 1)
        marker = 'next_page:\n'
        self.assertEqual(source.count(marker), 1)
        mutants['unconditional_release_at_next_page'] = source.replace(
            marker, marker + '\t\t\t' + FREE + '\n', 1)
        self.assertEqual(source.count('mt76_put_rxwi(mdev, t);'), 1)
        mutants['duplicate_metadata_return'] = source.replace(
            'mt76_put_rxwi(mdev, t);',
            'mt76_put_rxwi(mdev, t);\n\t\t\tmt76_put_rxwi(mdev, t);', 1)
        for label, mutant in mutants.items():
            with self.subTest(source_mutant=label):
                with self.assertRaises(AssertionError):
                    self.assert_only_drop_deltas(mutant)


if __name__ == '__main__':
    unittest.main(verbosity=2)
