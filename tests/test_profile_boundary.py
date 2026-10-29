"""Runner and container profile paths must not cross the execution boundary."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ProfileBoundaryTests(unittest.TestCase):
    def loader(self):
        spec = importlib.util.spec_from_file_location('boundary_profile', ROOT / 'scripts/build_profile.py')
        assert spec is not None and spec.loader is not None
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper

    def test_explicit_runner_path_ignores_container_environment(self):
        expected = json.loads((ROOT / 'user/default/build.json').read_text())
        with patch.dict(os.environ, DK_PROFILE='/bld/user/default'):
            self.assertEqual(self.loader().load(ROOT / 'user/default'), expected)

    def test_explicit_path_is_not_replaced_by_another_valid_profile(self):
        expected = json.loads((ROOT / 'user/default/build.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            other = dict(expected, device='MX4200' if expected['device'] == 'W1700K' else 'W1700K')
            (Path(directory) / 'build.json').write_text(json.dumps(other))
            with patch.dict(os.environ, DK_PROFILE=directory):
                self.assertEqual(self.loader().load(ROOT / 'user/default'), expected)
                self.assertEqual(self.loader().load(), other)

    def test_container_only_mount_is_used_when_checkout_is_absent(self):
        helper = self.loader()
        expected = json.loads((ROOT / 'user/default/build.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            mount = Path(directory) / 'mounted-profile'
            mount.mkdir()
            (mount / 'build.json').write_text(json.dumps(expected))
            absent = Path(directory) / 'container-user/default'
            with patch.dict(os.environ, DK_PROFILE=str(mount)):
                self.assertEqual(helper.load(absent), expected)

    def test_missing_mount_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, DK_PROFILE=str(Path(directory) / 'missing-mount')):
                with self.assertRaises(FileNotFoundError):
                    self.loader().load(Path(directory) / 'missing-checkout')

    def test_runner_cache_helper_imports_with_workflow_environment(self):
        code = "import runpy; m=runpy.run_path('scripts/cache_helper.py',run_name='boundary'); print(sorted(m['SLOTS']))"
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                env=dict(os.environ, DK_PROFILE='/bld/user/default'),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for prefix in json.loads((ROOT / 'user/default/build.json').read_text())['cache_prefix'].values():
            self.assertIn(prefix, result.stdout)

    def test_runner_verifier_reaches_asset_readback(self):
        code = '''import importlib.util,json,os,tempfile
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('verify', 'scripts/verify_release.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
profile=json.loads(Path('user/default/build.json').read_text())
with tempfile.TemporaryDirectory() as directory:
 paths=[Path(directory)/name for name in profile['images']]
 for p in paths: p.write_bytes(b'fixture image')
 with patch.object(m.subprocess,'check_output',side_effect=RuntimeError('asset-readback-reached')):
  try: m.verify('fixture-tag',paths)
  except RuntimeError as exc: assert str(exc)=='asset-readback-reached'
  else: raise AssertionError('asset readback not reached')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                env=dict(os.environ, DK_PROFILE='/bld/user/default', GITHUB_REPOSITORY='fixture/repo', GITHUB_SHA='a' * 40),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
