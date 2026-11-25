"""Exercise the shared ttyd package hook after either distro is selected."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.select_distribution import select

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = '110-run-libuv-loop.patch'
SOURCE_HASH = '039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650'


class TtydCompat(unittest.TestCase):
    def test_materialized_customization_scopes_the_native_patch(self):
        for distro in ('openwrt', 'immortalwrt'):
            with self.subTest(distro=distro), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                for path in ('user', 'installer'):
                    shutil.copytree(ROOT / path, base / path)
                select(distro, base)
                script = (base / 'user/default/custom.sh').read_text()
                marker = '# Backport the reviewed ttyd event loop fix.'
                self.assertEqual(script.count(marker), 1)
                commands = script.split(marker, 1)[1].split('# Preserve buildroot ownership', 1)[0]
                package = base / 'feeds/packages/utils/ttyd'
                patches = package / 'patches'
                patches.mkdir(parents=True)
                original = patches / '100-log-to-syslog.patch'
                original.write_text('official logging patch\n')
                target = patches / PAYLOAD
                payload_dir = base / 'user/w1700k-patches'
                expected = (payload_dir / 'patches' / PAYLOAD).read_bytes()
                makefile = package / 'Makefile'
                for mode in ('known', 'repeat', 'unknown', 'conflict', 'upstream-r2', 'duplicate-release'):
                    with self.subTest(mode=mode):
                        version = '2.0.0' if mode == 'unknown' else '1.7.7'
                        release = '2' if mode in ('repeat', 'upstream-r2') else '1'
                        recipe = f'PKG_VERSION:={version}\nPKG_RELEASE:={release}\nPKG_HASH:={SOURCE_HASH}\n'
                        if mode == 'duplicate-release':
                            recipe += 'PKG_RELEASE:=3\n'
                        makefile.write_text(recipe)
                        if mode != 'repeat':
                            target.unlink(missing_ok=True)
                        if mode == 'conflict':
                            target.write_bytes(b'feed patch\n')
                        result = subprocess.run(['bash', '-e', '-c', commands], cwd=base,
                                                env=dict(os.environ, PATCH_DIR=str(payload_dir)),
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode == 0, mode in ('known', 'repeat'), result.stderr)
                        self.assertEqual(makefile.read_text(), recipe.replace('PKG_RELEASE:=1', 'PKG_RELEASE:=2')
                                         if mode == 'known' else recipe)
                        self.assertEqual(original.read_text(), 'official logging patch\n')
                        if mode in ('known', 'repeat'):
                            self.assertEqual(target.read_bytes(), expected)
                        elif mode == 'unknown':
                            self.assertFalse(target.exists())
                            self.assertIn('unreviewed ttyd source', result.stderr)
                        elif mode == 'conflict':
                            self.assertIn('conflicting ttyd compatibility patch', result.stderr)
                            self.assertEqual(target.read_bytes(), b'feed patch\n')
                        else:
                            self.assertIn('unreviewed ttyd package release', result.stderr)
                            self.assertFalse(target.exists())
