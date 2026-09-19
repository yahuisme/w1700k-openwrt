"""Execute the production image-selection shell with local Docker stubs."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())['jobs']['build']['steps']
BLOCK = next(s['run'] for s in STEPS if s.get('name') == 'Start build container')
BLOCK = BLOCK[BLOCK.index('IMAGE='):BLOCK.index('install -m 755')]
DIGEST = 'sha256:' + 'a' * 64
IMAGE_ID = 'sha256:' + 'b' * 64
ARM = {'platform': {'os': 'linux', 'architecture': 'arm64'}, 'digest': DIGEST}


class BuilderImageTests(unittest.TestCase):
    def test_selection_and_failure_boundaries(self):
        for case, manifests, phase, success in (
            ('valid', [ARM, {'platform': {'os': 'unknown', 'architecture': 'unknown'}, 'digest': 'attestation'}], '', True),
            ('absent', [], '', False),
            ('ambiguous', [ARM, ARM], '', False),
            ('bad_digest', [dict(ARM, digest='sha256:bad')], '', False),
            ('index_failure', [ARM], 'buildx', False),
            ('pull_failure', [ARM], 'pull', False),
            ('inspect_failure', [ARM], 'image', False),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / 'index').write_text(json.dumps({'manifests': manifests}))
                env = dict(os.environ, INDEX=str(base / 'index'), LOG=str(base / 'calls'),
                           GITHUB_ENV=str(base / 'env'), FAIL=phase, EXPECTED_ID=IMAGE_ID)
                stub = '''
                docker() {
                  printf '%s\\n' "$*" >> "$LOG"
                  [ "$1" != "$FAIL" ] || return 19
                  case "$1" in
                    buildx) cat "$INDEX";;
                    pull) :;;
                    image) printf '%s\\n' "$EXPECTED_ID";;
                    run) [ "${@: -1}" = "$EXPECTED_ID" ];;
                    *) return 99;;
                  esac
                }
                '''
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', stub + BLOCK],
                                        env=env, capture_output=True, text=True)
                calls = (base / 'calls').read_text()
                self.assertEqual(result.returncode == 0, success, result.stderr)
                if success:
                    self.assertIn('pull ghcr.io/w1700k/fastbuild_base@' + DIGEST, calls)
                    self.assertEqual((base / 'env').read_text(), 'IMAGE_ID=' + IMAGE_ID + '\n')
                    self.assertTrue(calls.rstrip().endswith(IMAGE_ID))
                else:
                    self.assertNotIn('run -dt', calls)

    def test_live_tag_and_exact_cache_preserved(self):
        self.assertIn('IMAGE=ghcr.io/w1700k/fastbuild_base:debian-arm', BLOCK)
        inputs = next(s['run'] for s in STEPS if s.get('id') == 'inputs')
        self.assertIn('/tcarchive "$IMAGE_ID"', inputs)
        restore = next(s for s in STEPS if s.get('id') == 'tc')
        self.assertNotIn('restore-keys', restore['with'])


if __name__ == '__main__':
    unittest.main()
