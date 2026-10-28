#!/usr/bin/env python3
"""Execute signed Aurora preparation and the custom-app clone lifecycle."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CUSTOM = (ROOT / 'user/default/custom.sh').read_text()


class CustomProfile(unittest.TestCase):
    def test_signed_aurora_preparation_failure_stops_customization(self):
        self.assertNotIn('https://github.com/eamonxg/', CUSTOM)
        self.assertNotIn('TPL_DIR=', CUSTOM)
        commands = [line for line in CUSTOM.splitlines()
                    if line.startswith('python3 /cache-scripts/external_packages.py prepare ')]
        self.assertEqual(len(commands), 1)
        for status in (0, 23):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                mock = r'''python3() {
    printf '%s\n' "$PWD" "$@" > prepare-calls
    return "$PREPARE_STATUS"
}
'''
                result = subprocess.run(['bash', '-ec', mock + commands[0] + '\ntouch reached'],
                                        cwd=tmp, env=dict(os.environ, PREPARE_STATUS=str(status)),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                self.assertEqual((Path(tmp) / 'reached').exists(), status == 0)
                self.assertEqual((Path(tmp) / 'prepare-calls').read_text().splitlines(),
                                 [tmp, '/cache-scripts/external_packages.py', 'prepare', '.'])

    def test_aurora_is_external_without_changing_native_packages(self):
        config = (ROOT / 'user/default/config.diff').read_text()
        self.assertNotIn('CONFIG_PACKAGE_luci-theme-aurora', config)
        self.assertNotIn('CONFIG_PACKAGE_luci-app-aurora-config', config)
        self.assertNotIn('CONFIG_PACKAGE_luci-i18n-aurora-config', config)
        for package in ('luci', 'luci-light', 'luci-app-package-manager', 'luci-theme-bootstrap'):
            self.assertIn(f'CONFIG_PACKAGE_{package}=y', config.splitlines())

    def test_package_temp_cleanup_and_provenance(self):
        # Omit unrelated overlay/patch application; run real temporary clone/copy lifecycle.
        start = CUSTOM.index('if ! git clone --depth=1 https://github.com/yahuisme/packages.git')
        end = CUSTOM.index('# Required patches', start)
        lifecycle = CUSTOM[CUSTOM.index('PKG_REPO='):CUSTOM.index('if ! git clone --depth=1 https://github.com/yahuisme/packages.git')]
        fragment = lifecycle + CUSTOM[start:end]
        mock = '''git() {
    if [ "$1" = -C ]; then printf '%040d\\n' 456; return; fi
    local dest="${@: -1}"
    printf '%s' "$dest" > clone-path
    [ "$MODE" != clone-failure ] || return 1
    for pkg in luci-app-wifi7 luci-app-airoha-npu luci-app-airoha-flowsense luci-app-airoha-fancontrol; do
        mkdir -p "$dest/$pkg"
        touch "$dest/$pkg/Makefile"
    done
    [ "$MODE" != missing-package ] || rm -r "$dest/luci-app-wifi7"
}
'''
        for mode in ('success', 'clone-failure', 'missing-package'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                (work / 'package').mkdir()
                result = subprocess.run(['bash', '-ec', mock + fragment + '\ntouch reached'], cwd=work,
                                        env=dict(os.environ, MODE=mode, TMPDIR=tmp), text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, mode == 'success', result.stderr)
                self.assertFalse(Path((work / 'clone-path').read_text()).exists())
                self.assertEqual((work / 'reached').exists(), mode == 'success')
                if mode == 'success':
                    self.assertIn('yahuisme/packages: ' + '456'.zfill(40), result.stdout)
                    self.assertEqual(len(list((work / 'package').glob('*/Makefile'))), 4)


if __name__ == '__main__':
    unittest.main()
