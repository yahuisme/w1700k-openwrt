"""Execute the complete publish shell with local gh, real jq and no network."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_cache_workflow import step, ROOT
from record_fixture import READBACK

BLOCK = step('Publish firmware and prune releases')['run']
PREFIX_MATCH = re.search(r'PREFIX="([^"]+)"', BLOCK)
assert PREFIX_MATCH is not None
PREFIX = PREFIX_MATCH[1]
CURRENT = PREFIX[:-1] + '-r1-current'
API = ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']
GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path('calls').open('a') as f:
    f.write(json.dumps(args) + '\\n')
if args == ['api', 'repos/fixture/repo/git/ref/heads/main', '--jq', '.object.sha']:
    print(os.environ['GITHUB_SHA'])
elif args == ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']:
    print(Path('pages.json').read_text())
    sys.exit(19 if os.environ['FAULT'] == 'list' else 0)
elif args[0] == 'api' and '/releases/tags/' in args[1]:
''' + READBACK + '''
elif args[:2] == ['release', 'create']:
    sys.exit(17 if os.environ['FAULT'] == 'create' else 0)
elif args[:2] == ['release', 'delete']:
    assert len(args) == 5 and args[3:] == ['--cleanup-tag', '-y']
    sys.exit(23 if os.environ['FAULT'] == 'delete' else 0)
else:
    sys.exit(99)
'''


def release(tag: str, day: int) -> dict:
    return dict(tag_name=tag, published_at=f'2026-01-{day:02d}T00:00:00Z',
                id=day, draft=False, prerelease=False)


class RetentionTests(unittest.TestCase):
    def replay(self, pages, expected=(), fault='', success=True):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'scripts').symlink_to(ROOT / 'scripts')
            (base / 'firmware').mkdir()
            (base / 'firmware/version.txt').write_text(CURRENT + '\n')
            (base / 'firmware/release-notes.md').write_text('fixture')
            (base / 'firmware/fixture-sysupgrade.itb').write_text('not firmware')
            (base / 'gh').write_text(GH)
            (base / 'gh').chmod(0o755)
            (base / 'pages.json').write_text(pages if isinstance(pages, str) else json.dumps(pages))
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='fixture/repo', FAULT=fault)
            result = subprocess.run(['bash', '-eo', 'pipefail', '-c', BLOCK],
                                    cwd=base, env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            self.assertEqual([c[2] for c in calls if c[:2] == ['release', 'delete']], list(expected))
            self.assertEqual(API in calls, fault != 'create')
            create = next(c for c in calls if c[:2] == ['release', 'create'])
            self.assertEqual(create[2], CURRENT)
            self.assertEqual(create[create.index('--target') + 1], 'a' * 40)
            self.assertEqual(create[create.index('--title') + 1], CURRENT.rsplit('-', 1)[0] + '_current')
            if API in calls:
                self.assertLess(calls.index(create), calls.index(API))
            return result

    def test_zero_releases(self):
        self.assertIn('retaining all releases', self.replay([[]]).stdout)

    def test_one_release(self):
        self.replay([[release(CURRENT, 3)]])

    def test_two_releases(self):
        self.replay([[release(PREFIX + 'old', 1), release(CURRENT, 3)]])

    def test_three_releases_sorted_by_publication_not_revision(self):
        old = PREFIX[:-1] + '-r999999-old'
        self.replay([[release(old, 1), release(CURRENT, 3), release(PREFIX + 'previous', 2)]], [old])

    def test_multiple_pages_filter_before_global_sort(self):
        others = [release(f'unrelated-{i}', 20) for i in range(100)]
        old = PREFIX + 'old'
        previous = PREFIX + 'previous'
        self.replay([others, [release(old, 1), release(previous, 2)], [release(CURRENT, 3)]], [old])

    def test_other_series_retired_oc_draft_prerelease_protected(self):
        protected = [release(t, 20) for t in (
            'unrelated', 'MX4200-ImmortalWrt-r9-old', 'W1700K-ubi2-oc_old',
            PREFIX[:-1] + '-OC_old', PREFIX[:-1] + '-OC-r9-old',
            'W1700K-OC-Immortalwrt_old',
            'W1700K-ImmortalWrt_old' if 'OpenWrt' in PREFIX else 'W1700K-OpenWrt_old')]
        draft = release(PREFIX + 'draft', 21)
        draft['draft'] = True
        pre = release(PREFIX + 'pre', 22)
        pre['prerelease'] = True
        old = 'W1700K-ubi2_old'
        self.replay([protected + [draft, pre, release(old, 1),
                                 release(PREFIX + 'previous', 2), release(CURRENT, 3)]], [old])

    def test_current_outside_newest_two_is_never_deleted(self):
        self.replay([[release(PREFIX + 'newest', 4), release(PREFIX + 'second', 3),
                      release(CURRENT, 2), release(PREFIX + 'old', 1)]],
                    [PREFIX + 'second', PREFIX + 'old'])

    def test_missing_current_skips_cleanup(self):
        result = self.replay([[release(PREFIX + str(i), i) for i in range(1, 5)]])
        self.assertIn('retaining all releases', result.stdout)

    def test_create_failure_prevents_listing_and_deletion(self):
        self.replay([[release(CURRENT, 3), release(PREFIX + 'previous', 2),
                      release(PREFIX + 'old', 1)]], fault='create', success=False)

    def test_partial_listing_failure_cannot_delete(self):
        self.replay([[release(CURRENT, 3), release(PREFIX + 'previous', 2),
                      release(PREFIX + 'old', 1)]], fault='list')

    def test_malformed_listing_cannot_delete(self):
        self.replay('[[{')

    def test_equal_publication_uses_id_tiebreak(self):
        old, previous = release(PREFIX + 'old', 2), release(PREFIX + 'previous', 2)
        old['id'], previous['id'] = 1, 2
        self.replay([[old, release(CURRENT, 3), previous]], [old['tag_name']])

    def test_deletion_failure_warns_without_failing_publication(self):
        result = self.replay([[release(CURRENT, 4), release(PREFIX + 'previous', 3),
                      release(PREFIX + 'old', 2), release(PREFIX + 'oldest', 1)]],
                    [PREFIX + 'old', PREFIX + 'oldest'], fault='delete')
        self.assertIn('::warning::Failed to delete release', result.stdout)
