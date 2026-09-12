"""Exercise the workflow's fetch/checkout/reset with an isolated real Git remote."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FetchFailureTests(unittest.TestCase):
    def test_fetch_failure_stops_before_reset(self):
        lines = (ROOT / '.github/workflows/W1700K.yaml').read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if 'git fetch origin ' in line)
        end = next(i for i in range(start, len(lines)) if 'git reset --hard origin/' in lines[i])
        fragment = '\n'.join(line.strip() for line in lines[start:end + 1])
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
            result = subprocess.run(['bash', '-e', '-c', fragment + '\nprintf CONTINUED'],
                                    cwd=root, env=dict(os.environ, REPO_BRANCH='main'),
                                    text=True, capture_output=True)
            self.assertIn('fatal:', result.stderr)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('CONTINUED', result.stdout)
            self.assertEqual(git('rev-parse', 'HEAD'), head)
            self.assertEqual(tracked.read_text(), 'must survive failed fetch')
