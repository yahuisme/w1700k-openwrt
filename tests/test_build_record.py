"""Actual metadata helper and publish shell; Git/gh remain entirely local."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_cache_workflow import ROOT, step
import test_release_safety as safety
from test_release_safety import IMAGE
from test_release_retention import GH, CURRENT, PREFIX, release
from record_fixture import prepare, READBACK


class BuildRecordTests(unittest.TestCase):
    def test_actual_helper_success_and_missing_metadata(self):
        for missing in ('', '.config', '.custom-revisions.tsv', 'manifest', 'feed'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, _ = safety.ReleaseTests().fixture(base)
                prepare(base)
                if missing == 'manifest':
                    (output / 'fixture.manifest').unlink()
                elif missing == 'feed':
                    (base / 'feeds/packages/.git').rename(base / 'feed-git-hidden')
                elif missing:
                    (base / missing).unlink()
                (output / IMAGE).chmod(0o600)
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'), tmp,
                                         str(base / 'record')], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not missing, result.stderr)
                record = base / 'record'
                self.assertEqual(bool(json.loads((record / 'diagnostics.json').read_text())['errors']), bool(missing))
                self.assertIn(hashlib.sha256((output / IMAGE).read_bytes()).hexdigest(),
                              (record / 'sha256sums').read_text())
                self.assertFalse(list(record.glob('**/*.itb')))
                for path in record.rglob('*'):
                    if path.is_file():
                        self.assertEqual(path.stat().st_mode & 0o444, 0o444)
                if not missing:
                    revisions = json.loads((record / 'revisions.json').read_text())
                    self.assertEqual({r['name'] for r in revisions}, {'source', 'feed/packages'})
                    sha = subprocess.check_output(['git', '-C', tmp, 'rev-parse', 'HEAD'], text=True).strip()
                    self.assertEqual(revisions[0]['sha'], sha)

    def test_copy_errors_retain_later_evidence(self):
        for collision in ('final.config', 'targets'):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                output, _ = safety.ReleaseTests().fixture(base)
                prepare(base)
                record = base / 'record'
                record.mkdir()
                if collision == 'final.config':
                    (record / collision).mkdir()
                else:
                    (record / collision).write_text('not a directory')
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'),
                                         tmp, str(record)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                errors = json.loads((record / 'diagnostics.json').read_text())['errors']
                self.assertTrue(any('Copy failed:' in error for error in errors))
                self.assertEqual((record / 'custom-revisions.tsv').read_bytes(),
                                 (base / '.custom-revisions.tsv').read_bytes())
                self.assertIn(hashlib.sha256((output / IMAGE).read_bytes()).hexdigest(),
                              (record / 'sha256sums').read_text())

    def test_dpkg_inventory_success_empty_and_failure(self):
        for mode in ('ok', 'empty', 'failure'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                safety.ReleaseTests().fixture(base)
                prepare(base)
                commands = base / 'commands'
                commands.mkdir()
                stub = commands / 'dpkg-query'
                stub.write_text('#!/bin/sh\n' + {
                    'ok': "printf 'z\\tarm64\\t2\\na\\tall\\t1\\n'\n",
                    'empty': 'exit 0\n', 'failure': 'exit 17\n'}[mode])
                stub.chmod(0o755)
                record = base / 'record'
                result = subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'),
                    tmp, str(record)], capture_output=True, text=True,
                    env=dict(os.environ, PATH=str(commands)+':'+os.environ['PATH']))
                self.assertEqual(result.returncode == 0, mode == 'ok', result.stderr)
                self.assertEqual(bool(json.loads((record / 'diagnostics.json').read_text())['errors']), mode != 'ok')
                self.assertTrue((record / 'sha256sums').read_text())
                if mode == 'ok':
                    self.assertEqual((record / 'dpkg-packages.tsv').read_text(), 'a\tall\t1\nz\tarm64\t2\n')

    def test_feed_failures_keep_stderr(self):
        lines = [line.strip() for line in step('Prepare source and cache key')['run'].splitlines()
                 if './scripts/feeds ' in line]
        self.assertEqual(len(lines), 2)
        for line in lines:
            with self.subTest(line=line), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / 'scripts').mkdir()
                feeds = base / 'scripts/feeds'
                feeds.write_text('#!/bin/sh\nprintf "feed diagnostic" >&2\nexit 17\n')
                feeds.chmod(0o755)
                result = subprocess.run(['bash', '-e', '-c', line], cwd=base,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('feed diagnostic', result.stderr)

    def test_actual_custom_clone_record_fragments(self):
        script = (ROOT / 'user/default/custom.sh').read_text()
        start = script.index('PKG_SHA=$(git -C "$PKG_REPO" rev-parse HEAD)')
        first = script[start:script.index('cp -r "$PKG_REPO/luci-app-wifi7"', start)]
        start = script.index('    PKG_SHA=$(git -C "package/$pkg" rev-parse HEAD)')
        second = script[start:script.index('\ndone', start)]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            safety.ReleaseTests().fixture(base)
            prepare(base)
            sha = subprocess.check_output(['git', '-C', tmp, 'rev-parse', 'HEAD'], text=True).strip()
            for pkg in ('luci-theme-aurora', 'luci-app-aurora-config'):
                path = base / 'package' / pkg
                path.parent.mkdir(exist_ok=True)
                path.symlink_to(base / 'feeds/packages', target_is_directory=True)
            subprocess.run(['bash', '-e', '-c', first + '\nfor pkg in luci-theme-aurora luci-app-aurora-config; do\n' + second + '\ndone'],
                           cwd=base, env=dict(os.environ, PKG_REPO=tmp), check=True, capture_output=True)
            rows = [line.split('\t') for line in (base / '.custom-revisions.tsv').read_text().splitlines()]
            self.assertEqual(rows[0], ['yahuisme/packages', 'https://example.invalid/local', sha])
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(len(row[2]) == 40 for row in rows))

    def test_artifact_contract(self):
        collect, upload = step('Collect build record'), step('Upload build record')
        self.assertTrue(collect['continue-on-error'])
        self.assertTrue(upload['continue-on-error'])
        self.assertEqual(collect['if'], '${{ always() }}')
        self.assertEqual(upload['if'], '${{ always() }}')
        self.assertEqual(upload['with']['retention-days'], 30)
        self.assertEqual(upload['with']['path'], 'build-record/')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertEqual(step('Publish firmware and prune releases')['if'],
                         "${{ !cancelled() && steps.stage.outcome == 'success' }}")

    def test_readback_failure_cannot_prune(self):
        mutations = {
            'missing': 'assets=[]',
            'size': "assets[0]['size']+=1",
            'extra': "assets.append(dict(assets[0],name='extra.itb'))",
            'state': "assets[0]['state']='new'",
            'digest': "assets[0]['digest']='sha256:'+'0'*64",
            'draft': 'pass',
            'bad-json': "print('{'); sys.exit(0)",
            'api-failure': 'sys.exit(17)',
            'download': "assets[0]['digest']=None",
            'download-wrong': "assets[0]['digest']=None",
            'download-failure': "assets[0]['digest']=None",
            'ok': 'pass',
        }
        for mode, mutation in mutations.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / 'scripts').symlink_to(ROOT / 'scripts')
                (base / 'firmware').mkdir()
                (base / 'firmware/version.txt').write_text(CURRENT)
                (base / 'firmware/release-notes.md').write_text('fixture')
                (base / 'firmware/image-sysupgrade.itb').write_bytes(b'local fixture image')
                readback = READBACK.replace('    print(json.dumps', '    '+mutation+'\n    print(json.dumps')
                if mode == 'draft':
                    readback = readback.replace('draft=False', 'draft=True')
                stub = GH.replace(READBACK, readback)
                stub = stub.replace("elif args[0] == 'api' and '/releases/tags/'", """elif args[0] == 'api' and '/releases/assets/' in args[1]:
    if os.environ['MODE']=='download-failure': sys.exit(17)
    sys.stdout.buffer.write(b'bad' if os.environ['MODE']=='download-wrong' else Path('firmware/image-sysupgrade.itb').read_bytes())
elif args[0] == 'api' and '/releases/tags/'""")
                (base / 'gh').write_text(stub)
                (base / 'gh').chmod(0o755)
                (base / 'pages.json').write_text(json.dumps([[release(CURRENT, 3),
                    release(PREFIX+'previous', 2), release(PREFIX+'old', 1)]]))
                env = dict(os.environ, PATH=tmp+':'+os.environ['PATH'], GITHUB_SHA='a'*40,
                           GITHUB_REPOSITORY='fixture/repo', FAULT='', MODE=mode)
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c',
                    step('Publish firmware and prune releases')['run']], cwd=base, env=env,
                    capture_output=True, text=True)
                good = mode in ('ok', 'download')
                self.assertEqual(result.returncode == 0, good, result.stderr)
                calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
                self.assertEqual([c[2] for c in calls if c[:2] == ['release', 'delete']],
                                 [PREFIX+'old'] if good else [])
