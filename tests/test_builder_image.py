"""Production builder shell failure boundaries; no Docker or compilation required."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
STEPS = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())['jobs']['build']['steps']
BLOCK = next(s['run'] for s in STEPS if s.get('name') == 'Start build container')
BLOCK = BLOCK[BLOCK.index('IMAGE='):BLOCK.index('install -m 755')]
IMAGE_ID = 'sha256:' + 'b' * 64
FINGERPRINT = 'c' * 64
spec = importlib.util.spec_from_file_location('builder', ROOT / 'scripts/builder_fingerprint.py')
assert spec is not None and spec.loader is not None
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuilderImageTests(unittest.TestCase):
    def test_selection_and_failure_boundaries(self):
        for phase in ('', 'build', 'image', 'bad_id', 'run', 'exec', 'bad_fingerprint'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                env = dict(os.environ, LOG=str(base / 'calls'), GITHUB_ENV=str(base / 'env'),
                           FAIL=phase, EXPECTED_ID=IMAGE_ID, FP=FINGERPRINT,
                           DK_USER='/bld/user', DK_BIN='/bld/openwrt_bin')
                stub = '''
                docker() {
                  printf '%s\\n' "$*" >> "$LOG"
                  [ "$1" != "$FAIL" ] || return 19
                  case "$1" in
                    build) [ "${@: -1}" = docker ];;
                    image) if [ "$FAIL" = bad_id ]; then echo bad; else echo "$EXPECTED_ID"; fi;;
                    run) [ "${*: -3}" = "$EXPECTED_ID sleep infinity" ];;
                    exec) if [ "$FAIL" = bad_fingerprint ]; then echo bad; else echo "$FP"; fi;;
                    *) return 99;;
                  esac
                }
                '''
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', stub + BLOCK],
                                        env=env, capture_output=True, text=True)
                calls = (base / 'calls').read_text()
                self.assertEqual(result.returncode == 0, not phase, result.stderr)
                if not phase:
                    self.assertIn('build --platform linux/arm64 -t w1700k-builder:local docker', calls)
                    self.assertIn(IMAGE_ID + ' sleep infinity', calls)
                    self.assertIn('run -d --name DK', calls)
                    self.assertNotIn('run -dt', calls)
                    self.assertEqual((base / 'env').read_text(),
                                     f'IMAGE_ID={IMAGE_ID}\nBUILDER_FINGERPRINT={FINGERPRINT}\n')
                elif phase in ('build', 'image', 'bad_id'):
                    self.assertNotIn('run -d', calls)
                else:
                    self.assertNotIn('BUILDER_FINGERPRINT=', (base / 'env').read_text())

    def test_exact_key_and_recipe(self):
        inputs = next(s['run'] for s in STEPS if s.get('id') == 'inputs')
        self.assertIn('/tcarchive "$BUILDER_FINGERPRINT"', inputs)
        self.assertNotIn('restore-keys', next(s for s in STEPS if s.get('id') == 'tc')['with'])
        recipe = (ROOT / 'docker/Dockerfile').read_text()
        self.assertIn('debian:trixie-slim@sha256:da496358bd6934d2bd6a563a33176a2e50eff5490c54b4ac6fb051b69fef4071', recipe)
        self.assertIn('ARG GO_VERSION=1.26.8', recipe)
        self.assertIn('sha256sum -c -', recipe)

    def test_llvm_guard_after_defconfig(self):
        inputs = next(s['run'] for s in STEPS if s.get('id') == 'inputs')
        block = inputs[inputs.index('make defconfig'):inputs.index('make download') + len('make download -j8 || exit 1')]
        stub = 'make() { if [ "$1" = defconfig ]; then printf "%s\\n" "$CONFIG" > .config; else touch downloaded; fi; };\n'
        for config, allowed in (('CONFIG_USE_LLVM_HOST=y', False),
                                ('CONFIG_BPF_TOOLCHAIN_BUILD_LLVM=y', True),
                                ('# CONFIG_USE_LLVM is not set', True)):
            with self.subTest(config=config), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(['bash', '-e', '-c', stub + block], cwd=tmp,
                                        env=dict(os.environ, CONFIG=config), capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
                self.assertEqual((Path(tmp) / 'downloaded').exists(), allowed)
                if not allowed:
                    self.assertIn('Host LLVM selected', result.stderr)

    def test_invalid_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp)
            recipe = context / 'Dockerfile'
            with self.assertRaisesRegex(ValueError, 'missing Dockerfile'):
                builder.fingerprint(context)
            recipe.write_text('recipe')
            with patch.object(builder.subprocess, 'check_output', return_value=''):
                with self.assertRaisesRegex(ValueError, 'empty installed'):
                    builder.fingerprint(context)
            with patch.object(builder.subprocess, 'check_output', side_effect=subprocess.CalledProcessError(1, 'dpkg-query')):
                with self.assertRaises(subprocess.CalledProcessError):
                    builder.fingerprint(context)
            recipe.unlink()
            target = context / 'real-recipe'
            target.write_text('recipe')
            recipe.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'linked Docker input'):
                builder.fingerprint(context)

    def test_implementation_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp)
            (context / 'Dockerfile').write_text('recipe')
            implementation = context / 'fingerprint.py'
            implementation.write_bytes((ROOT / 'scripts/builder_fingerprint.py').read_bytes())
            with patch.object(builder.subprocess, 'check_output', return_value='a\tarm64\t1\n'), patch.object(builder, '__file__', str(implementation)):
                before = builder.fingerprint(context)
                implementation.write_bytes(implementation.read_bytes() + b'\n# changed implementation\n')
                self.assertNotEqual(before, builder.fingerprint(context))

    def test_non_inputs_do_not_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp)
            (context / 'Dockerfile').write_text('controlled recipe')
            with patch.object(builder.subprocess, 'check_output', return_value='a\tarm64\t1\n'):
                before = builder.fingerprint(context)
                for name in ('README.md', 'smoke.sh', '.dockerignore'):
                    (context / name).write_text('not consumed by current Dockerfile')
                self.assertEqual(before, builder.fingerprint(context))

    def test_fingerprint_content_packages_architecture_not_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp)
            recipe = context / 'Dockerfile'
            recipe.write_text('controlled base and Go checksum')
            with patch.object(builder.subprocess, 'check_output', return_value='z\tarm64\t1\na\tall\t2\n') as query:
                before = builder.fingerprint(context)
                self.assertEqual(before, builder.fingerprint(context))
                query.assert_called_with(['dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\n'], text=True)
                os.utime(recipe, (1, 1))
                self.assertEqual(before, builder.fingerprint(context))
                query.return_value = 'a\tall\t2\nz\tarm64\t1\n'
                self.assertEqual(before, builder.fingerprint(context))
                for manifest in ('a\tall\t3\nz\tarm64\t1\n', 'a\tarm64\t2\nz\tarm64\t1\n'):
                    query.return_value = manifest
                    self.assertNotEqual(before, builder.fingerprint(context))
                query.return_value = 'a\tall\t2\nz\tarm64\t1\n'
                with patch.object(builder.platform, 'machine', return_value='other-architecture'):
                    self.assertNotEqual(before, builder.fingerprint(context))
                recipe.write_text('changed base or Go checksum')
                self.assertNotEqual(before, builder.fingerprint(context))
                recipe.unlink()
                recipe.symlink_to(context / 'missing')
                with self.assertRaises(ValueError):
                    builder.fingerprint(context)


if __name__ == '__main__':
    unittest.main()
