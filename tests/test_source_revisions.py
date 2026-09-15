"""Checkout logging stays on stdout and preserves preparation failure gates."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_cache_workflow import render, step

ROOT = Path(__file__).resolve().parents[1]


class SourceRevisionTests(unittest.TestCase):
    def test_nested_prepare_logs_and_failures(self):
        block = render(step('inputs')['run'], {'matrix.target': 'ubi2'})
        for phase in ('', 'fetch', 'revision', 'update', 'install', 'list', 'custom', 'download'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                source = base / 'source'
                (source / 'scripts').mkdir(parents=True)
                profile = base / 'profile'
                (profile / 'files').mkdir(parents=True)
                (profile / 'config.diff').write_text('CONFIG_TEST=y\n')
                (profile / 'custom.sh').write_text('[ "$FAIL" != custom ] || exit 19\n')
                feeds = source / 'scripts/feeds'
                feeds.write_text('#!/bin/bash\nprintf "feeds %s\\n" "$*" >> "$LOG"\n'
                                 '[ "$1" != "$FAIL" ] || exit 19\n'
                                 'if [ "$*" = "list -s" ]; then printf "luci src-git %s fixture-url\\n" "$FEED_SHA"; fi\n')
                feeds.chmod(0o755)
                env = dict(os.environ, DK_OPENWRT=str(source), DK_BIN=str(base / 'bin'),
                           DK_PROFILE=str(profile), GITHUB_OUTPUT=str(base / 'output'),
                           IMAGE_ID='fixture-image', LOG=str(base / 'calls'), FAIL=phase,
                           SOURCE_SHA='1' * 40, FEED_SHA='2' * 40)
                stub = '''
                docker_exec() { shift; "$@"; }
                git() {
                  printf 'git %s\\n' "$*" >> "$LOG"
                  [ "$1" != "$FAIL" ] || return 19
                  if [ "$*" = 'rev-parse HEAD' ]; then
                    [ "$FAIL" != revision ] || return 19
                    printf '%s\\n' "$SOURCE_SHA"
                  fi
                }
                mountpoint() { :; }
                make() { [ "$1" != "$FAIL" ] || return 19; }
                python3() { printf 'key\\n' >> "$LOG"; printf 'fixture-key\\n'; }
                export -f git mountpoint make python3
                '''
                result = subprocess.run(['bash', '-eo', 'pipefail', '-c', stub + block],
                                        cwd=base, env=env, text=True, capture_output=True)
                expected = 1 if phase in ('update', 'install', 'download') else (19 if phase else 0)
                self.assertEqual(result.returncode, expected, result.stderr)
                calls = (base / 'calls').read_text()
                if phase:
                    self.assertNotIn('\nkey\n', '\n' + calls)
                    self.assertFalse((base / 'output').exists())
                else:
                    self.assertIn('Source: ' + env['SOURCE_SHA'], result.stdout)
                    self.assertIn('luci src-git ' + env['FEED_SHA'], result.stdout)
                    self.assertIn('feeds list -s\n', calls)
                    self.assertEqual((source / '.config').read_text(), 'CONFIG_TEST=y\nCONFIG_VERSION_NUMBER=ubi2\n')
                    self.assertEqual((base / 'output').read_text(), 'key=tc-v3-ubi2-fixture-key\n')

    def test_custom_donor_checkouts(self):
        script = (ROOT / 'user/default/custom.sh').read_text()
        packages = script[script.index('PKG_REPO='):script.index('# Existing W1700K custom files')]
        aurora = script[script.index('for pkg in luci-theme-aurora'):script.index('# 修改 Aurora')]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            donor = base / 'donor'
            donor.mkdir()
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=donor, text=True, stderr=subprocess.DEVNULL).strip()
            git('init')
            for pkg in ('luci-app-wifi7', 'luci-app-airoha-npu', 'luci-app-airoha-flowsense', 'luci-app-airoha-fancontrol'):
                (donor / pkg).mkdir()
                (donor / pkg / 'Makefile').write_text('# fixture\n')
            (donor / 'Makefile').write_text('# theme fixture\n')
            git('add', '.')
            git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
            sha = git('rev-parse', 'HEAD')
            for failure in ('', 'clone', 'revision'):
                with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir=base) as work:
                    work = Path(work)
                    (work / 'package').mkdir()
                    # Redirect fixed staging and remote clones; rev-parse uses real Git.
                    block = packages.replace('/tmp/yahuisme-packages', str(work / 'donor-clone')) + aurora
                    stub = '''git() {
                      if [ "$1" = clone ]; then
                        [ "$FAIL" != clone ] || return 19
                        command git clone --quiet "$DONOR" "${@: -1}"
                      else
                        [ "$FAIL" != revision ] || return 19
                        command git "$@"
                      fi
                    }
                    '''
                    result = subprocess.run(['bash', '-e', '-c', stub + block], cwd=work,
                                            env=dict(os.environ, DONOR=str(donor), FAIL=failure),
                                            text=True, capture_output=True)
                    if failure:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn('installed successfully.', result.stdout)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.count(sha), 3, result.stdout)
                        self.assertIn('yahuisme/packages: ' + sha, result.stdout)
                        for pkg in ('luci-theme-aurora', 'luci-app-aurora-config'):
                            self.assertIn(pkg + ': ' + sha, result.stdout)
