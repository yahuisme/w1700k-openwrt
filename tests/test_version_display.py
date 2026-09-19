"""Render real upstream templates, without compiling or running defconfig.

VERSION_SOURCE=/path/to/downloaded/upstream python3 tests/test_version_display.py
The source needs include/version.mk, rules.mk and package/base-files/.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class VersionDisplay(unittest.TestCase):
    def test_display_only(self):
        source = os.environ.get('VERSION_SOURCE')
        if not source:
            self.skipTest('set VERSION_SOURCE to real upstream templates')
        source = Path(source)
        install = re.search(r'\$\(VERSION_SED_SCRIPT\) \\\n(.*?)(?=\n\s*\n)',
                            (source / 'package/base-files/Makefile').read_text(), re.S)
        assert install is not None, 'upstream template install list changed'
        names = re.findall(r'\$\(1\)/(\S+)', install[1])
        script = (ROOT / 'user/default/custom.sh').read_text()
        fragment = script.split('# Snapshot branding is display-only;', 1)[1].split('\n# ---', 1)[0]
        fragment = '# Snapshot branding is display-only;' + fragment
        qstrip = next(line for line in (source / 'rules.mk').read_text().splitlines()
                      if line.startswith('qstrip='))
        # Explicit test inputs, not claimed build results or replacement revision numbers.
        for revision in ('r41341-f44d1535b4', 'r12345-0123456789'):
            with self.subTest(revision=revision), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(source / 'package/base-files', root / 'package/base-files')
                shutil.copytree(source / 'include', root / 'include')
                base = root / 'package/base-files/files'
                originals = {name: (base / name).read_bytes() for name in names}
                version_mk = (root / 'include/version.mk').read_bytes()
                makefile = f'''empty:=
space:=$(empty) $(empty)
comma:=,
{qstrip}
tolower=$(shell printf '%s' '$(1)' | tr A-Z a-z)
SED:=sed -i -e
REVISION:={revision}
BOARD:=airoha
SUBTARGET:=an7581
ARCH_PACKAGES:=aarch64_cortex-a53
SOURCE_DATE_EPOCH:=1
include include/version.mk
all:
\t$(VERSION_SED_SCRIPT) {' '.join('package/base-files/files/' + name for name in names)}
\t@printf '%s\\n' '$(VERSION_NUMBER)' '$(VERSION_CODE)' '$(VERSION_REPO)' > metadata
'''
                (root / 'Makefile').write_text(makefile)
                def render():
                    subprocess.run(['make', '--no-print-directory'], cwd=root, check=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    return {name: (base / name).read_text() for name in names}
                before = render()
                metadata = (root / 'metadata').read_bytes()
                for name, data in originals.items():
                    (base / name).write_bytes(data)
                subprocess.run(['bash', '-ec', fragment], cwd=root, check=True)
                modified = {name: (base / name).read_bytes() for name in names}
                subprocess.run(['bash', '-ec', fragment], cwd=root, check=True)
                self.assertEqual(modified, {name: (base / name).read_bytes() for name in names})
                after = render()
                if os.environ.get('VERSION_OUTPUT'):
                    output = Path(os.environ['VERSION_OUTPUT']) / revision
                    for stage, files in (('before', before), ('after', after)):
                        for name, text in files.items():
                            path = output / stage / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(text)
                    (output / 'metadata').write_bytes(metadata)
                self.assertEqual((root / 'include/version.mk').read_bytes(), version_mk)
                self.assertEqual((root / 'metadata').read_bytes(), metadata)
                self.assertIn(b'SNAPSHOT\n', metadata)
                self.assertIn(b'/snapshots\n', metadata)
                expected = dict(before)
                expected['etc/banner'] = before['etc/banner'].replace(' SNAPSHOT, ', ' ')
                expected['etc/openwrt_release'] = before['etc/openwrt_release'].replace(
                    ' SNAPSHOT ' + revision, ' ' + revision)
                expected['usr/lib/os-release'] = before['usr/lib/os-release'].replace(
                    ' SNAPSHOT"', ' ' + revision + '"').replace(' SNAPSHOT ' + revision, ' ' + revision)
                self.assertEqual(after, expected)
                def fields(name):
                    return dict(line.split('=', 1) for line in after[name].splitlines() if '=' in line)
                release, os_release = fields('etc/openwrt_release'), fields('usr/lib/os-release')
                display = release['DISTRIB_DESCRIPTION'].strip("'")
                self.assertNotIn('SNAPSHOT', display)
                self.assertTrue(display.endswith(' ' + revision))
                self.assertIn(' ' + display + '\n', after['etc/banner'])
                self.assertEqual(os_release['PRETTY_NAME'], '"' + display + '"')
                self.assertEqual(os_release['OPENWRT_RELEASE'], '"' + display + '"')
                self.assertEqual(release['DISTRIB_RELEASE'], "'SNAPSHOT'")
                self.assertEqual(os_release['VERSION'], '"SNAPSHOT"')
                self.assertEqual(os_release['VERSION_ID'], '"snapshot"')
                self.assertEqual(os_release['BUILD_ID'], '"' + revision + '"')
                self.assertEqual(after['etc/device_info'], before['etc/device_info'])
                self.assertEqual(after['etc/openwrt_version'], revision + '\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
