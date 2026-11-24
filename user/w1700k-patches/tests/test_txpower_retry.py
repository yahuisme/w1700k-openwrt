"""911 TX-power source contracts and numeric protocol oracle.

These tests bind to immutable mt76/backports source and model callback routing;
they do not execute or compile kernel C, MCU firmware, or hardware.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / 'fixtures/mt76-txpower'
MANIFEST_BYTES = (FIXTURES / 'manifest.json').read_bytes()
assert hashlib.sha256(MANIFEST_BYTES).hexdigest() == '243378a8d23bc05010439e7512c19ab4a04d031c2a1bf942f03c6d55aaf865bc'
MANIFEST = json.loads(MANIFEST_BYTES)
PATCH = ROOT / 'tree/package/kernel/mt76/patches/911-mt76-mt7996-refresh-power-limits-on-txpower-changes.patch'
INT_MIN = -(2 ** 31)


def source_file(name):
    path = FIXTURES / name
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == MANIFEST['files'][name]['sha256']
    return data.decode()


def function(source, name):
    match = re.search(r'(?m)^(?:static[ \t]+)?(?:bool|int|void|u32)(?:[ \t]+|\n)' +
                      re.escape(name) + r'\([^;{}]*\)\n\{', source)
    assert match, name
    return source[match.start():source.index('\n}', match.end()) + 2]


def patched_main(patch=PATCH):
    original = source_file('mt76-mt7996-main.c.fixture')
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / 'mt7996/main.c'
        target.parent.mkdir()
        target.write_text(original)
        result = subprocess.run(
            ['patch', '-p1', '--batch', '--forward', '--fuzz=0',
             '--no-backup-if-mismatch', '-i', str(patch)],
            cwd=temp, text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        assert not list(Path(temp).rglob('*.rej'))
        assert not list(Path(temp).rglob('*.orig'))
        return target.read_text()


def bss_refresh(info, cached, sku_results, chan_results, *, changed=True,
                source=None):
    """Numeric callback oracle; branch shape is checked against real C bytes."""
    source = patched_main() if source is None else source
    block = function(source, 'mt7996_link_info_changed')
    # Accept exactly the immutable old branch or the single reviewed correction.
    match = re.search(r'if \(changed & BSS_CHANGED_TXPOWER &&(.*?)\) \{',
                      block, re.S)
    assert match, 'missing BSS power predicate'
    gate = ' '.join(match.group(1).split())
    assert gate in ('info->txpower != INT_MIN',
                    'info->txpower != INT_MIN && info->txpower != phy->txpower')
    body = block[block.index('\t\tphy->txpower = info->txpower;'):]
    assert body == BSS_UPDATE_BODY
    if not changed or info == INT_MIN or ('phy->txpower' in gate and info == cached):
        return cached, [], None
    cached = info
    calls = ['sku']
    sku = next(sku_results)
    if sku:
        return cached, calls, sku
    calls.append('chan')
    chan = next(chan_results)
    return cached, calls, chan


BSS_UPDATE_BODY = '''\t\tphy->txpower = info->txpower;
\t\tret = mt7996_mcu_set_txpower_sku(phy);
\t\tif (ret) {
\t\t\tdev_err_ratelimited(dev->mt76.dev,
\t\t\t\t\t    "failed to update txpower SKU: %d\\n",
\t\t\t\t\t    ret);
\t\t\tgoto out;
\t\t}

\t\tret = mt7996_mcu_set_chan_info(phy, UNI_CHANNEL_SWITCH);
\t\tif (ret)
\t\t\tdev_err_ratelimited(dev->mt76.dev,
\t\t\t\t\t    "failed to update txpower channel info: %d\\n",
\t\t\t\t\t    ret);
\t}

out:
\tmutex_unlock(&dev->mt76.mutex);
}'''


def config_refresh(source, powers, radio_idx, changed, requested, results):
    """Numeric oracle for the unchanged global/radio callback (POWER=1, CHANNEL=2)."""
    assert function(source, 'mt7996_config') == function(
        patched_main(FIXTURES / '911-before.patch.fixture'), 'mt7996_config')
    powers = list(powers)
    calls = []
    if not changed & 3:
        return powers, calls, 0
    if radio_idx >= len(powers):
        return powers, calls, -22
    targets = [radio_idx] if radio_idx >= 0 else range(len(powers))
    for index in targets:
        if powers[index] is None:
            continue
        if changed & 1:
            powers[index] = requested
        calls.append((index, 'sku'))
        ret = next(results)
        if not ret and changed & 1:
            calls.append((index, 'chan'))
            ret = next(results)
        if ret:
            return powers, calls, ret
    return powers, calls, 0


class TxPowerSourceContracts(unittest.TestCase):
    def test_valid_bss_notification_is_not_suppressed_by_equal_desired_cache(self):
        main = patched_main()
        block = function(main, 'mt7996_link_info_changed')
        self.assertRegex(block, r'if \(changed & BSS_CHANGED_TXPOWER &&\s*info->txpower != INT_MIN\) \{')
        self.assertNotIn('info->txpower != phy->txpower', block)
        self.assertLess(block.index('phy->txpower = info->txpower;'),
                        block.index('mt7996_mcu_set_txpower_sku(phy)'))
        self.assertIn('failed to update txpower SKU:', block)
        self.assertIn('failed to update txpower channel info:', block)

    def test_immutable_old_patch_suppresses_a_real_arriving_repeat_notification(self):
        before = FIXTURES / '911-before.patch.fixture'
        self.assertEqual(hashlib.sha256(before.read_bytes()).hexdigest(),
                         MANIFEST['historical_patch']['sha256'])
        old = patched_main(before)
        current = patched_main()
        # SKU failed, and SKU succeeded then CHANNEL_SWITCH failed. Each leaves
        # the requested cache changed; only a later *arriving* callback is tested.
        for sku, chan, expected in ((-12, 0, ['sku']), (0, -5, ['sku', 'chan'])):
            for source, repeat_calls in ((old, []), (current, ['sku', 'chan'])):
                with self.subTest(sku=sku, chan=chan, old=source == old):
                    cached, calls, status = bss_refresh(
                        20, 30, iter([sku]), iter([chan]), source=source)
                    self.assertEqual((cached, calls, status), (20, expected, sku or chan))
                    cached, calls, status = bss_refresh(
                        20, cached, iter([0]), iter([0]), source=source)
                    self.assertEqual(calls, repeat_calls)
                    self.assertEqual(status, None if source == old else 0)

    def test_entire_patched_source_diff_is_only_removal_of_bss_cache_gate(self):
        original = patched_main(FIXTURES / '911-before.patch.fixture')
        current = patched_main()
        old = '\t    info->txpower != INT_MIN &&\n\t    info->txpower != phy->txpower) {'
        new = '\t    info->txpower != INT_MIN) {'
        self.assertEqual(current.count(new), 1)
        self.assertEqual(current.replace(new, old, 1), original)

    def test_missing_txpower_change_flag_does_not_emit_updates(self):
        self.assertEqual(bss_refresh(0, 30, iter([]), iter([]), changed=False),
                         (30, [], None))

    def test_zero_dbm_is_a_valid_notification(self):
        self.assertEqual(bss_refresh(0, 30, iter([0]), iter([0])),
                         (0, ['sku', 'chan'], 0))

    def test_mutated_mcu_sequence_or_logging_is_rejected(self):
        source = patched_main()
        for token in ('ret = mt7996_mcu_set_txpower_sku(phy);',
                      'ret = mt7996_mcu_set_chan_info(phy, UNI_CHANNEL_SWITCH);',
                      '"failed to update txpower SKU: %d\\n",',
                      '\t\t\tgoto out;'):
            body_at = source.index('\tif (changed & BSS_CHANGED_TXPOWER &&')
            prefix, body = source[:body_at], source[body_at:]
            self.assertEqual(body.count(token), 1)
            with self.subTest(token=token), self.assertRaises(AssertionError):
                bss_refresh(20, 30, iter([0]), iter([0]),
                            source=prefix + body.replace(token, '', 1))

    def test_sku_failure_then_same_notification_reissues_sku_and_channel(self):
        cached, calls1, status1 = bss_refresh(90, 90, iter([-12, 0]), iter([0]))
        cached, calls2, status2 = bss_refresh(90, cached, iter([0]), iter([0]))
        self.assertEqual((cached, calls1, status1), (90, ['sku'], -12))
        self.assertEqual((cached, calls2, status2), (90, ['sku', 'chan'], 0))

    def test_channel_failure_then_same_notification_reissues_both_updates(self):
        cached, calls1, status1 = bss_refresh(84, 70, iter([0]), iter([-5]))
        cached, calls2, status2 = bss_refresh(84, cached, iter([0]), iter([0]))
        self.assertEqual((cached, calls1, status1), (84, ['sku', 'chan'], -5))
        self.assertEqual((cached, calls2, status2), (84, ['sku', 'chan'], 0))

    def test_successful_duplicate_notification_refreshes_without_cache_gate(self):
        cached, calls1, status1 = bss_refresh(72, 72, iter([0]), iter([0]))
        cached, calls2, status2 = bss_refresh(72, cached, iter([0]), iter([0]))
        self.assertEqual((cached, calls1, status1), (72, ['sku', 'chan'], 0))
        self.assertEqual((cached, calls2, status2), (72, ['sku', 'chan'], 0))

    def test_int_min_does_not_mutate_or_emit_mcu_updates(self):
        cached, calls, status = bss_refresh(INT_MIN, 66, iter([]), iter([]))
        self.assertEqual((cached, calls, status), (66, [], None))

    def test_mcu_source_proves_sku_cache_write_is_not_transactional_rollback(self):
        mcu = source_file('mt76-mt7996-mcu.c.fixture')
        sku = function(mcu, 'mt7996_mcu_set_txpower_sku')
        chan = function(mcu, 'mt7996_mcu_set_chan_info')
        cache_write = sku.index('mphy->txpower_cur = tx_power;')
        self.assertLess(cache_write, sku.index('skb = mt76_mcu_msg_alloc'))
        self.assertLess(sku.index('skb = mt76_mcu_msg_alloc'),
                        sku.index('return mt76_mcu_skb_send_msg'))
        self.assertIn('center_freq1', chan)
        self.assertNotIn('phy->txpower', chan)

    def test_global_and_radio_index_paths_keep_existing_dispatch_order(self):
        config = function(patched_main(), 'mt7996_config')
        self.assertIn('if (radio_idx >= ARRAY_SIZE(dev->radio_phy))', config)
        self.assertIn('phy = dev->radio_phy[radio_idx];', config)
        self.assertIn('mt7996_for_each_phy(dev, phy)', config)
        self.assertIn('phy->txpower = hw->conf.power_level;', config)
        self.assertIn('ret = mt7996_mcu_set_txpower_sku(phy);', config)
        self.assertIn('if (!ret && (changed & IEEE80211_CONF_CHANGE_POWER))', config)
        self.assertIn('if (ret)\n\t\t\t\tbreak;', config)

    def test_global_and_radio_numeric_boundary_matrix_preserves_first_error(self):
        source = patched_main()
        cases = (
            ('no_power_or_channel', [30, 27], -1, 0, [], [30, 27], [], 0),
            ('invalid_radio', [30, 27], 2, 1, [], [30, 27], [], -22),
            ('absent_radio', [30, None], 1, 1, [], [30, None], [], 0),
            ('radio_power_success', [30, 27], 1, 1, [0, 0], [30, 20],
             [(1, 'sku'), (1, 'chan')], 0),
            ('radio_sku_failure', [30, 27], 1, 1, [-12], [30, 20], [(1, 'sku')], -12),
            ('radio_channel_failure', [30, 27], 1, 1, [0, -5], [30, 20],
             [(1, 'sku'), (1, 'chan')], -5),
            ('channel_only_preserves_bss_limit', [30, 27], 1, 2, [0], [30, 27],
             [(1, 'sku')], 0),
            ('all_power_success_skips_null', [30, None, 27], -1, 3, [0, 0, 0, 0],
             [20, None, 20], [(0, 'sku'), (0, 'chan'), (2, 'sku'), (2, 'chan')], 0),
            ('all_sku_failure_stops', [30, 27], -1, 1, [-12], [20, 27], [(0, 'sku')], -12),
            ('all_channel_failure_stops', [30, 27], -1, 1, [0, -5], [20, 27],
             [(0, 'sku'), (0, 'chan')], -5),
            ('all_second_sku_failure', [30, 27], -1, 1, [0, 0, -12], [20, 20],
             [(0, 'sku'), (0, 'chan'), (1, 'sku')], -12),
            ('all_channel_only', [30, 27], -1, 2, [0, 0], [30, 27],
             [(0, 'sku'), (1, 'sku')], 0),
        )
        for name, powers, radio, changed, results, expected_powers, calls, status in cases:
            with self.subTest(case=name):
                self.assertEqual(config_refresh(source, powers, radio, changed, 20, iter(results)),
                                 (expected_powers, calls, status))

    def test_mac80211_same_power_assignment_does_not_force_new_notification(self):
        cfg = source_file('backports-net-mac80211-cfg.c.fixture')
        iface = source_file('backports-net-mac80211-iface.c.fixture')
        main = source_file('backports-net-mac80211-main.c.fixture')
        cfg_power = function(cfg, 'ieee80211_set_tx_power')
        recalc = function(iface, 'ieee80211_recalc_txpower')
        notify = function(main, 'ieee80211_link_info_change_notify')
        self.assertIn('ieee80211_recalc_txpower(link, update_txp_type);', cfg_power)
        self.assertIn('if (__ieee80211_recalc_txpower(link) ||', recalc)
        self.assertIn('(update_bss && ieee80211_sdata_running(link->sdata))', recalc)
        recalc_value = function(iface, '__ieee80211_recalc_txpower')
        self.assertIn('if (power != link->conf->txpower)', recalc_value)
        self.assertIn('BSS_CHANGED_TXPOWER);', recalc)
        self.assertIn('drv_link_info_changed(local, sdata, link->conf, link->link_id, changed);', notify)

    def test_mac80211_notification_routing_has_no_error_return_or_retry(self):
        dispatch = source_file('backports-net-mac80211-driver-ops.c.fixture')
        self.assertTrue(dispatch.startswith('void drv_link_info_changed('))
        self.assertIn('if (!check_sdata_in_driver(sdata))', dispatch)
        self.assertIn('if (!ieee80211_vif_link_active(&sdata->vif, link_id))', dispatch)
        self.assertIn('local->ops->link_info_changed(&local->hw, &sdata->vif,', dispatch)
        self.assertNotIn('return local->ops->link_info_changed', dispatch)
        # Source-bound numeric oracle for __recalc + recalc. Equal effective
        # power/type does not notify; type change may notify a running BSS.
        iface = source_file('backports-net-mac80211-iface.c.fixture')
        self.assertIn('if (!chanctx_conf)', iface)
        self.assertIn('if (power != link->conf->txpower)', iface)
        self.assertIn('(update_bss && ieee80211_sdata_running(link->sdata))', iface)
        cases = (
            ('same_value_and_type', 20, 20, False, True, True, False),
            ('effective_power_change', 20, 25, False, True, True, True),
            ('type_change_running', 20, 20, True, True, True, True),
            ('type_change_stopped', 20, 20, True, False, True, False),
            ('missing_channel_no_type_change', 20, 25, False, True, False, False),
        )
        for name, old, power, type_changed, running, channel, expected in cases:
            with self.subTest(case=name):
                self.assertEqual((channel and power != old) or (type_changed and running),
                                 expected)

    def test_global_mac80211_power_change_only_calls_config_when_effective_value_changes(self):
        cfg = source_file('backports-net-mac80211-cfg.c.fixture')
        main = source_file('backports-net-mac80211-main.c.fixture')
        set_power = function(cfg, 'ieee80211_set_tx_power')
        self.assertIn('(old_power != local->user_power_level)', set_power)
        self.assertIn('ieee80211_hw_conf_chan(local);', set_power)
        hwconf = function(main, 'ieee80211_calc_hw_conf_chan')
        self.assertIn('if (local->hw.conf.power_level != power)', hwconf)
        self.assertIn('IEEE80211_CONF_CHANGE_POWER', hwconf)


if __name__ == '__main__':
    unittest.main(verbosity=2)
