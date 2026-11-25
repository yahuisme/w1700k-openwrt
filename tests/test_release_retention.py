"""Execute the complete publish shell with local gh, real jq and no network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_cache_workflow import step, ROOT, MATRIX
from record_fixture import staged_images, acceptance, READBACK
from test_release_safety import IMAGE

BLOCK = step('Publish firmware and prune releases')['run']
PREFIX = f"W1700K-{MATRIX['title']}-"
CURRENT = PREFIX + 'r8-26.01.03_08.00.00'
OLD = PREFIX + 'r999999-26.01.01_08.00.00'
PREVIOUS = PREFIX + 'r7-26.01.02_08.00.00'
NEWER = PREFIX + 'r9-26.01.04_08.00.00'
API = ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']
GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path('calls').open('a') as f:
    f.write(json.dumps(args) + '\\n')
if args == ['api', 'repos/fixture/repo/git/ref/heads/main', '--jq', '.object.sha']:
    print('b' * 40 if Path('listed').exists() and os.environ['FAULT'] == 'advance-after-list' else os.environ['GITHUB_SHA'])
elif args == ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']:
    Path('listed').touch()
    print(Path('pages.json').read_text())
    sys.exit(19 if os.environ['FAULT'] == 'list' else 0)

elif args[0] == 'api' and '/releases/tags/' in args[1]:
''' + READBACK + '''
elif args[0] == 'api' and '/git/ref/tags/' in args[1]:
    print(json.dumps(dict(object=dict(type='commit',sha=os.environ['GITHUB_SHA']))))
elif args[:2] == ['release', 'create']:
    sys.exit(17 if os.environ['FAULT'] == 'create' else 0)
elif args[:2] == ['release', 'delete']:
    assert len(args) == 5 and args[3:] == ['--cleanup-tag', '-y']
    sys.exit(23 if os.environ['FAULT'] == 'delete' else 0)
else:
    sys.exit(99)
'''


def release(tag: str, day: int, *, id=None) -> dict:
    return dict(tag_name=tag, published_at=f'2026-01-{day:02d}T00:00:00Z',
                id=(1000 if tag == CURRENT else day) if id is None else id, draft=False, prerelease=False)


class RetentionTests(unittest.TestCase):
    def replay(self, pages, expected=(), fault='', success=True):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'scripts').symlink_to(ROOT / 'scripts')
            (base / 'firmware').mkdir()
            (base / 'firmware/version.txt').write_text(CURRENT + '\n')
            (base / 'firmware/release-notes.md').write_text('fixture')
            (base / 'firmware' / IMAGE).write_text('not firmware')
            staged_images(base)
            (base / 'gh').write_text(GH)
            (base / 'gh').chmod(0o755)
            (base / 'pages.json').write_text(pages if isinstance(pages, str) else json.dumps(pages))
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='fixture/repo', FAULT=fault,
                       SYSTEM=MATRIX['system'])
            self.assertIn('${{ steps.stage.outputs.acceptance }}', BLOCK)
            block = BLOCK.replace('${{ steps.stage.outputs.acceptance }}', acceptance(base))
            result = subprocess.run(['bash', '-eo', 'pipefail', '-c', block],
                                    cwd=base, env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in (base / 'calls').read_text().splitlines()]
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            self.assertCountEqual([c[2] for c in calls if c[:2] == ['release', 'delete']], expected)
            self.assertEqual(API in calls, fault != 'create')
            create = next(c for c in calls if c[:2] == ['release', 'create'])
            self.assertEqual(create[2], CURRENT)
            expected_images = json.loads((ROOT / 'user/default/build.json').read_text())['images']
            self.assertEqual({Path(arg).name for arg in create if arg.endswith('.itb')}, set(expected_images))
            self.assertEqual(create[create.index('--target') + 1], 'a' * 40)
            self.assertEqual(create[create.index('--title') + 1], CURRENT)
            if API in calls:
                self.assertLess(calls.index(create), calls.index(API))
            return result

    def test_zero_releases(self):
        self.assertIn('retaining all releases', self.replay([[]]).stdout)

    def test_one_release(self):
        self.replay([[release(CURRENT, 3)]])

    def test_current_plus_one_old_keeps_only_current(self):
        self.replay([[release(OLD, 1), release(CURRENT, 3)]], [OLD])

    def test_same_tag_replacement_after_asset_verification_keeps_older_releases(self):
        result = self.replay([[release(OLD, 1), release(CURRENT, 3, id=2000)]])
        self.assertIn('retaining all releases', result.stdout)

    def test_older_releases_deleted_regardless_of_revision(self):
        self.replay([[release(OLD, 1), release(CURRENT, 3), release(PREVIOUS, 2)]], [OLD, PREVIOUS])

    def test_multiple_pages_keep_protected_series(self):
        others = [release(f'unrelated-{i}', 20, id=i + 100) for i in range(98)]
        self.replay([others + [release(OLD, 1), release(PREVIOUS, 2)], [release(CURRENT, 3)]], [OLD, PREVIOUS])

    def test_other_series_retired_oc_draft_prerelease_protected(self):
        protected = [release(t, 20, id=i + 100) for i, t in enumerate((
            'unrelated', 'MX4200-ImmortalWrt-r9-old', 'W1700K-ubi2-oc_old',
            'W1700K-ubi2_oc-r9-old', 'W1700K-ubi2-OC_old', 'W1700K-ubi2_OC-r9-old',
            PREFIX[:-1] + '-OC_old', PREFIX[:-1] + '-OC-r9-old',
            'W1700K-OC-Immortalwrt_old',
            'W1700K-ImmortalWrt_old' if 'OpenWrt' in PREFIX else 'W1700K-OpenWrt_old',
            'W1700K-ImmortalWrt-r123-current' if MATRIX['system'] == 'openwrt' else 'W1700K-OpenWrt-r123-current',
            'W1700K-ImmortalWrt-r122-26.01.01_08.00.00' if MATRIX['system'] == 'openwrt' else 'W1700K-OpenWrt-r122-26.01.01_08.00.00'))]
        if MATRIX['system'] == 'immortalwrt':
            protected += [release('W1700K-ubi2_26.01.01-08.00.00_r1', 1, id=60),
                          release('W1700K-ubi2-r1-26.01.01_08.00.00', 1, id=61)]
        draft = release(PREFIX + 'r14-26.01.01_08.00.00', 1, id=21)
        draft['draft'] = True
        pre = release(PREFIX + 'r15-26.01.01_08.00.00', 1, id=22)
        pre['prerelease'] = True
        self.replay([protected + [draft, pre, release(OLD, 1),
                                 release(PREVIOUS, 2), release(CURRENT, 3)]], [PREVIOUS, OLD])

    def test_legacy_standard_forms_still_pruned(self):
        tags = [PREFIX[:-1] + '_26.01.01-08.00.00_r1', PREFIX + 'r2-26.01.01-08.00.00']
        if MATRIX['system'] == 'openwrt':
            tags += ['W1700K-ubi2_26.01.01-08.00.00_r1', 'W1700K-ubi2-r1-26.01.01_08.00.00']
        self.replay([[release(CURRENT, 3)] + [release(tag, 1, id=i + 10) for i, tag in enumerate(tags)]], tags)

    def test_preserves_newer_build_or_publication(self):
        self.replay([[release(NEWER, 1, id=10), release(PREVIOUS, 4),
                      release(CURRENT, 3), release(OLD, 1)]], [OLD])

    def test_abnormal_inventory_retains_all(self):
        current, old = release(CURRENT, 3), release(OLD, 1)
        for pages in ([[current], [old]], [[current, old, old]],
                      [[current, old, dict(old, id=10)]], [[current, old, dict(old, tag_name=PREVIOUS)]],
                      [[current, old, dict(release(PREVIOUS, 2), published_at='missing')]]):
            with self.subTest(pages=pages):
                self.assertIn('retaining all releases', self.replay(pages).stdout)

    def test_unknown_suffix_is_not_a_production_tag(self):
        self.replay([[release(PREFIX + 'r1-old', 1), release(PREFIX + 'r5-26.99.03_08.00.00', 2), release(CURRENT, 3)]])

    def test_main_advances_during_listing(self):
        self.replay([[release(OLD, 1), release(CURRENT, 3)]], fault='advance-after-list')

    def test_missing_current_skips_cleanup(self):
        result = self.replay([[release(PREFIX + f'r{i}-old', i) for i in range(1, 5)]])
        self.assertIn('retaining all releases', result.stdout)

    def test_create_failure_prevents_listing_and_deletion(self):
        self.replay([[release(CURRENT, 3), release(PREFIX + 'r2-previous', 2),
                      release(PREFIX + 'r1-old', 1)]], fault='create', success=False)

    def test_partial_listing_failure_cannot_delete(self):
        self.replay([[release(CURRENT, 3), release(PREFIX + 'r2-previous', 2),
                      release(PREFIX + 'r1-old', 1)]], fault='list')

    def test_malformed_listing_cannot_delete(self):
        self.replay('[[{')

    def test_equal_publication_or_build_time_does_not_prove_age(self):
        self.replay([[release(OLD, 3, id=4), release(CURRENT, 3),
                      release(PREFIX + 'r6-26.01.03_08.00.00', 2)]])

    def test_deletion_failure_warns_without_failing_publication(self):
        result = self.replay([[release(CURRENT, 4), release(PREVIOUS, 2), release(OLD, 1)]],
                             [PREVIOUS, OLD], fault='delete')
        self.assertIn('::warning::Failed to delete release', result.stdout)
