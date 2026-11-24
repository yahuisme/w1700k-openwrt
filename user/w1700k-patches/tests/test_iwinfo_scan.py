"""Pinned iwinfo patch-chain/source contracts, not executed C or RF tests."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / 'fixtures/iwinfo-scan'
PATCHES = ROOT / 'tree/package/network/utils/iwinfo/patches'
PATCH = PATCHES / '998-fix-multi-radio-scan.patch'


def function(source, name):
    match = re.search(r'\b' + re.escape(name) + r'\([^;{}]*\)\s*\{', source)
    if match is None:
        raise AssertionError('missing function: ' + name)
    begin = source.index('{', match.start())
    depth, end = 1, begin + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]


class IwinfoScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='iwinfo-scan-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        manifest = json.loads((FIXTURES / 'manifest.json').read_text())
        for name, record in manifest['files'].items():
            data = (FIXTURES / name).read_bytes()
            assert hashlib.sha256(data).hexdigest() == record['sha256'], name
            if 'source' in record:
                dest = cls.root / record['source']
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        for patch in [FIXTURES / '100-multi_radio.patch.fixture',
                      *sorted(PATCHES.glob('*.patch'))]:
            result = subprocess.run(['patch', '-p1', '--batch', '--fuzz=0',
                                     '--no-backup-if-mismatch', '-i', str(patch)],
                                    cwd=cls.root, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
        cls.source = (cls.root / 'iwinfo_nl80211.c').read_text()

    def test_existing_interfaces_are_selected_by_requested_radio(self):
        # The same phy must not make radio2 reuse the active radio0 netdev.
        body = function(self.source, 'nl80211_phy2ifname')
        self.assertIn('nl80211_radio_mask_from_uci(ifname, &radio_mask)', body)
        self.assertIn('nl80211_get_if_data(e->d_name, &data)', body)
        self.assertIn('data.radio_mask != radio_mask', body)
        self.assertLess(body.index('data.radio_mask != radio_mask'),
                        body.index('strncpy(nif'))
        self.assertIn('continue;', body[body.index('data.radio_mask != radio_mask'):])

    def test_radio_mask_is_retained_without_collapsing_multilink_masks(self):
        body = function(self.source, 'nl80211_get_mode_cb')
        self.assertIn('data->radio_mask = mask;', body)
        self.assertIn('data->radio_mask = 0;', function(self.source, 'nl80211_get_if_data'))
        self.assertIn('uint32_t radio_mask;', self.source)

    def test_temporary_scan_interface_is_bound_and_creation_failure_is_visible(self):
        body = function(self.source, 'nl80211_ifadd')
        self.assertIn('nl80211_radio_mask_from_uci(ifname, &radio_mask)', body)
        self.assertRegex(body, r'if \(radio_mask\)\s+NLA_PUT_U32\(req->msg, NL80211_ATTR_VIF_RADIO_MASK, radio_mask\);')
        self.assertRegex(body, r'if \(nl80211_send\(req, NULL, NULL\)\)\s+return NULL;')
        self.assertLess(body.index('NL80211_ATTR_VIF_RADIO_MASK'), body.index('nl80211_send'))

    def test_uci_radio_index_is_explicit_and_bounded(self):
        body = function(self.source, 'nl80211_radio_mask_from_uci')
        self.assertIn('uci_lookup_option(uci_ctx, s, "radio")', body)
        self.assertIn('strtoul(value, &end, 10)', body)
        self.assertIn('end != value && !*end && idx < 32', body)
        self.assertIn('1U << idx', body)
        self.assertIn('iwinfo_uci_free();', body)
        self.assertNotIn('atoi(', body)

    def test_invalid_explicit_radio_does_not_fall_back_to_any_radio(self):
        body = function(self.source, 'nl80211_radio_mask_from_uci')
        self.assertIn('opt->type != UCI_TYPE_STRING', body)
        self.assertIn("*value < '0' || *value > '9'", body)
        self.assertIn('ret = -1;', body)
        self.assertIn('return ret;', body)
        for name in ('nl80211_phy2ifname', 'nl80211_ifadd'):
            with self.subTest(name=name):
                self.assertRegex(function(self.source, name),
                    r'if \(nl80211_radio_mask_from_uci\(ifname, &radio_mask\)\)\s+return NULL;')

    def test_disabled_radio_preserves_native_temporary_scan_and_cleanup(self):
        body = function(self.source, 'nl80211_get_scanlist')
        self.assertIn('else if ((res = nl80211_ifadd(ifname)) != NULL)', body)
        self.assertRegex(body, r'rv = nl80211_get_scanlist\(res, buf, len\);\s+nl80211_ifdel\(res\);\s+return rv;')
        self.assertNotIn('disabled', body)
        self.assertNotIn('iwinfo_ifdown(ifname)', body[:body.index('/* WPA supplicant */')])

    def test_both_distro_recipes_pin_the_verified_predecessor(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text())
        self.assertEqual(set(manifest['revisions']), {'iwinfo', 'openwrt', 'immortalwrt'})
        recipe = (FIXTURES / 'Makefile.fixture').read_text()
        self.assertIn('PKG_SOURCE_VERSION:=' + manifest['revisions']['iwinfo'], recipe)
        self.assertEqual(list(self.root.rglob('*.orig')), [])
        self.assertTrue(PATCH.is_file(), 'radio scan fix must be shipped')


if __name__ == '__main__':
    unittest.main(verbosity=2)
