"""Source-bound TX-free cleanup regression; no C or firmware compilation."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'tree/package/kernel/mt76/patches/913-mt76-mt7996-clean-up-truncated-txfree.patch'
FIXTURE = Path(__file__).parent / 'fixtures/mt76-txfree/mt7996/mac.c'
QUEUE_FIXTURE = FIXTURE.with_name('queue_rx_skb.c')
QUEUE_MARKER = 'void mt7996_queue_rx_skb('
CHECK_FIXTURE = FIXTURE.with_name('rx_check.c')
CHECK_MARKER = 'bool mt7996_rx_check('
QUEUE_DELTA = (
    '\t\tmt7996_mac_tx_free(dev, skb->data, skb->len);\n',
    '\t\tif (pskb_may_pull(skb, skb->len))\n'
    '\t\t\tmt7996_mac_tx_free(dev, skb->data, skb->len);\n',
)
QUEUE_ENTRY_DELTA = (
    '\t__le32 *rxd = (__le32 *)skb->data;\n'
    '\t__le32 *end = (__le32 *)&skb->data[skb->len];\n'
    '\tenum rx_pkt_type type;\n\n',
    '\t__le32 *rxd, *end;\n'
    '\tenum rx_pkt_type type;\n\n'
    '\tif (!pskb_may_pull(skb, sizeof(*rxd))) {\n'
    '\t\tdev_kfree_skb(skb);\n\t\treturn;\n\t}\n\n'
    '\trxd = (__le32 *)skb->data;\n'
    '\tend = (__le32 *)&skb->data[skb->len];\n',
)
RAW_ENTRY_DELTA = (
    '\t__le32 *end = (__le32 *)&rxd[len / 4];\n'
    '\tenum rx_pkt_type type;\n\n',
    '\t__le32 *end;\n'
    '\tenum rx_pkt_type type;\n\n'
    '\tif (len < (int)sizeof(*rxd))\n\t\treturn false;\n\n'
    '\tend = (__le32 *)&rxd[len / 4];\n',
)
GUARD = '\t\tif (WARN_ON_ONCE((void *)cur_info >= end))\n'
# Explicit allowed deltas; the immutable official fixture must never be refreshed
# to the patched bytes. Everything outside these unique matches remains exact.
HEADER_DELTAS = (
    ('\tvoid *end = data + len;\n', '\tvoid *end;\n'),
    ('\t/* clean DMA queues and unmap buffers first */\n',
     '\tif (len < 2 * (int)sizeof(*tx_free))\n'
     '\t\treturn;\n\n'
     '\tend = data + len;\n\n'
     '\t/* clean DMA queues and unmap buffers first */\n'),
)
WORD_GUARD = ('\t\tif (WARN_ON_ONCE((void *)cur_info >= end ||\n'
              '\t\t\t\t end - (void *)cur_info < sizeof(*cur_info)))\n')
WORD_DELTA = (GUARD + '\t\t\treturn;', WORD_GUARD + '\t\t\tbreak;')
PAIR_DELTA = (
    '\t\t\tif (ver == 7 && ((void *)(cur_info + 1) < end) &&\n',
    '\t\t\tif (ver == 7 &&\n'
    '\t\t\t    end - (void *)(cur_info + 1) >= sizeof(*cur_info) &&\n',
)


class TxFreeCleanupTests(unittest.TestCase):
    def patched(self, queue=False, check=False):
        original = FIXTURE.read_text()
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         'a22a9a73f3db00e933ee79041dbf41e9d1abe481e1d7c7babffe2ff0d0ec8fbf')
        self.assertEqual(hashlib.sha256(QUEUE_FIXTURE.read_bytes()).hexdigest(),
                         '27befddc178b6e4c9b3403b97ea724a70af5ddd0d7e84f5bb072e58241998b55')
        self.assertEqual(hashlib.sha256(CHECK_FIXTURE.read_bytes()).hexdigest(),
                         '8ca542bea25ff041c32d92f122a3fd5b7f9d13fe2043b5b4108eb1aa58eaef00')
        # Apply the actual production patch to immutable official entrypoints.
        # Their line offsets are irrelevant; patch must match all context, no fuzz.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'mt7996/mac.c'
            target.parent.mkdir()
            target.write_text(original + CHECK_FIXTURE.read_text() + QUEUE_FIXTURE.read_text())
            result = subprocess.run(['patch', '-p1', '--batch', '--forward', '--fuzz=0',
                                     '--no-backup-if-mismatch', '-i', str(PATCH)],
                                    cwd=tmp, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            parser, remaining = target.read_text().split(CHECK_MARKER)
            checked, rx = remaining.split(QUEUE_MARKER)
            return CHECK_MARKER + checked if check else QUEUE_MARKER + rx if queue else parser

    def replace_unique(self, text, old, new):
        self.assertEqual(text.count(old), 1, f'non-unique source delta: {old!r}')
        return text.replace(old, new, 1)

    def expected_parser(self):
        expected = FIXTURE.read_text()
        for old, new in (*HEADER_DELTAS, WORD_DELTA, PAIR_DELTA):
            expected = self.replace_unique(expected, old, new)
        return expected

    def test_rx_entrypoints_validate_first_word_before_classification(self):
        raw = self.patched(check=True)
        self.assertIn('if (len < (int)sizeof(*rxd))\n\t\treturn false;', raw)
        self.assertLess(raw.index('if (len <'), raw.index('type = le32_get_bits(rxd[0]'))
        self.assertLess(raw.index('if (len <'), raw.index('end = '))
        queued = self.patched(queue=True)
        self.assertIn('if (!pskb_may_pull(skb, sizeof(*rxd))) {', queued)
        prefix = queued[:queued.index('type = le32_get_bits(rxd[0]')]
        self.assertIn('dev_kfree_skb(skb);\n\t\treturn;', prefix)
        self.assertLess(prefix.index('pskb_may_pull'), prefix.index('rxd = (__le32 *)skb->data;'))
        self.assertLess(prefix.index('pskb_may_pull'), prefix.index('end = '))

    def test_fragmented_txfree_is_pulled_before_parser_and_always_consumed(self):
        text = self.patched(queue=True)
        self.assertIn(QUEUE_DELTA[1] + '\t\tnapi_consume_skb(skb, 1);', text)
        expected = QUEUE_FIXTURE.read_text()
        for delta in (QUEUE_ENTRY_DELTA, QUEUE_DELTA):
            expected = self.replace_unique(expected, *delta)
        self.assertEqual(text, expected,
                         'only validate RX header/pull TXFREE; keep WED and other branches')
        raw_expected = self.replace_unique(CHECK_FIXTURE.read_text(), *RAW_ENTRY_DELTA)
        self.assertEqual(self.patched(check=True), raw_expected)

    def test_short_header_is_rejected_before_dma_cleanup_or_header_access(self):
        text = self.patched()
        self.assertIn('\tif (len < 2 * (int)sizeof(*tx_free))\n\t\treturn;', text)
        self.assertLess(text.index('if (len <'), text.index('end = data + len;'))
        self.assertLess(text.index('if (len <'), text.index('mt76_queue_tx_cleanup'))
        self.assertLess(text.index('if (len <'), text.index('tx_free[1]'))

    def test_partial_info_word_keeps_warning_and_breaks_before_read(self):
        text = self.patched()
        self.assertIn(WORD_GUARD + '\t\t\tbreak;', text)
        self.assertLess(text.index(WORD_GUARD), text.index('info = le32_to_cpu(*cur_info);'))

    def test_ver7_extension_is_read_only_as_a_complete_word(self):
        self.assertIn(PAIR_DELTA[1], self.patched())

    def test_truncated_event_reaches_existing_cleanup_without_losing_warning(self):
        expected = self.expected_parser()
        self.assertEqual(self.patched(), expected,
                         'only the explicit header and cleanup deltas are permitted')
        for call in ('mt76_set_tx_blocked', 'mt76_worker_schedule', 'napi_consume_skb'):
            self.assertIn(call, expected[expected.index('mt7996_mac_sta_poll(dev);'):])

    def test_invalid_version_and_normal_processing_remain_unchanged(self):
        text = self.patched()
        self.assertIn('if (WARN_ON_ONCE(ver < 5))\n\t\treturn;', text)
        for old, new in reversed((*HEADER_DELTAS, WORD_DELTA, PAIR_DELTA)):
            text = self.replace_unique(text, new, old)
        self.assertEqual(text, FIXTURE.read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
