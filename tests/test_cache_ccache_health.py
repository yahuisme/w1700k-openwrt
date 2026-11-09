"""Exact cache health through real archives, restore/pack CLIs and compile shell.

Only make/Docker boundaries are inert; no compiler or restored binary is probed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from test_cache_workflow import ROOT, step, render, render_env


class CcacheHealthTests(unittest.TestCase):
    def fixture(self, root, state):
        for name in ('build_dir/host', 'staging_dir/host/bin',
                     'build_dir/toolchain-test', 'staging_dir/toolchain-test'):
            path = root / name
            path.mkdir(parents=True, exist_ok=True)
            (path / 'sentinel').write_text('fixture')
        for tool in ('ccache', 'cmake'):
            built = root / f'build_dir/host/{tool}-1/.built'
            built.parent.mkdir(parents=True, exist_ok=True)
            built.touch()
            stamp = root / f'staging_dir/host/stamp/.{tool}_installed'
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.touch()
        binary = root / 'staging_dir/host/bin/ccache'
        binary.write_text('#!/bin/sh\nprintf "ccache %s\\n" "$*" >> "$LOG"\n')
        binary.chmod(0o755)
        if state == 'empty':
            binary.write_bytes(b'')
        elif state == 'missing':
            binary.unlink()
        elif state == 'nonexecutable':
            binary.chmod(0o644)
        elif state == 'directory':
            binary.unlink()
            binary.mkdir()
        elif state == 'symlink':
            binary.rename(binary.with_name('real-ccache'))
            binary.symlink_to('real-ccache')

    def test_restore_health_drives_real_compile_bootstrap_and_poison_save_gates(self):
        for tier in ('toolchain', 'bootstrap'):
            for state in ('valid', 'empty', 'missing', 'nonexecutable', 'directory', 'symlink'):
                with self.subTest(tier=tier, state=state), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    producer, root, archive = (base / name for name in ('producer', 'source', 'archive'))
                    root.mkdir(); archive.mkdir()
                    self.fixture(producer, state)
                    roots = ('build_dir/host', 'staging_dir/host')
                    if tier == 'toolchain':
                        roots += ('build_dir/toolchain-test', 'staging_dir/toolchain-test')
                    with tarfile.open(archive / (tier + '.tar.gz'), 'w:gz') as stream:
                        for name in roots:
                            stream.add(producer / name, arcname=name)
                    (archive / 'key').write_text('exact\n')
                    output, calls = base / 'output', base / 'calls'
                    name = 'Extract toolchain cache' if tier == 'toolchain' else 'Extract compiler bootstrap'
                    item = step(name)
                    values = {'steps.tc.outputs.cache-matched-key': 'exact', 'steps.tc.outcome': 'success',
                              'steps.tb.outputs.cache-matched-key': 'exact', 'steps.tb.outcome': 'success',
                              'steps.inputs.outputs.key': 'exact', 'steps.tb_inputs.outputs.key': 'exact'}
                    block = render(item['run'], values).replace('/cache-scripts/cache_recovery.py',
                                                                      str(ROOT / 'scripts/cache_recovery.py'))
                    block = block.replace('/tcarchive', str(archive)).replace('/tbarchive', str(archive))
                    prefix = 'docker_exec() { shift; "$@"; };\n'
                    env = dict(os.environ, DK_OPENWRT=str(root), GITHUB_OUTPUT=str(output),
                               DK_PROFILE='/bld/user/default', LOG=str(calls), **render_env(item, values))
                    restored = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + block],
                                              cwd=base, env=env, capture_output=True, text=True)
                    self.assertEqual(restored.returncode, 0, restored.stderr)
                    fields = dict(line.split('=', 1) for line in output.read_text().splitlines())
                    healthy = state == 'valid'
                    self.assertEqual(fields['hit'], str(healthy).lower(), restored.stderr)
                    self.assertEqual(fields['poisoned'], str(not healthy).lower())
                    self.assertFalse(calls.exists(), 'health checks must not execute restored binaries')
                    if not healthy:
                        self.assertFalse((root / 'build_dir/host').exists())
                        self.assertFalse((root / 'staging_dir/host').exists())
                        self.assertEqual(list(archive.iterdir()), [])
                    values.update({'steps.tc_restore.outputs.hit': fields['hit'] if tier == 'toolchain' else 'false',
                                   'steps.tc_restore.outputs.poisoned': fields['poisoned'] if tier == 'toolchain' else 'false',
                                   'steps.tb_restore.outputs.hit': fields['hit'] if tier == 'bootstrap' else '',
                                   'steps.tb_restore.outputs.poisoned': fields['poisoned'] if tier == 'bootstrap' else ''})
                    compile_item = step('Compile firmware')
                    compile_env = render_env(compile_item, values)
                    if not healthy:
                        # The rejected immutable tier cannot be packed/admitted/saved.
                        gate = step('tc_budget' if tier == 'toolchain' else 'tb_budget')['if']
                        import re
                        gate = re.sub(r"hashFiles\('[^']+'\)", "'present'", gate)
                        gate = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), gate)
                        # Trusted checked-in YAML with repr-quoted local values only.
                        self.assertFalse(eval(gate.replace('&&', ' and '), {'__builtins__': {}}))
                    # Isolate only snapshot packing: compile must run its real bootstrap decision.
                    compile_env['BOOTSTRAP_SAVE'] = 'false'
                    stub = base / 'healthy-ccache'
                    stub.write_text('#!/bin/sh\nprintf "ccache %s\\n" "$*" >> "$LOG"\n')
                    stub.chmod(0o755)
                    boundary = '''docker_exec() { shift; "$@"; }
make() {
 printf 'make %s\\n' "$*" >> "$LOG"
 if [ "$1" = tools/ccache/compile ]; then
  mkdir -p staging_dir/host/bin
  cp "$STUB" staging_dir/host/bin/ccache
 fi
}
nproc() { printf '1\\n'; }
export -f docker_exec make nproc
'''
                    compiled = subprocess.run(['bash', '-eo', 'pipefail', '-c', boundary + compile_item['run']],
                        cwd=base, env=dict(env, **compile_env, STUB=str(stub)), capture_output=True, text=True)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    actual = calls.read_text().splitlines()
                    bootstrap = tier == 'bootstrap' or not healthy
                    self.assertEqual(actual, (['make tools/ccache/compile -j2'] if bootstrap else []) +
                                     ['ccache -d /ghcache --zero-stats', 'make -j2', 'ccache -d /ghcache -sz'])

    def test_pack_rejects_unhealthy_ccache_without_upload_candidate(self):
        for tier in ('toolchain', 'bootstrap'):
            for state in ('valid', 'empty', 'missing', 'nonexecutable', 'directory', 'symlink'):
                with self.subTest(tier=tier, state=state), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp); root, archive = base / 'source', base / 'archive'
                    self.fixture(root, state)
                    script, mode = ('cache.py', 'toolchain') if tier == 'toolchain' else ('bootstrap_cache.py', 'pack')
                    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), mode,
                                             str(root), str(archive), 'exact'],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, state == 'valid', result.stdout + result.stderr)
                    self.assertEqual((archive / (tier + '.tar.gz')).exists(), state == 'valid')
                    self.assertEqual((archive / 'key').exists(), state == 'valid')


if __name__ == '__main__':
    unittest.main()
