"""Exercise the workflow's fetch/checkout/clean with an isolated real Git remote."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from workflow_fixture import WORKFLOW

ROOT = Path(__file__).resolve().parents[1]


def checkout_block():
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if 'git fetch origin ' in line)
    end = next(i for i in range(start, len(lines)) if 'git clean -ffdx' in lines[i])
    return '\n'.join(line.strip() for line in lines[start:end + 1])


class FetchFailureTests(unittest.TestCase):
    def test_failed_output_symlink_stops_source_preparation(self):
        lines = WORKFLOW.read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if 'ln -s' in line and 'DK_BIN' in line)
        end = next(i for i in range(start, len(lines)) if './scripts/feeds update' in lines[i])
        fragment = '\n'.join(line.strip() for line in lines[start:end])
        for failure, expected in (('none', ['bin', 'dl', 'continued']),
                                  ('bin', ['bin']), ('dl', ['bin', 'dl'])):
            with self.subTest(failure=failure):
                result = subprocess.run(['bash', '-e', '-c',
                    'ln() { printf "%s\\n" "$3"; [ "$3" != "$FAILURE" ] || return 17; };\n'
                    + fragment + '\necho continued'],
                    env=dict(os.environ, DK_BIN='/fixture/only', FAILURE=failure),
                    text=True, capture_output=True)
                self.assertEqual(result.stdout.splitlines(), expected)
                self.assertEqual(result.returncode, 0 if failure == 'none' else 17)

    def test_fetch_failure_leaves_checkout_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT, text=True).strip()
            git('init', '-b', 'main')
            git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                'commit', '--allow-empty', '-m', 'fixture')
            sha = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/remotes/origin/main', sha)
            git('remote', 'add', 'origin', str(root / 'missing-remote'))
            tracked = root / 'tracked'
            tracked.write_text('original')
            git('add', 'tracked')
            git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                'commit', '-m', 'local fixture')
            tracked.write_text('must survive failed fetch')
            head = git('rev-parse', 'HEAD')
            result = subprocess.run(['bash', '-e', '-c', checkout_block() + '\nprintf CONTINUED'],
                                    cwd=root, env=dict(os.environ, REPO_BRANCH='main'),
                                    text=True, capture_output=True)
            self.assertIn('fatal:', result.stderr)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('CONTINUED', result.stdout)
            self.assertEqual(git('rev-parse', 'HEAD'), head)
            self.assertEqual(tracked.read_text(), 'must survive failed fetch')

    def test_checkout_replaces_dirty_tracked_files_and_cleans_seeded_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream, checkout = root / 'upstream', root / 'checkout'

            def git(path, *args):
                return subprocess.check_output(
                    ['git', '-C', str(path), '-c', 'user.name=Fixture',
                     '-c', 'user.email=fixture@example.invalid', *args],
                    stderr=subprocess.PIPE, text=True).strip()

            upstream.mkdir()
            git(upstream, 'init', '-b', 'main')
            (upstream / 'tracked').write_text('old')
            (upstream / '.gitignore').write_text('build_dir/\n')
            git(upstream, 'add', '.')
            git(upstream, 'commit', '-m', 'old fixture')
            git(root, 'clone', str(upstream), str(checkout))
            (upstream / 'tracked').write_text('upstream')
            git(upstream, 'commit', '-am', 'new fixture')
            (checkout / 'tracked').write_text('staged local input')
            git(checkout, 'add', 'tracked')
            (checkout / 'tracked').write_text('unstaged local input')
            (checkout / 'build_dir').mkdir()
            (checkout / 'build_dir/seed').touch()
            git(checkout, 'init', 'feeds/cache')
            result = subprocess.run(['bash', '-e', '-c', checkout_block()], cwd=checkout,
                                    env=dict(os.environ, REPO_BRANCH='main'), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git(checkout, 'rev-parse', 'HEAD'), git(upstream, 'rev-parse', 'HEAD'))
            self.assertEqual(git(checkout, 'rev-parse', '--symbolic-full-name', '@{upstream}'),
                             'refs/remotes/origin/main')
            self.assertEqual((checkout / 'tracked').read_text(), 'upstream')
            self.assertEqual(git(checkout, 'status', '--porcelain'), '')
            self.assertFalse((checkout / 'build_dir').exists())
            self.assertFalse((checkout / 'feeds').exists())
