"""Download after exact restores: real YAML shells, no Docker or compilation."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import ROOT, STEPS, step, render, render_env


PREFIX = r'''
umask 077
docker_exec() {
    shift
    if [ "$1" = python3 ]; then
        case "$2:$3:$4" in
            */cache_recovery.py:restore:toolchain)
                printf 'restore-tc\n' >> "$LOG"
                rm -rf "$DK_OPENWRT/build_dir" "$DK_OPENWRT/staging_dir"
                if [ "$TC" = true ]; then install_cc; fi;;
            */cache_recovery.py:restore:bootstrap)
                printf 'restore-tb\n' >> "$LOG"
                rm -rf "$DK_OPENWRT/build_dir/host" "$DK_OPENWRT/staging_dir/host"
                if [ "$TB" = true ]; then install_cc; fi;;
            *) return 99;;
        esac
    else
        "$@"
    fi
}
install_cc() {
    mkdir -p "$DK_OPENWRT/staging_dir/host/bin"
    printf '#!/bin/sh\nexit 0\n' > "$DK_OPENWRT/staging_dir/host/bin/ccache"
    chmod +x "$DK_OPENWRT/staging_dir/host/bin/ccache"
}
make() {
    case "$1" in
        download)
            [ "$*" = 'download -j8' ] || return 97
            [ "$(umask)" = "$EXPECTED_UMASK" ] || return 96
            if [ "$EXPECTED_UMASK" = 0022 ]; then [ -f "$DK_OPENWRT/tar-umask" ] || return 95; fi
            printf 'download\n' >> "$LOG"
            [ "$FAIL_DOWNLOAD" = false ] || return 19
            mkdir -p build_dir/host staging_dir/host/bin dl
            touch build_dir/host/download-stamp
            printf 'downloaded\n' > dl/fixture.tar;;
        tools/ccache/compile)
            printf 'bootstrap\n' >> "$LOG"
            [ -f build_dir/host/download-stamp ] || return 98
            install_cc;;
        *)
            printf 'world\n' >> "$LOG"
            [ -f build_dir/host/download-stamp ] || return 98;;
    esac
}
python3() { printf 'snapshot\n' >> "$LOG"; }
git() { [ "$*" = 'config --global tar.umask 0022' ] && touch "$DK_OPENWRT/tar-umask"; }
export -f docker_exec install_cc make python3 git
'''


class DownloadWorkflowTests(unittest.TestCase):
    def test_download_is_after_all_restores_before_compile(self):
        source = step('inputs')
        self.assertNotIn('make download', source['run'])
        self.assertIn('CONFIG_USE_LLVM_HOST=y', source['run'])
        self.assertLess(STEPS.index(source), STEPS.index(step('Extract toolchain cache')))
        self.assertLess(source['run'].index('make defconfig'), source['run'].index('KEY=$(docker_exec'))
        download = step('Download sources')
        for name in ('Extract toolchain cache', 'Extract compiler bootstrap'):
            self.assertLess(STEPS.index(step(name)), STEPS.index(download))
        self.assertLess(STEPS.index(download), STEPS.index(step('Compile firmware')))
        self.assertNotIn('if', download)  # implicit success(), including restore failures
        self.assertFalse(download.get('continue-on-error', False))
        self.assertIn('docker_exec DK bash -e -c', download['run'])

    def replay(self, tc, tb, failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.config').write_text('CONFIG_CCACHE=y\n')
            values = {'steps.tc_restore.outputs.hit': tc, 'steps.tb_restore.outputs.hit': tb,
                      'steps.inputs.outputs.key': 'tc-fixture', 'steps.tc_restore.outputs.poisoned': 'false',
                          'steps.tb_restore.outputs.poisoned': 'false',
                          'steps.tb_inputs.outputs.key': 'tb-fixture'}
            env = dict(os.environ, DK_OPENWRT=tmp, TC=tc, TB=tb, LOG=str(root / 'calls'),
                       FAIL_DOWNLOAD=str(failure).lower(), EXPECTED_UMASK='0022', GITHUB_OUTPUT=str(root / 'outputs'))
            executed = []
            status = 0
            for item in STEPS[STEPS.index(step('Extract toolchain cache')):STEPS.index(step('Compile firmware')) + 1]:
                if 'run' not in item or item['name'] == 'Prepare bootstrap cache key' or item['name'].startswith('Invalidate rejected'):
                    continue
                if item.get('if') and tc == 'true':
                    continue
                if status:
                    continue
                executed.append(item['name'])
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', PREFIX + render(item['run'], values)],
                                        cwd=root, env=dict(env, **render_env(item, values)),
                                        text=True, capture_output=True)
                status = result.returncode
                self.assertNotIn('command not found', result.stderr)
            return status, executed, (root / 'calls').read_text().splitlines()

    def test_tc_tb_cold_restore_download_compile_lifecycle(self):
        for tc, tb, expected in (
            ('true', '', ['restore-tc', 'download', 'world']),
            ('false', 'true', ['restore-tc', 'restore-tb', 'download', 'bootstrap', 'world']),
            ('false', 'false', ['restore-tc', 'restore-tb', 'download', 'bootstrap', 'snapshot', 'world']),
        ):
            with self.subTest(tc=tc, tb=tb):
                status, _, calls = self.replay(tc, tb)
                self.assertEqual(status, 0, calls)
                self.assertEqual(calls, expected)

    def test_download_failure_stops_compile_in_all_cache_states(self):
        for tc, tb in (('true', ''), ('false', 'true'), ('false', 'false')):
            with self.subTest(tc=tc, tb=tb):
                status, executed, calls = self.replay(tc, tb, failure=True)
                self.assertNotEqual(status, 0)
                self.assertNotIn('Compile firmware', executed)
                self.assertEqual(calls[-1], 'download')

    def test_download_preserves_profile_config_and_cache_key_inputs(self):
        def module(name):
            spec = importlib.util.spec_from_file_location(name, ROOT / ('scripts/' + name + '.py'))
            assert spec is not None and spec.loader is not None
            result = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(result)
            return result
        tc, tb = module('cache'), module('bootstrap_cache')
        profile = ROOT / 'user/default/config.diff'
        original = profile.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in tc.INPUTS:
                p = root / name
                if name in ('.config', 'rules.mk', 'Makefile', 'Config.in'):
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(original if name == '.config' else b'# fixture\n')
                else:
                    p.mkdir(parents=True, exist_ok=True)
                    (p / 'fixture').write_text('# fixture\n')
            for name in tb.FIXED_INPUTS:
                p = root / name
                if not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text('# fixture\n')
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            def keys():
                with contextlib.redirect_stderr(io.StringIO()):
                    toolchain = tc.key(root, 'fixture-builder')
                    return toolchain, tb.key(root, 'fixture-builder', toolchain)
            before = keys()
            protected = {p.relative_to(root): p.read_bytes() for p in root.rglob('*')
                         if p.is_file() and '.git' not in p.parts}
            env = dict(os.environ, DK_OPENWRT=tmp, LOG=str(root / 'calls'), FAIL_DOWNLOAD='false', EXPECTED_UMASK='0022')
            result = subprocess.run(['bash', '-eo', 'pipefail', '-c', PREFIX + step('Download sources')['run']],
                                    cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(before, keys())
            self.assertEqual(protected, {name: (root / name).read_bytes() for name in protected})
            self.assertEqual(profile.read_bytes(), original)
