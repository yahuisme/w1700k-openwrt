"""Production caller + ordered exact source replay; no kernel C/hardware execution."""
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from scripts.select_distribution import select
from scripts.validate_firmware import validate, finalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/w1700k-native-fixes'
RESET = 'target/linux/airoha/patches-6.18/609-02-clk-en7523-add-support-for-dedicated-PCIe-PERSTOUT-r.patch'
MT76 = 'package/kernel/mt76'
NEW = ('915-mt76-npu-rx-packet-reassembly.patch',
       '916-mt76-radiotap-tlv-header.patch', '917-mt76-amsdu-subframe-header.patch')
ROOT_PATCHES = ('004-airoha-reset-initialize-value.patch', '005-eip93-cbc-dependency.patch')


def apply(work, payload):
    result = subprocess.run(['patch', '-p1', '--batch', '--forward', '--fuzz=0',
                             '--no-backup-if-mismatch'], input=payload, cwd=work,
                            capture_output=True)
    if os.environ.get('NATIVE_FIX_REPLAY_LOG'):
        with open(os.environ['NATIVE_FIX_REPLAY_LOG'], 'a') as log:
            log.write(json.dumps({'work': str(work), 'patch_sha256': hashlib.sha256(payload).hexdigest(),
                                  'exit': result.returncode, 'stdout': result.stdout.decode(),
                                  'stderr': result.stderr.decode()}) + '\n')
    if result.returncode or b'fuzz' in result.stdout.lower():
        raise AssertionError(result.stdout.decode() + result.stderr.decode())
    if list(work.rglob('*.rej')) or list(work.rglob('*.orig')):
        raise AssertionError('patch reject/backup entered source tree')
    return result.stdout.decode()


class NativeFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = (FIXTURE / 'sources.tar.gz').read_bytes()
        cls.manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        assert hashlib.sha256(raw).hexdigest() == cls.manifest['archive_sha256']
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            cls.files = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}
        assert set(cls.files) == set(cls.manifest['files'])
        for name, data in cls.files.items():
            assert hashlib.sha256(data).hexdigest() == cls.manifest['files'][name]['sha256']

    def populate(self, root, prefix):
        for name, data in self.files.items():
            if name.startswith(prefix + '/'):
                path = root / name[len(prefix) + 1:]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    def recipe(self, base, distro):
        recipe = base / 'recipe'
        for name in ('user', 'installer'):
            shutil.copytree(ROOT / name, recipe / name)
        select(distro, recipe)
        return recipe

    def production(self, source, recipe):
        script = (recipe / 'user/default/custom.sh').read_text()
        start = script.index('# Required patches')
        stop = script.index('patch -p1 --fuzz=0 --no-backup-if-mismatch < "$PATCH_DIR/patches/002-')
        # This is the verbatim production block, including preflight, guards,
        # native repairs, ttyd and overlay copy. No patch logic is mocked.
        result = subprocess.run(['bash', '-ec', script[start:stop]], cwd=source,
                                env=dict(os.environ, DK_USER=str(recipe / 'user')),
                                capture_output=True, text=True)
        if os.environ.get('NATIVE_FIX_REPLAY_LOG'):
            with open(os.environ['NATIVE_FIX_REPLAY_LOG'], 'a') as log:
                log.write(json.dumps({'production': str(recipe / 'user/default/custom.sh'),
                                      'exit': result.returncode, 'stdout': result.stdout,
                                      'stderr': result.stderr}) + '\n')
        return result

    def setup_source(self, base, distro):
        work = base / 'source'
        self.populate(work, distro)
        ttyd = work / 'feeds/packages/utils/ttyd/Makefile'
        ttyd.parent.mkdir(parents=True)
        ttyd.write_text('PKG_VERSION:=1.7.7\nPKG_RELEASE:=1\nPKG_HASH:=039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650\n')
        return work

    def replay(self, base, distro, work):
        mt = base / 'mt76'
        self.populate(mt, 'mt76')
        names = []
        for patch in sorted((work / MT76 / 'patches').glob('*.patch')):
            apply(mt, patch.read_bytes())
            names.append(patch.name)
        self.assertEqual(names[-3:], list(NEW), 'new fixes not on the native package patch chain')
        self.assertIn('911-mt76-mt7996-refresh-power-limits-on-txpower-changes.patch', names)
        # Each backport must have the exact official +/- semantics, not just a
        # hand-written source-string approximation.
        for name, sha in zip(NEW, ('a801adb009f70cde062de22976d4d6c7dc13daa8',
                                  '1a519350810083fce4ae1ab00ff58f02b716f6e0',
                                  '6145ff0b02f315f8e80af01345cb3bd6caa62b84')):
            self.assertEqual((work / MT76 / 'patches' / name).read_bytes(),
                             self.files['official/' + sha + '.patch'])
        kernel = base / 'kernel'
        version = '6.18.64' if distro == 'openwrt' else '6.18.60'
        self.populate(kernel, 'linux-' + version)
        for path in sorted(name for name in self.files if name.startswith(distro + '/clock-chain/')):
            # The caller repairs the original native patch at buildroot layer.
            patch = (work / RESET).read_bytes() if Path(path).name == Path(RESET).name else self.files[path]
            if Path(path).name == Path(RESET).name:
                patch = patch[patch.index(b'--- a/drivers/clk/'):]
            apply(kernel, patch)
        clock = (kernel / 'drivers/clk/clk-en7523.c').read_text()
        self.assertNotIn('val |= assert ?', clock)
        self.assertIn('val = assert ? 0 : BIT(id % RST_NR_PER_BANK);', clock)
        self.assertIn('val = assert ? BIT(id % RST_NR_PER_BANK) : 0;', clock)
        # Masked reset truth table: both banks, assertion states and arbitrary
        # incoming stack bits. This models assignment, not executing undefined C.
        for inverted in (False, True):
            for asserted in (False, True):
                for stale in (0, 1, 0xffffffff):
                    expected = int(asserted != inverted)
                    value = (0 if asserted else 1) if inverted else (1 if asserted else 0)
                    self.assertEqual(value & 1, expected)
        crypto = (work / 'package/kernel/linux/modules/crypto.mk').read_text()
        eip = crypto.split('define KernelPackage/crypto-hw-eip93\n')[1].split('\nendef')[0]
        self.assertEqual(eip.count('+kmod-crypto-cbc'), 1)
        return mt

    def test_each_native_repair_is_maintained_and_replayed(self):
        distro = json.loads((ROOT / 'user/default/build.json').read_text())['system']
        for name in ROOT_PATCHES:
            with self.subTest(patch=name), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                self.populate(work, distro)
                patch = ROOT / 'user/w1700k-patches/patches' / name
                self.assertTrue(patch.is_file(), 'missing maintained native repair: ' + name)
                apply(work, patch.read_bytes())
                if name.startswith('004-'):
                    self.assertNotIn('val |= assert ?', (work / RESET).read_text())
                else:
                    text = (work / 'package/kernel/linux/modules/crypto.mk').read_text()
                    eip = text.split('define KernelPackage/crypto-hw-eip93\n')[1].split('\nendef')[0]
                    self.assertIn('+kmod-crypto-cbc', eip)

    def test_both_default_callers_apply_exact_ordered_sources(self):
        for distro in (json.loads((ROOT / 'user/default/build.json').read_text())['system'],):
            with self.subTest(distro=distro), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                recipe = self.recipe(base, distro)
                work = self.setup_source(base, distro)
                result = self.production(work, recipe)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                mt = self.replay(base, distro, work)
                self.check_source_models(mt)
                for filename, before, after in (
                    ('npu.c', 'q->queued--;', 'q->queued -= 0;'),
                    ('mt76.h', 'return skb_mac_header(skb);', 'return skb->data;'),
                    ('mac80211.c', 'ether_addr_equal(subframe, rfc1042_header)',
                     'ether_addr_equal(skb->data, rfc1042_header)'),
                ):
                    path = mt / filename
                    original = path.read_text()
                    self.assertIn(before, original)
                    path.write_text(original.replace(before, after))
                    with self.assertRaises(AssertionError):
                        self.check_source_models(mt)
                    path.write_text(original)
                config = (recipe / 'user/default/config.diff').read_text()
                for package in ('kmod-crypto-hw-eip93', 'kmod-crypto-cbc'):
                    self.assertEqual(config.splitlines().count('CONFIG_PACKAGE_' + package + '=y'),
                                     int(distro == 'immortalwrt'))
                # Exercise the workflow's actual profile -> builder config copy.
                from workflow_fixture import build_job
                block = next(step['run'] for step in build_job()['steps'] if step.get('id') == 'inputs')
                command = next(line.strip() for line in block.splitlines()
                               if line.strip() == 'cp $DK_PROFILE/config.diff .config')
                subprocess.run(['bash', '-ec', command], cwd=base,
                               env=dict(os.environ, DK_PROFILE=str(recipe / 'user/default')), check=True)
                self.assertEqual((base / '.config').read_text(), config)

    def check_source_models(self, mt):
        npu = (mt / 'npu.c').read_text()
        header = (mt / 'mt76.h').read_text()
        mac = (mt / 'mac80211.c').read_text()
        self.assertIn('int pending;', header)
        self.assertIn('q->pending = nframes;', npu)
        self.assertIn('q->rx_head = napi_build_skb', npu)
        self.assertIn('dev_kfree_skb(q->rx_head);', npu)
        self.assertLess(npu.index('dma_rmb();'), npu.index('info = desc[q->tail].info;'))
        # Full reached function hashes come from exact official fix commits,
        # also compared to the later upstream master; no textual-token-only pass.
        for name, identity in self.manifest['fixed_functions'].items():
            source = (mt / identity['file']).read_text()
            start = source.rfind('\n', 0, source.index(name)) + 1
            opening = source.index('{', source.index(name))
            depth = 0
            body = ''
            for index in range(opening, len(source)):
                depth += (source[index] == '{') - (source[index] == '}')
                if depth == 0:
                    body = source[start:index + 2]
                    break
            if name == 'mt76_rx_release_amsdu(':
                # Upstream's earlier 6a2f1454 independently changes station/WCID
                # ownership, not header/subframe location. Normalize only its
                # exact prologue, retaining the entire reached validation body.
                selected = ('\tstruct sk_buff *skb = phy->rx_amsdu[q].head;\n'
                            '\tstruct mt76_rx_status *status = (struct mt76_rx_status *)skb->cb;\n'
                            '\tstruct mt76_dev *dev = phy->dev;\n'
                            '\tstruct mt76_queue *rxq = &dev->q_rx[q];\n\n'
                            '\tphy->rx_amsdu[q].head = NULL;\n'
                            '\tphy->rx_amsdu[q].tail = NULL;\n')
                official = ('\tstruct sk_buff *skb = mt76_rx_amsdu_detach(phy, q);\n'
                            '\tstruct mt76_rx_status *status = (struct mt76_rx_status *)skb->cb;\n'
                            '\tstruct mt76_dev *dev = phy->dev;\n'
                            '\tstruct mt76_queue *rxq = &dev->q_rx[q];\n\n'
                            '\t/* status->wcid was looked up in an earlier RCU section. It can only be\n'
                            '\t * used if the wcid is still published, which keeps it alive until the\n'
                            '\t * end of the current RCU section.\n'
                            '\t */\n'
                            '\tif (status->amsdu && status->wcid &&\n'
                            '\t    __mt76_wcid_ptr(dev, phy->rx_amsdu[q].wcid_idx) != status->wcid) {\n'
                            '\t\tdev_kfree_skb(skb);\n'
                            '\t\treturn;\n'
                            '\t}\n')
                self.assertEqual(body.count(selected), 1)
                body = body.replace(selected, official, 1)
            self.assertEqual(hashlib.sha256(body.encode()).hexdigest(), identity['sha256'], name)
        # Complete official added lines further bind the model to applied C.
        official = self.files['official/a801adb009f70cde062de22976d4d6c7dc13daa8.patch'].decode()
        for line in official.splitlines():
            if line.startswith('+') and not line.startswith('+++') and line[1:].strip():
                self.assertIn(line[1:], npu + header)
        # Model the official queue ownership rules after full-function binding.
        class Queue:
            def __init__(self, start=0, count=2):
                self.tail, self.queued = start, count
                self.pending, self.skb = 0, []
                self.consumed, self.delivered, self.freed = [], [], []
                self.dma_idx = start

            def poll(self, ready, count=2, allocate=True):
                remaining = self.pending
                while True:
                    if not self.queued or not ready[len(self.consumed)]:
                        self.pending = remaining
                        return 'EBUSY'
                    if not remaining and remaining == self.pending:
                        remaining = max(count, 1)
                    if not self.skb and not allocate:
                        return 'ENOMEM'
                    buffer = len(self.consumed)
                    self.skb.append(buffer)
                    self.consumed.append(buffer)
                    self.tail = (self.tail + 1) % 4
                    self.queued -= 1
                    remaining -= 1
                    if not remaining:
                        self.delivered.append(self.skb)
                        self.skb, self.pending = [], 0
                        self.dma_idx = self.tail
                        return 'OK'

            def cleanup(self):
                # Queued buffers and the skb are disjoint owners; no reuse.
                self.freed += list(range(len(self.consumed), len(self.consumed) + self.queued))
                self.tail = (self.tail + self.queued) % 4
                self.queued = 0
                if self.skb:
                    self.freed += self.skb
                    self.skb, self.pending = [], 0

        for start in (0, 3):
            queue = Queue(start)
            self.assertEqual(queue.poll((False, False)), 'EBUSY')
            self.assertEqual((queue.tail, queue.queued, queue.skb, queue.pending), (start, 2, [], 0))
            self.assertEqual(queue.poll((True, False), allocate=False), 'ENOMEM')
            self.assertEqual((queue.tail, queue.queued, queue.skb), (start, 2, []))
            self.assertEqual(queue.poll((True, False)), 'EBUSY')
            self.assertEqual((queue.tail, queue.queued, queue.pending, queue.delivered),
                             ((start + 1) % 4, 1, 1, []))
            self.assertEqual(queue.dma_idx, start)
            self.assertEqual(queue.poll((True, False)), 'EBUSY')
            self.assertEqual(queue.consumed, [0])
            self.assertEqual(queue.poll((True, True)), 'OK')
            self.assertEqual((queue.consumed, queue.delivered, queue.queued, queue.pending),
                             ([0, 1], [[0, 1]], 0, 0))
            self.assertEqual(queue.dma_idx, (start + 2) % 4)
        queue = Queue()
        self.assertEqual(queue.poll((True, False)), 'EBUSY')
        queue.cleanup()
        self.assertEqual((sorted(queue.freed), queue.skb, queue.pending, queue.queued), ([0, 1], [], 0, 0))
        queue.cleanup()
        self.assertEqual(sorted(queue.freed), [0, 1])
        self.assertEqual(queue.poll(()), 'EBUSY')
        queue = Queue(count=1)
        self.assertEqual(queue.poll((True,), count=0), 'OK')
        self.assertEqual(queue.delivered, [[0]])
        self.assertIn('if (!q->rx_head)\n\t\t\t\treturn -ENOMEM;', npu)
        cleanup = npu[npu.index('void mt76_npu_queue_cleanup'):npu.index('static int mt76_npu_rx_process_entry')]
        self.assertIn('q->rx_head = NULL;\n\t\tq->pending = 0;', cleanup)
        self.assertIn('return skb_mac_header(skb);', header)
        self.assertIn('struct ieee80211_hdr *hdr = mt76_skb_get_hdr(skb);', mac)
        self.assertIn('ether_addr_equal(subframe, rfc1042_header)', mac)
        # Radiotap/802.11/IV boundaries: plain, HE, HE-MU, EHT; raw 802.3.
        rfc = bytes.fromhex('aaaa03000000')
        def hdr_offset(*, he=False, he_mu=False, eht=False, mac_header=0):
            # Source-bound mt76_skb_get_hdr branch order; EHT must win even if
            # HE flags are also present. The original helper fails this case.
            if eht and 'return skb_mac_header(skb);' in header:
                return mac_header
            return 12 * he + 12 * he_mu

        def rejected(packet, *, flags, mac_header=0, ethernet=False,
                     decrypted=False, stripped=False, fragments=True):
            if not fragments:
                return False
            if ethernet:
                offset = 0
            else:
                offset = hdr_offset(**flags, mac_header=mac_header)
                # 0x0088 QoS data has a 26-byte header. Real ieee80211_hdrlen
                # uses the actual returned header's frame_control.
                fc = int.from_bytes(packet[offset:offset + 2], 'little')
                length = 26 if fc & 0x00fc == 0x0088 else 24
                offset += length + (8 if decrypted and not stripped else 0)
            return packet[offset:offset + 6] == rfc

        for flags, prefix in (({}, 0), ({'he': True}, 12),
                              ({'he': True, 'he_mu': True}, 24),
                              ({'eht': True}, 40),
                              ({'eht': True, 'he': True}, 40)):
            for decrypted, stripped in ((False, False), (True, False), (True, True)):
                iv = 8 if decrypted and not stripped else 0
                data = (b'\x21\0' + b'\0' * (prefix - 2)) if prefix else b''
                packet = data + b'\x88\0' + b'\0' * 24 + b'\0' * iv + rfc
                options: dict[str, Any] = dict(flags=flags, mac_header=prefix, decrypted=decrypted, stripped=stripped)
                self.assertEqual(hdr_offset(**flags, mac_header=prefix), prefix)
                self.assertTrue(rejected(packet, **options))
                self.assertFalse(rejected(packet[:-6] + b'normal', **options))
                self.assertFalse(rejected(packet, fragments=False, **options))
        self.assertTrue(rejected(rfc, flags={}, ethernet=True))
        self.assertFalse(rejected(b'normal', flags={}, ethernet=True))

    def test_source_drift_absorption_and_conflicts_stop_before_copy(self):
        for distro in (json.loads((ROOT / 'user/default/build.json').read_text())['system'],):
            for fault in ('version', 'mirror', 'native-patch', 'reset-absorbed', 'cbc-absorbed',
                          'collision', 'symlink', 'patch-reject-reset', 'patch-reject-cbc'):
                with self.subTest(distro=distro, fault=fault), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    recipe = self.recipe(base, distro)
                    work = self.setup_source(base, distro)
                    target = work / MT76 / 'Makefile'
                    if fault == 'version':
                        target.write_text(target.read_text().replace(self.manifest['mt76'], '0' * 40))
                    if fault == 'mirror':
                        target.write_text(target.read_text().replace('3a3844097e66021f21f0ec8508cb740ef6536a2243f74c47fd5a898edb26839f', '0' * 64))
                    if fault == 'native-patch':
                        next((work / MT76 / 'patches').glob('*.patch')).write_text('unexpected\n')
                    if fault == 'reset-absorbed':
                        p = work / RESET
                        p.write_text(p.read_text().replace('val |= assert ?', 'val = assert ?'))
                    if fault == 'cbc-absorbed':
                        p = work / 'package/kernel/linux/modules/crypto.mk'
                        p.write_text(p.read_text().replace('+kmod-crypto-authenc \\\n', '+kmod-crypto-authenc \\\n\t+kmod-crypto-cbc \\\n'))
                    if fault in ('collision', 'symlink'):
                        p = work / MT76 / 'patches' / NEW[0]
                        p.symlink_to('/dev/null') if fault == 'symlink' else p.write_text('upstream owner\n')
                    if fault.startswith('patch-reject-'):
                        name = ROOT_PATCHES[int(fault.endswith('cbc'))]
                        payload = recipe / 'user/w1700k-patches/patches' / name
                        original = payload.read_text()
                        before_line = ('-+\t\tval |= assert ? 0 : BIT(id % RST_NR_PER_BANK);' if fault.endswith('reset')
                                       else ' \t+kmod-crypto-authenc \\')
                        self.assertIn(before_line, original)
                        payload.write_text(original.replace(before_line, before_line + ' unreviewed'))
                    before = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob('*') if p.is_file()}
                    result = self.production(work, recipe)
                    self.assertNotEqual(result.returncode, 0, 'unreviewed/absorbed source silently accepted')
                    if fault.startswith('patch-reject-'):
                        self.assertIn('FAILED', result.stdout)
                    else:
                        diagnostic = ('conflicting mt76 backport' if fault in ('collision', 'symlink') else
                                      'unreviewed mt76 source' if fault in ('version', 'mirror') else
                                      'unreviewed mt76 native patches' if fault == 'native-patch' else
                                      'unreviewed Airoha reset/EIP93 source')
                        self.assertIn('ERROR: ' + diagnostic, result.stderr)
                    after = {str(p.relative_to(work)): p.read_bytes() for p in work.rglob('*') if p.is_file()}
                    self.assertEqual(before, after)


class Eip93Acceptance(unittest.TestCase):
    def test_final_config_and_device_manifest(self):
        from test_release_safety import ReleaseTests, MATRIX
        distro = MATRIX['system']
        for package in ('kmod-crypto-hw-eip93', 'kmod-crypto-cbc'):
            for fault in ('valid', 'absent', 'module', 'disabled', 'duplicate', 'conflict', 'manifest-missing', 'manifest-duplicate', 'manifest-absent', 'manifest-empty', 'manifest-symlink'):
                with self.subTest(package=package, fault=fault), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    output, _ = ReleaseTests().fixture(base)
                    config = base / '.config'
                    selected = 'CONFIG_PACKAGE_' + package + '=y\n'
                    text = config.read_text()
                    if distro == 'immortalwrt':
                        for pkg in ('kmod-crypto-hw-eip93', 'kmod-crypto-cbc'):
                            line = 'CONFIG_PACKAGE_' + pkg + '=y\n'
                            if line not in text:
                                text += line
                    if fault == 'absent': text = text.replace(selected, '')
                    if fault == 'module': text = text.replace(selected, selected.replace('=y', '=m'))
                    if fault == 'disabled': text = text.replace(selected, '# CONFIG_PACKAGE_' + package + ' is not set\n')
                    if fault == 'duplicate': text += selected
                    if fault == 'conflict': text += selected.replace('=y', '=m')
                    config.write_text(text)
                    image = MATRIX['system'] + '-airoha-an7581-gemtek_w1700k-ubi'
                    manifest = output / (image + '.manifest')
                    entries = ['kmod-crypto-hw-eip93 - 6.18.60-r1', 'kmod-crypto-cbc - 6.18.60-r1']
                    if fault == 'manifest-missing': entries = [x for x in entries if not x.startswith(package + ' - ')]
                    if fault == 'manifest-duplicate': entries += [next(x for x in entries if x.startswith(package + ' - '))]
                    manifest.write_text('\n'.join(entries) + '\n')
                    if fault == 'manifest-absent': manifest.unlink()
                    if fault == 'manifest-empty': manifest.write_text('')
                    if fault == 'manifest-symlink':
                        manifest.rename(output / 'other.manifest')
                        manifest.symlink_to('other.manifest')
                    for checker in (validate, finalize):
                        if fault == 'valid' or distro == 'openwrt':
                            self.assertTrue(checker(config, base / 'openwrt_bin/targets', distro)['images'])
                        else:
                            with self.assertRaisesRegex(ValueError, package):
                                checker(config, base / 'openwrt_bin/targets', distro)
                    result = ReleaseTests().stage(base)
                    self.assertEqual(result.returncode == 0, fault == 'valid' or distro == 'openwrt', result.stderr)
                    if distro == 'immortalwrt' and fault != 'valid':
                        self.assertIn(package, result.stderr)
                        self.assertFalse((base / 'firmware').exists())


if __name__ == '__main__':
    unittest.main()
