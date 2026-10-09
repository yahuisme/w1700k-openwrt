#!/usr/bin/env python3
"""Execute complete Aurora clone/preset block with only Git mocked."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CUSTOM = (ROOT / 'user/default/custom.sh').read_text()


class CustomProfile(unittest.TestCase):
    def test_complete_aurora_fragment(self):
        start = CUSTOM.index('for pkg in luci-theme-aurora')
        fragment = CUSTOM[start:CUSTOM.index('# The temperature & fan', start)]
        mock = '''git() {
    if [ "$1" = -C ]; then printf '%040d\\n' 123; return; fi
    local dest="${@: -1}"
    [ "$MODE:$dest" != "clone-failure:$FAIL_PACKAGE" ] || return 1
    mkdir -p "$dest"
    [ "$MODE:$dest" = "missing-makefile:$FAIL_PACKAGE" ] || touch "$dest/Makefile"
    if [[ "$dest" = *luci-app-aurora-config ]]; then
        local dir="$dest/root/usr/share/aurora"
        [ "$MODE" != missing-dir ] || return 0
        mkdir -p "$dir"
        [ "$MODE" != empty-dir ] || return 0
        for name in default custom; do
            [ "$MODE:$name" != missing-default:default ] || continue
            printf "\\toption nav_type 'mega-menu'  \\n\\toption struct_radius_base '0.5rem' \\n" > "$dir/$name.template"
        done
        if [ "$MODE" = mismatch ]; then
            printf "option unknown 'upstream-changed'\\n" > "$dir/custom.template"
        fi
    fi
}
'''
        for package in ('luci-theme-aurora', 'luci-app-aurora-config'):
            for mode in ('success', 'clone-failure', 'missing-makefile', 'missing-dir',
                         'empty-dir', 'missing-default', 'mismatch'):
                with self.subTest(mode=mode, package=package), tempfile.TemporaryDirectory() as tmp:
                    result = subprocess.run(['bash', '-ec', mock + fragment + '\ntouch reached'],
                                            cwd=tmp, env=dict(os.environ, MODE=mode, FAIL_PACKAGE='package/' + package),
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode == 0, mode == 'success', result.stdout + result.stderr)
                    self.assertEqual((Path(tmp) / 'reached').exists(), mode == 'success')
                    if mode == 'success':
                        for pkg in ('luci-theme-aurora', 'luci-app-aurora-config'):
                            self.assertIn(pkg + ': ' + '123'.zfill(40), result.stdout)
                        for tpl in Path(tmp).rglob('*.template'):
                            self.assertIn("option nav_type 'sidebar'", tpl.read_text())
                            self.assertIn("option struct_radius_base '0.125rem'", tpl.read_text())

    def test_package_temp_cleanup_and_provenance(self):
        # Omit unrelated overlay/patch application; run real temporary clone/copy lifecycle.
        start = CUSTOM.index('if ! git clone --depth=1 https://github.com/yahuisme/packages.git')
        end = CUSTOM.index('# Existing W1700K custom files', start)
        lifecycle = CUSTOM[CUSTOM.index('PKG_REPO='):CUSTOM.index('# Checked-in,')]
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
