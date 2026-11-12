"""Build-profile wiring and cache/artifact contracts, no compilation."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SharedProfileTests(unittest.TestCase):
    def helper(self):
        spec = importlib.util.spec_from_file_location('profile_test', ROOT / 'scripts/build_profile.py')
        assert spec is not None and spec.loader is not None
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper

    def test_checked_in_profile_matches_device_and_namespaces(self):
        helper = self.helper()
        with patch.dict(os.environ, {}, clear=True):
            data = helper.load()
        board, subtarget = data['target'].split('/')
        expected = ([f"{data['system']}-airoha-an7581-gemtek_w1700k-ubi-{kind}.itb"
                     for kind in ("squashfs-sysupgrade", "initramfs-installer", "chainload-uboot")]
                    if data['device'] == 'W1700K' else
                    [f"immortalwrt-qualcommax-ipq807x-linksys_mx4200{version}-squashfs-{kind}.bin"
                     for version in ('v1', 'v2') for kind in ('factory', 'sysupgrade')])
        self.assertEqual(data['images'], expected)
        workflow = ROOT / '.github/workflows/W1700K.yaml'
        text = workflow.read_text()
        for prefix in data['cache_prefix'].values():
            self.assertIn(prefix, text)
        self.assertIn(f'CONFIG_TARGET_{board}=y', (ROOT / 'user/default/config.diff').read_text())
        self.assertTrue(all('/' not in name for name in data['images']))

    def test_explicit_repo_fallback_is_not_import_cache_dependent(self):
        helper = self.helper()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            profile = Path(directory)
            data = json.loads((ROOT / 'user/default/build.json').read_text())
            data['device'] = 'MX4200' if data['device'] == 'W1700K' else 'W1700K'
            (profile / 'build.json').write_text(json.dumps(data))
            self.assertEqual(helper.load(profile), data)

    def test_invalid_and_missing_profiles_fail_closed(self):
        helper = self.helper()
        data = json.loads((ROOT / 'user/default/build.json').read_text())
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, DK_PROFILE=directory):
            path = Path(directory) / 'build.json'
            with self.assertRaises(OSError): helper.load()
            for field, value in [('system', 'other'), ('device', 'other'),
                                 ('target', '../outside'), ('images', []),
                                 ('images', [data['images'][0]] * 2),
                                 ('images', ['../outside']), ('cache_prefix', {})]:
                with self.subTest(field=field, value=value):
                    invalid = copy.deepcopy(data)
                    invalid[field] = value
                    path.write_text(json.dumps(invalid))
                    with self.assertRaises((ValueError, KeyError, TypeError)): helper.load()
            path.write_text(json.dumps(data))
            self.assertEqual(helper.load(), data)
