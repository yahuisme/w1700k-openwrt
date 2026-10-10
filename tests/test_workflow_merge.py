"""Execute both complete merged steps; no Docker, network or host writes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import STEPS, step, render


ENV_STUB = r'''
record() { printf '%s\n' "$1" >> "$LOG"; [ "$FAIL" != "$1" ]; }
tar() { record "extract:$3"; }
sudo() {
    case "$1" in
        python3) record snapshot;;
        tee) record daemon; command cat >/dev/null;;
        systemctl) record reload;;
        *) return 99;;
    esac
}
docker() {
    record "$1" || return 19
    case "$1" in
        image) printf 'sha256:%064d\n' 1;;
        exec) printf '%064d\n' 2;;
        run) [[ "${*: -3}" = "sha256:$(printf '%064d' 1) sleep infinity" ]];;
        build) :;;
        *) return 99;;
    esac
}
install() { record install; command cat > "$RUNNER_TEMP/docker_exec"; }
'''
CACHE_STUB = r'''
record() { printf '%s\n' "$1" >> "$LOG"; [ "$FAIL" != "$1" ]; }
docker_exec() { record "$4"; }
sudo() { [ "$1" = chown ]; record chown; }
python3() {
    record admit
    [ "$1" = scripts/cache_helper.py ] && [ "$2" = admit ]
    [ "$3" = cc-v3-ubi2. ] && [ "$4" = ccarchive/ccache.tar.gz ]
    [ "$5" = cc-v3-ubi2.new ]
    printf 'save=%s\n' "$ADMIT" >> "$GITHUB_OUTPUT"
}
'''


class WorkflowMergeTests(unittest.TestCase):
    def test_step_boundaries_and_failure_policy(self):
        self.assertEqual(len(STEPS), 22)
        for name in ('Prepare build environment', 'Prepare build caches'):
            merged = step(name)
            self.assertNotIn('if', merged)
            self.assertFalse(merged.get('continue-on-error', False))
        self.assertEqual(step('Prepare build caches')['id'], 'cc_budget')
        self.assertEqual(STEPS.index(step('Prepare build caches')) + 1,
                         STEPS.index(step('Save compiler cache')))
        for name in ('Compile firmware', 'Validate and stage firmware',
                     'Publish firmware and prune releases'):
            self.assertIn(step(name), STEPS)

    def test_complete_environment_success_and_early_failures(self):
        expected = ['extract:ccarchive/ccache.tar.gz', 'extract:dlarchive/dl.tar.gz',
                    'snapshot', 'daemon', 'reload', 'build', 'image', 'run', 'exec', 'install']
        for fail in ['', *expected, 'missing-config']:
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for name in ('ccarchive/ccache.tar.gz', 'dlarchive/dl.tar.gz',
                             'user/default/config.diff'):
                    p = base / name
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.touch()
                if fail == 'missing-config':
                    (base / 'user/default/config.diff').unlink()
                env = dict(os.environ, FAIL=fail, LOG=str(base/'calls'), RUNNER_TEMP=tmp,
                           GITHUB_ENV=str(base/'env'), DK_USER='/bld/user', DK_BIN='/bld/bin')
                env.pop('IMAGE_ID', None)
                env.pop('BUILDER_FINGERPRINT', None)
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c',
                                         ENV_STUB + step('Prepare build environment')['run']],
                                        cwd=base, env=env, text=True, capture_output=True)
                calls = (base/'calls').read_text().splitlines()
                want = expected if not fail else expected[:3] if fail == 'missing-config' else expected[:expected.index(fail)+1]
                self.assertEqual(calls, want, result.stderr)
                self.assertEqual(result.returncode == 0, not fail, result.stderr)
                if not fail:
                    self.assertEqual((base/'env').read_text(),
                                     f'IMAGE_ID=sha256:{1:064d}\nBUILDER_FINGERPRINT={2:064d}\n')
                    self.assertIn('exec docker exec', (base/'docker_exec').read_text())

    def test_complete_cache_success_denial_and_early_failures(self):
        for warm in (False, True):
            for changed in (False, True):
                expected = ['ccache'] + ([] if warm else ['toolchain']) + (['dl'] if changed else []) + ['chown', 'admit']
                for fail, admit in [('', 'true'), ('', 'false')] + [(p, 'true') for p in expected]:
                    with self.subTest(warm=warm, changed=changed, fail=fail, admit=admit), tempfile.TemporaryDirectory() as tmp:
                        base = Path(tmp)
                        values = {'steps.tc.outputs.cache-hit': str(warm).lower(),
                                  'steps.dl_changed.outputs.save': str(changed).lower(),
                                  'steps.inputs.outputs.key': 'tc-v3-ubi2-new',
                                  'steps.gh.outputs.cache-primary-key': 'cc-v3-ubi2.new'}
                        result = subprocess.run(['bash', '-eo', 'pipefail', '-c', CACHE_STUB + render(step('cc_budget')['run'], values)],
                                                cwd=base, env=dict(os.environ, FAIL=fail, ADMIT=admit,
                                                DK_OPENWRT='/build', LOG=str(base/'calls'), GITHUB_OUTPUT=str(base/'output')),
                                                text=True, capture_output=True)
                        self.assertEqual(result.returncode == 0, not fail, result.stderr)
                        self.assertEqual((base/'calls').read_text().splitlines(), expected if not fail else expected[:expected.index(fail)+1])
                        self.assertEqual((base/'output').exists(), not fail)
                        if not fail:
                            self.assertEqual((base/'output').read_text(), f'save={admit}\n')
