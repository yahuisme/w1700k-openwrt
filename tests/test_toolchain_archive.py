"""Exact TC member boundaries through the production cache recovery CLI."""
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'scripts/cache_recovery.py'


class ToolchainArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'root'
        self.archive = self.base / 'archive'
        self.root.mkdir()
        self.archive.mkdir()

    def cli(self):
        return subprocess.run([sys.executable, str(SCRIPT), 'restore', 'toolchain',
                               str(self.root), str(self.archive), 'matched',
                               '--restored', 'matched', '--outcome', 'success'],
                              text=True, capture_output=True)

    def archive_entries(self, extra=()):
        with tarfile.open(self.archive / 'toolchain.tar.gz', 'w:gz') as tf:
            for name in ('build_dir/host', 'staging_dir/host',
                         'build_dir/toolchain-test', 'staging_dir/toolchain-test'):
                item = tarfile.TarInfo(name)
                item.type = tarfile.DIRTYPE
                tf.addfile(item)
            item = tarfile.TarInfo('staging_dir/host/bin/ccache')
            item.mode = 0o755
            item.size = 2
            tf.addfile(item, io.BytesIO(b'ok'))
            for item in extra:
                tf.addfile(item, io.BytesIO(b'x' * item.size) if item.isfile() else None)
        (self.archive / 'key').write_text('matched\n')

    def test_source_member_is_rejected_before_extraction(self):
        (self.root / '.config').write_text('original')
        item = tarfile.TarInfo('.config')
        item.size = 6
        self.archive_entries([item])
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / '.config').read_text(), 'original')
        self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
        self.assertIn('unsafe/duplicate archive path', result.stderr)
        self.assertFalse((self.root / 'staging_dir').exists())
        self.assertEqual(list(self.archive.iterdir()), [])

    @staticmethod
    def member(name, kind=tarfile.REGTYPE, target='', mode=0o644):
        item = tarfile.TarInfo(name)
        item.type, item.linkname, item.mode = kind, target, mode
        item.size = 1 if kind == tarfile.REGTYPE else 0
        return item

    def test_rejects_unsafe_members_and_link_graphs(self):
        m = self.member
        cases = [[m(name)] for name in (
            'target/payload', 'package/payload', 'staging_dir/hostpkg/payload',
            'build_dir/target-test/payload', '../escape', '/absolute',
            'build_dir/host/../../.config', 'build_dir/host/./alias',
            'build_dir/host//alias', 'staging_dir/host/bin/ccache')]
        cases += [
            [m('build_dir/host/fifo', tarfile.FIFOTYPE)],
            [m('build_dir/host/device', tarfile.CHRTYPE)],
            [m('build_dir/host/privileged', mode=0o4755)],
            [m('build_dir/host/link', tarfile.SYMTYPE, '../../.config')],
            [m('build_dir/host/link', tarfile.SYMTYPE, '/etc/passwd')],
            [m('build_dir/host/link', tarfile.LNKTYPE, '.config')],
            [m('build_dir/host/link', tarfile.LNKTYPE, 'build_dir/host/missing')],
            [m('build_dir/host/a', tarfile.SYMTYPE, 'b'),
             m('build_dir/host/b', tarfile.SYMTYPE, 'a')],
            [m('build_dir/host/link', tarfile.SYMTYPE, '/usr/bin'),
             m('build_dir/host/link/payload')],
            [m('build_dir/host/alias', tarfile.SYMTYPE, 'real'),
             m('build_dir/host/next', tarfile.SYMTYPE, 'alias/../real')],
        ]
        (self.root / '.config').write_text('original')
        for entries in cases:
            with self.subTest(entries=[(e.name, e.linkname) for e in entries]):
                self.archive_entries(entries)
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertEqual((self.root / '.config').read_text(), 'original')
                self.assertFalse((self.root / 'build_dir').exists())
                self.assertFalse((self.root / 'staging_dir').exists())
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_native_prerequisite_internal_and_system_links(self):
        scripts = self.root / 'scripts'
        scripts.mkdir(mode=0o755)
        for name in ('xxdi.pl', 'noop.sh'):
            script = scripts / name
            script.write_text('#!/bin/sh\nexit 0\n')
            script.chmod(0o755)
        m = self.member
        self.archive_entries([
            m('staging_dir/host/bin/xxd', tarfile.SYMTYPE, str(scripts / 'xxdi.pl')),
            m('staging_dir/host/bin/ldconfig', tarfile.SYMTYPE, str(scripts / 'noop.sh')),
            m('staging_dir/host/bin/sh', tarfile.SYMTYPE, '/bin/sh'),
            m('build_dir/toolchain-test/data'),
            m('build_dir/toolchain-test/hard', tarfile.LNKTYPE, 'build_dir/toolchain-test/data'),
            m('staging_dir/toolchain-test/link', tarfile.SYMTYPE, '../../build_dir/toolchain-test/data'),
        ])
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertEqual((self.root / 'staging_dir/toolchain-test/link').read_bytes(), b'x')
        self.assertEqual((self.root / 'build_dir/toolchain-test/hard').stat().st_ino,
                         (self.root / 'build_dir/toolchain-test/data').stat().st_ino)

    def test_native_autoreconf_script_link_packs_and_restores(self):
        # Both recorded W1700K snapshot autotools.mk files create this absolute
        # source-script link inside host packages; do not dereference it.
        script = self.root / 'scripts/config.rpath'
        script.parent.mkdir(mode=0o755)
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        self.archive_entries()
        self.assertEqual(self.cli().stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        link = self.root / 'build_dir/host/gmp-6.3.0/config.rpath'
        link.parent.mkdir()
        subprocess.run(['ln', '-s', str(script), str(link)], check=True)
        pack = subprocess.run([sys.executable, str(SCRIPT.with_name('cache.py')),
                               'toolchain', str(self.root), str(self.archive), 'matched'],
                              text=True, capture_output=True)
        self.assertEqual(pack.returncode, 0, pack.stdout + pack.stderr)
        with tarfile.open(self.archive / 'toolchain.tar.gz', 'r:gz') as tf:
            member = tf.getmember(link.relative_to(self.root).as_posix())
            self.assertTrue(member.issym())
            self.assertEqual(member.linkname, str(script))
        restored = self.cli()
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(restored.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_bytes(), script.read_bytes())

    def test_autoreconf_exception_remains_exact_and_source_locked(self):
        script = self.root / 'scripts/config.rpath'
        script.parent.mkdir(mode=0o755)
        good = ('build_dir/host/gmp-6.3.0/config.rpath', str(script), 'regular')
        cases = [
            ('build_dir/host/gmp-6.3.0/config.rpath', str(self.root / 'scripts/noop.sh'), 'regular'),
            ('build_dir/host/gmp-6.3.0/other', str(script), 'regular'),
            ('staging_dir/host/share/config.rpath', str(script), 'regular'),
            ('build_dir/host/config.rpath', str(script), 'regular'),
            (good[0], '../../../scripts/config.rpath', 'regular'),
            (good[0], str(script), 'missing'),
            (good[0], str(script), 'nonexec'),
            (good[0], str(script), 'writable'),
            (good[0], str(script), 'symlink'),
        ]
        for name, target, state in cases:
            with self.subTest(name=name, target=target, state=state):
                script.unlink(missing_ok=True)
                if state != 'missing':
                    script.write_text('#!/bin/sh\nexit 0\n')
                    script.chmod({'nonexec': 0o644, 'writable': 0o777}.get(state, 0o755))
                if state == 'symlink':
                    script.unlink()
                    script.symlink_to('/bin/sh')
                self.archive_entries([self.member(name, tarfile.SYMTYPE, target)])
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'hit=false\nmatched-key=\npoisoned=true\n')
                self.assertFalse((self.root / 'build_dir').exists())
                self.assertEqual(list(self.archive.iterdir()), [])

    def test_pack_rejects_source_link_without_upload_candidate(self):
        self.archive_entries()
        self.assertIn('hit=true\n', self.cli().stdout)
        (self.root / '.config').write_text('original')
        (self.root / 'staging_dir/host/source-link').symlink_to('../../.config')
        result = subprocess.run([sys.executable, str(SCRIPT.with_name('cache.py')),
                                 'toolchain', str(self.root), str(self.archive), 'matched'],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('archive link escapes host pair', result.stderr)
        self.assertFalse((self.archive / 'toolchain.tar.gz').exists())
        self.assertEqual((self.root / '.config').read_text(), 'original')

    def test_valid_toolchain_graph_restores_and_hits(self):
        self.archive_entries()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'hit=true\nmatched-key=matched\npoisoned=false\n')
        self.assertEqual((self.root / 'staging_dir/host/bin/ccache').read_bytes(), b'ok')
