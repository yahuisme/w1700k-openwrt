"""Execute the production PO merge and native gettext/po2lmo, no builds."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OverviewTranslation(unittest.TestCase):
    def run_merge(self, root, missing='', malformed=False):
        base = root / 'feeds/luci/modules/luci-base/po/zh_Hans/base.po'
        custom = root / 'profile/po/zh_Hans/base-custom.po'
        base.parent.mkdir(parents=True, exist_ok=True)
        custom.parent.mkdir(parents=True, exist_ok=True)
        if missing != 'base' and not base.exists():
            base.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n"Language: zh_Hans\\n"\n"Project-Id-Version: LuCI\\n"\n\nmsgid "Existing"\nmsgstr "已有"')
        if missing != 'custom':
            shutil.copy2(ROOT / 'user/default/po/zh_Hans/base-custom.po', custom)
            if malformed:
                custom.write_text('msgid "unterminated\n')
        source = (ROOT / 'user/default/custom.sh').read_text()
        fragment = source[source.index('BASE_PO='):source.index('echo "Airoha LuCI configuration completed.')]
        result = subprocess.run(['bash', '-ec', fragment + '\necho CONTINUED'], cwd=root,
                                env=dict(os.environ, DK_PROFILE=str(root / 'profile')), text=True, capture_output=True)
        return result, base

    def test_merge_is_idempotent_valid_and_compiles_to_luci_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, base = self.run_merge(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            first = base.read_bytes()
            self.assertIn(b'Language: zh_Hans', first)
            self.assertIn(b'Project-Id-Version: LuCI', first)
            result, _ = self.run_merge(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(base.read_bytes(), first)
            check = subprocess.run(['msgfmt', '-o', str(root / 'base.mo'), str(base)], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)
            for msgid in ('Temperature & Fan', 'Motherboard', 'Fan', 'Existing'):
                self.assertEqual(base.read_text().count(f'msgid "{msgid}"'), 1)
            po2lmo = shutil.which('po2lmo')
            self.assertIsNotNone(po2lmo, 'source /opt/test-tools/env.sh; provide native po2lmo on PATH')
            assert po2lmo is not None
            subprocess.run([po2lmo, str(base), str(root / 'base.zh-cn.lmo')], check=True)
            lmo = (root / 'base.zh-cn.lmo').read_bytes()
            for translated in ('温度与风扇', '主板', '风扇', '已有'):
                self.assertIn(translated.encode(), lmo)

    def test_real_upstream_dictionary_retains_header_and_valid_translations(self):
        if not os.environ.get('DEVICE_BASE_PO'):
            self.skipTest('set DEVICE_BASE_PO to immutable upstream base.po')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'feeds/luci/modules/luci-base/po/zh_Hans/base.po'
            base.parent.mkdir(parents=True)
            shutil.copy2(os.environ['DEVICE_BASE_PO'], base)
            result, base = self.run_merge(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            import gettext
            mo = root / 'base.mo'
            subprocess.run(['msgfmt', '-o', str(mo), str(base)], check=True)
            with mo.open('rb') as stream:
                catalog = gettext.GNUTranslations(stream)
            for msgid, expected in (('Temperature & Fan', '温度与风扇'), ('Motherboard', '主板'), ('Fan', '风扇')):
                self.assertEqual(catalog.gettext(msgid), expected)
            first = base.read_bytes()
            result, _ = self.run_merge(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(base.read_bytes(), first)

    def test_malformed_dictionary_does_not_change_upstream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Establish only the upstream fixture, then inject broken project PO.
            _, base = self.run_merge(root, missing='custom')
            original = base.read_bytes()
            result, _ = self.run_merge(root, malformed=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(base.read_bytes(), original)

    def test_missing_required_input_fails_closed(self):
        for missing in ('base', 'custom'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                result, _ = self.run_merge(Path(directory), missing=missing)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('CONTINUED', result.stdout)
                self.assertIn('ERROR:', result.stderr)


if __name__ == '__main__':
    unittest.main()
