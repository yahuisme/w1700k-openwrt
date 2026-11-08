"""Execute the production compile block; no compiler or Docker invocation."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from test_cache_workflow import render_env

ROOT = Path(__file__).resolve().parents[1]


class BuildTimingTests(unittest.TestCase):
    def test_timing_covers_bootstrap_world_and_failures(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())
        block = next(s['run'] for s in workflow['jobs']['build']['steps']
                     if s.get('name') == 'Compile firmware')
        for hot, pre, main, fallback, stats in (
                (False, 0, 0, 0, 0), (True, 0, 0, 0, 0),
                (False, 17, 0, 0, 0), (False, 0, 7, 0, 0),
                (True, 0, 7, 23, 31), (True, 0, 0, 0, 31)):
            with self.subTest(hot=hot, pre=pre, main=main, fallback=fallback, stats=stats), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cc = root / 'staging_dir/host/bin/ccache'
                cc.parent.mkdir(parents=True)
                stub = root / 'ccache-stub'
                stub.write_text('#!/bin/bash\n[[ "$*" != *-sz ]] || exit "$STATS"\n')
                stub.chmod(0o755)
                if hot:
                    cc.write_bytes(stub.read_bytes())
                    cc.chmod(0o755)
                env = dict(os.environ, DK_OPENWRT=tmp, PRE=str(pre), MAIN=str(main),
                           FALLBACK=str(fallback), STATS=str(stats), STUB=str(stub),
                           **render_env(next(s for s in workflow['jobs']['build']['steps']
                                             if s.get('name') == 'Compile firmware'), {
                               'steps.tc_restore.outputs.hit': 'true' if hot else 'false',
                               'steps.tb_restore.outputs.hit': 'true',
                               'steps.tb_inputs.outputs.key': 'tb-fixture'}))
                prefix = '''
                docker_exec() { shift; "$@"; }
                nproc() { printf '4\n'; }
                make() {
                  if [[ "$*" == tools/ccache/compile* ]]; then
                    [ "$PRE" = 0 ] || return "$PRE"
                    cp "$STUB" staging_dir/host/bin/ccache
                    return 0
                  fi
                  if [[ "$1" == -j1 ]]; then return "$FALLBACK"; fi
                  return "$MAIN"
                }
                export -f docker_exec make nproc
                '''
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + block],
                                        env=env, text=True, capture_output=True)
                expected = pre or (fallback if main else 0)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertRegex(result.stdout, rf'Build timing: bootstrap=[0-9]+s status={pre}')
                if pre:
                    self.assertNotIn('Build timing: world=', result.stdout)
                else:
                    self.assertRegex(result.stdout, rf'Build timing: world=[0-9]+s status={expected}')


if __name__ == '__main__':
    unittest.main()
