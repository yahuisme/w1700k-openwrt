"""The runner-owned profile overlay must not change buildroot ownership."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.geteuid() == 0, 'requires root to reproduce runner/container uid boundary')
class TreeOverlayOwnership(unittest.TestCase):
    def test_post_customization_git_gate(self):
        workflow = (ROOT / '.github/workflows/W1700K.yaml').read_text()
        custom = workflow.index('bash $DK_PROFILE/custom.sh')
        config = workflow.index('make defconfig', custom)
        self.assertIn('git rev-parse --verify HEAD > /dev/null', workflow[custom:config])

    def test_overlay_preserves_buildroot_and_git_identity(self):
        script = (ROOT / 'user/default/custom.sh').read_text()
        command = next(line for line in script.splitlines() if line.startswith('cp ') and '$DK_PROFILE/tree/.' in line)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            tree = base / 'profile/tree'
            tree.mkdir(parents=True)
            (tree / 'target').mkdir()
            (tree / 'target/payload').write_text('required patch payload\n')
            (tree / 'link').symlink_to('target/payload')
            for path in (tree, tree / 'target', tree / 'target/payload'):
                os.chown(path, 1001, 1001)
            work = base / 'buildroot'
            work.mkdir()
            subprocess.run(['git', 'init', '-q', str(work)], check=True)
            (work / 'tracked').write_text('source\n')
            subprocess.run(['git', '-C', str(work), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(work), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'source'], check=True)
            env = dict(os.environ, DK_PROFILE=str(tree.parent), HOME=str(base), GIT_CONFIG_NOSYSTEM='1')
            result = subprocess.run(['bash', '-ec', command], cwd=work, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(work.stat().st_uid, 0, 'overlay changed root-owned buildroot to runner uid')
            git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=work, env=env, text=True, capture_output=True)
            self.assertEqual(git.returncode, 0, git.stderr)
            self.assertEqual((work / 'target/payload').read_text(), 'required patch payload\n')
            self.assertTrue((work / 'link').is_symlink())


if __name__ == '__main__':
    unittest.main()
