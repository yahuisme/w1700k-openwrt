"""Recovery exercises native tar and production CLIs, never firmware compilation."""
import gzip
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zlib
from workflow_fixture import build_job

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts/cache_recovery.py'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'root'
        self.archive = self.base / 'archive'
        self.root.mkdir()
        self.archive.mkdir()

    def cli(self, kind, restored='matched', outcome='success', expected='matched'):
        return subprocess.run([sys.executable, str(SCRIPT), 'restore', kind,
                               str(self.root), str(self.archive), expected,
                               '--restored', restored, '--outcome', outcome],
                              text=True, capture_output=True)

    def test_exact_rejected_and_missing_archives_are_effective_misses(self):
        for kind in ('toolchain', 'bootstrap'):
            for failure in ('truncated', 'key', 'missing', 'action'):
                with self.subTest(kind=kind, failure=failure):
                    for name in ('build_dir/host', 'staging_dir/host'):
                        p = self.root / name
                        p.mkdir(parents=True, exist_ok=True)
                        (p / 'stale').write_text('old')
                    self.truncated(kind)
                    (self.archive / 'key').write_text('wrong\n' if failure == 'key' else 'matched\n')
                    if failure == 'missing':
                        (self.archive / (kind + '.tar.gz')).unlink()
                    result = self.cli(kind, outcome='failure' if failure == 'action' else 'success')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('hit=false\n', result.stdout)
                    self.assertIn('poisoned=true\n', result.stdout)
                    self.assertFalse((self.root / 'build_dir/host').exists())
                    self.assertFalse((self.root / 'staging_dir/host').exists())
                    self.assertEqual(list(self.archive.iterdir()), [])

    def test_exact_valid_archives_report_healthy_and_miss_cannot_reuse_leftovers(self):
        for kind in ('toolchain', 'bootstrap'):
            with self.subTest(kind=kind):
                for tool in ('ccache', 'cmake'):
                    p = self.root / 'build_dir/host' / (tool + '-1')
                    p.mkdir(parents=True, exist_ok=True)
                    (p / '.built').touch()
                    p = self.root / 'staging_dir/host/stamp' / ('.' + tool + '_installed')
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.touch()
                exe = self.root / 'staging_dir/host/bin/ccache'
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.write_text('#!/bin/sh\nexit 0\n')
                exe.chmod(0o755)
                for name in ('build_dir/toolchain-test', 'staging_dir/toolchain-test'):
                    (self.root / name).mkdir(parents=True, exist_ok=True)
                    (self.root / name / 'keep').write_text('toolchain')
                script = 'cache.py' if kind == 'toolchain' else 'bootstrap_cache.py'
                mode = 'toolchain' if kind == 'toolchain' else 'pack'
                packed = subprocess.run([sys.executable, str(REPO / 'scripts' / script), mode,
                                         str(self.root), str(self.archive), 'matched'], capture_output=True, text=True)
                self.assertEqual(packed.returncode, 0, packed.stderr)
                result = self.cli(kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('hit=true\n', result.stdout)
                self.assertIn('poisoned=false\n', result.stdout)
                self.assertTrue((self.root / 'staging_dir/toolchain-test/keep').exists())
                result = self.cli(kind, restored='')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('hit=false\n', result.stdout)
                self.assertFalse((self.root / 'staging_dir/host').exists())

    def test_workflow_consumers_use_health_not_raw_action_hits(self):
        steps = build_job()['steps']
        by_id = {s['id']: s for s in steps if 'id' in s}
        for tier in ('gh', 'dl', 'tc', 'tb'):
            self.assertTrue(by_id[tier].get('continue-on-error'), tier)
        for name in ('Extract compiler cache', 'Extract download cache', 'Extract toolchain cache', 'Extract compiler bootstrap'):
            step = next(s for s in steps if s['name'] == name)
            self.assertIn('cache_recovery.py restore', step['run'])
        self.assertIn('steps.tc_restore.outputs.hit', by_id['tb_inputs']['if'])
        compile_step = next(s for s in steps if s['name'] == 'Compile firmware')
        self.assertIn('steps.tc_restore.outputs.hit', compile_step['env']['BOOTSTRAP_RECHECK'])
        self.assertIn('steps.tb_restore.outputs.hit', compile_step['env']['BOOTSTRAP_SAVE'])
        self.assertIn('steps.tb_restore.outputs.poisoned', compile_step['env']['BOOTSTRAP_SAVE'])
        self.assertIn('steps.tc_restore.outputs.poisoned', by_id['tc_budget']['if'])
        self.assertIn('steps.tb_restore.outputs.poisoned', by_id['tb_budget']['if'])
        self.assertFalse(any('invalidate' in s.get('run', '') for s in steps))

    def test_poisoned_exact_keys_deny_production_pack_and_save(self):
        from test_cache_workflow import step, render, render_env
        values = {'steps.tc_restore.outputs.hit': 'false', 'steps.tb_restore.outputs.hit': 'false',
                  'steps.tc_restore.outputs.poisoned': 'true', 'steps.tb_restore.outputs.poisoned': 'true',
                  'steps.tb_inputs.outputs.key': 'tb-fixture'}
        self.assertEqual(render_env(step('Compile firmware'), values)['BOOTSTRAP_SAVE'], 'false')
        block = render(step('Prepare build caches')['run'], values)
        block = block.split('python3 scripts/cache_helper.py admit', 1)[0]
        result = subprocess.run(['bash', '-e', '-c',
                                 'docker_exec() { printf "%s\\n" "$*"; }; sudo() { :; };\n' + block],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('cache.py toolchain', result.stdout)
        for tier in ('tc', 'tb'):
            condition = step(tier + '_budget')['if']
            import re
            condition = re.sub(r"hashFiles\('[^']+'\)", "'present'", condition)
            condition = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), condition)
            # Trusted local YAML comparisons with repr-quoted fixture values only.
            self.assertFalse(eval(condition.replace('&&', ' and '), {'__builtins__': {}}))

    def test_production_unpack_blocks_emit_only_effective_outputs(self):
        from test_cache_workflow import render, render_env
        steps = build_job()['steps']
        for kind, name in (('ccache', 'Extract compiler cache'), ('dl', 'Extract download cache'),
                           ('toolchain', 'Extract toolchain cache'), ('bootstrap', 'Extract compiler bootstrap')):
            with self.subTest(kind=kind):
                destination = {'ccache': 'ghcache', 'dl': 'dlcache', 'toolchain': 'source', 'bootstrap': 'source'}[kind]
                cachedir = {'ccache': 'ccarchive', 'dl': 'dlarchive', 'toolchain': 'tcarchive', 'bootstrap': 'tbarchive'}[kind]
                root = self.base / destination
                root.mkdir(exist_ok=True)
                self.truncated(kind).replace(self.base / (kind + '.tar.gz'))
                archive = self.base / cachedir
                archive.mkdir(exist_ok=True)
                (self.base / (kind + '.tar.gz')).replace(archive / (kind + '.tar.gz'))
                (archive / 'key').write_text('matched\n')
                output = self.base / 'output'
                output.unlink(missing_ok=True)
                values = {f'steps.{tier}.outputs.cache-matched-key': 'matched' for tier in ('gh', 'dl', 'tc', 'tb')}
                values.update({f'steps.{tier}.outcome': 'success' for tier in ('gh', 'dl', 'tc', 'tb')})
                values.update({'steps.inputs.outputs.key': 'matched', 'steps.tb_inputs.outputs.key': 'matched'})
                item = next(s for s in steps if s['name'] == name)
                block = render(item['run'], values).replace('/cache-scripts/cache_recovery.py', str(SCRIPT))
                block = block.replace('python3 scripts/cache_recovery.py', 'python3 ' + str(SCRIPT))
                block = block.replace('/' + cachedir, str(archive))
                # Only relocate container/checkout paths; execute the real CLI/tar.
                prefix = 'docker_exec() { shift; "$@"; };\n'
                env = dict(os.environ, **render_env(item, values), DK_OPENWRT=str(root),
                           DK_PROFILE='/bld/user/default', GITHUB_OUTPUT=str(output))
                result = subprocess.run(['bash', '-e', '-c', prefix + block], cwd=self.base,
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                fields = dict(line.split('=', 1) for line in output.read_text().splitlines())
                self.assertEqual(fields['hit'], 'false')
                self.assertEqual(fields['matched-key'], '')

    def test_cold_cleanup_preserves_archive_mount_directory(self):
        for kind in ('toolchain', 'bootstrap'):
            with self.subTest(kind=kind):
                self.truncated(kind)
                (self.archive / 'key').write_text('matched\n')
                fd = os.open(self.archive, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    result = self.cli(kind)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    # Container tcarchive/tbarchive are bind mounts; unlinking
                    # their directory fails with EBUSY even after files vanish.
                    self.assertGreater(os.fstat(fd).st_nlink, 0)
                    self.assertEqual(list(self.archive.iterdir()), [])
                finally:
                    os.close(fd)

    def test_toolchain_incomplete_archive_cannot_claim_health(self):
        (self.archive / 'key').write_text('matched\n')
        with tarfile.open(self.archive / 'toolchain.tar.gz', 'w:gz') as tf:
            entry = tarfile.TarInfo('build_dir/host/sentinel')
            entry.size = 7
            tf.addfile(entry, io.BytesIO(b'partial'))
        result = self.cli('toolchain')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('hit=false\n', result.stdout)
        self.assertFalse((self.root / 'build_dir').exists())

    def test_container_script_import_uses_mounted_profile(self):
        import shutil
        scripts = self.base / 'cache-scripts'
        shutil.copytree(REPO / 'scripts', scripts)
        profile = self.base / 'mounted-profile'
        shutil.copytree(REPO / 'user/default', profile)
        result = subprocess.run([sys.executable, str(scripts / 'cache_recovery.py'),
                                 'restore', 'toolchain', str(self.root), str(self.archive),
                                 'matched'], env=dict(os.environ, DK_PROFILE=str(profile)),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dict(line.split('=', 1) for line in result.stdout.splitlines())['hit'], 'false')

    def test_unknown_and_cleanup_errors_still_fail_closed(self):
        import importlib.util
        from unittest.mock import patch
        sys.path.insert(0, str(REPO / 'scripts'))
        self.addCleanup(lambda: sys.path.remove(str(REPO / 'scripts')))
        spec = importlib.util.spec_from_file_location('recovery', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.truncated('toolchain')
        (self.archive / 'key').write_text('matched\n')
        with patch.object(module.toolchain, 'restore', side_effect=RuntimeError('bug')):
            with self.assertRaisesRegex(RuntimeError, 'bug'):
                module.restore('toolchain', self.root, self.archive, 'matched', 'matched', 'success')
        with patch.object(module.toolchain, 'restore', side_effect=OSError('unexpected')):
            with self.assertRaises(OSError):
                module.restore('toolchain', self.root, self.archive, 'matched', 'matched', 'success')
        with patch.object(module, 'clear_restored', side_effect=PermissionError('cleanup')):
            with self.assertRaises(PermissionError):
                module.restore('toolchain', self.root, self.archive, 'matched', 'matched', 'success')

    def test_invalid_gzip_and_missing_key_are_cold(self):
        for kind in ('ccache', 'dl', 'toolchain', 'bootstrap'):
            with self.subTest(kind=kind):
                (self.archive / (kind + '.tar.gz')).write_bytes(b'not gzip')
                result = self.cli(kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('hit=false\n', result.stdout)
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_tc_partial_tar_really_extracts_sentinel_before_failure(self):
        archive = self.truncated('toolchain')
        raw = self.base / 'native-extract'
        raw.mkdir()
        result = subprocess.run(['tar', '--gzip', '-xf', str(archive), '-C', str(raw)], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((raw / 'build_dir/host/sentinel').read_bytes(), b'partial')
        (self.archive / 'key').write_text('matched\n')
        result = self.cli('toolchain')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'build_dir').exists())

    def test_corrupt_bootstrap_deflate_stream_is_cold(self):
        (self.archive / 'key').write_text('matched\n')
        (self.archive / 'bootstrap.tar.gz').write_bytes(bytes.fromhex('1f8b0800000000000003') + b'\xff' * 100)
        result = self.cli('bootstrap')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('hit=false\n', result.stdout)

    def test_late_corrupt_bootstrap_deflate_stream_is_cold(self):
        (self.archive / 'key').write_text('matched\n')
        entry = tarfile.TarInfo('build_dir/host/large')
        entry.size = 200000
        # Stored DEFLATE blocks keep corruption beyond gzip's initial read-ahead.
        # SYNC_FLUSH ends on a byte boundary; 0x07 starts an invalid BTYPE=3 block.
        compressor = zlib.compressobj(level=0, wbits=31)
        good = compressor.compress(entry.tobuf() + b'x' * 50000)
        good += compressor.flush(zlib.Z_SYNC_FLUSH)
        archive = self.archive / 'bootstrap.tar.gz'
        archive.write_bytes(good + b'\x07')
        with tarfile.open(archive, 'r:gz') as tf:
            self.assertEqual(next(iter(tf)).name, entry.name)
            with self.assertRaisesRegex(zlib.error, 'invalid block type'):
                tf.next()
        for name in ('build_dir/host', 'staging_dir/host'):
            stale = self.root / name / 'stale'
            stale.parent.mkdir(parents=True)
            stale.write_text('old')
        result = self.cli('bootstrap')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
        self.assertIn('invalid block type', result.stderr)
        self.assertFalse((self.root / 'build_dir/host').exists())
        self.assertFalse((self.root / 'staging_dir/host').exists())
        self.assertEqual(list(self.archive.iterdir()), [])

    def truncated(self, kind):
        # A complete first member is extracted BEFORE the second member fails.
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w') as tf:
            prefix = 'build_dir/host/' if kind in ('toolchain', 'bootstrap') else ''
            for name, data in [(prefix + 'sentinel', b'partial'), (prefix + 'large', os.urandom(200000))]:
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tf.addfile(entry, io.BytesIO(data))
        raw = payload.getvalue()[:50000]
        path = self.archive / (kind + '.tar.gz')
        path.write_bytes(gzip.compress(raw))
        return path

    def test_rolling_partial_extraction_is_removed_and_reported_cold(self):
        for kind in ('ccache', 'dl'):
            with self.subTest(kind=kind):
                archive = self.truncated(kind)
                (self.root / 'stale').write_text('old')
                result = self.cli(kind)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('hit=false\n', result.stdout)
                self.assertIn('matched-key=\n', result.stdout)
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertFalse(archive.exists())


if __name__ == '__main__':
    unittest.main()
