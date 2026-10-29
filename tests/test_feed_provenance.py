"""Feed provenance must fail closed without discarding valid partial records."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_record_contract


class FeedProvenanceTests(unittest.TestCase):
    def test_configured_feed_cannot_be_silently_omitted(self):
        fixture = test_record_contract.RecordContract()
        for config in ('feeds.conf', 'feeds.conf.default'):
            for fault in ('missing-directory', 'missing-git', 'missing-origin'):
                with self.subTest(config=config, fault=fault), tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    fixture.fixture(base)
                    (base / config).write_text(
                        'src-git packages https://example.invalid/packages\n'
                        'src-git-full luci https://example.invalid/luci\n')
                    luci = base / 'feeds/luci'
                    if fault == 'missing-git':
                        luci.mkdir()
                    elif fault == 'missing-origin':
                        shutil.copytree(base / 'feeds/packages', luci)
                        subprocess.run(['git', '-C', str(luci), 'remote', 'remove', 'origin'], check=True)
                    result = fixture.run_record(base)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    errors = json.loads((base / 'record/diagnostics.json').read_text())['errors']
                    self.assertIn('Git revision unavailable: feed/luci', errors)
                    record = json.loads((base / 'record/build.json').read_text())
                    self.assertEqual([row['name'] for row in record['feeds']], ['feed/packages'])
                    self.assertIsNotNone(record['source'])
                    self.assertTrue(record['images'])
                    self.assertEqual([r['name'] for r in record['custom_sources']], ['custom/yahuisme/packages'])
                    self.assertIsNotNone(record['external_packages'])
                    self.assertEqual((base / 'record/final.config').read_bytes(), (base / '.config').read_bytes())

    def test_all_five_feed_identities_survive_index_links_and_git_worktrees(self):
        fixture = test_record_contract.RecordContract()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture.fixture(base)
            names = ('packages', 'luci', 'routing', 'telephony', 'video')
            packages = base / 'feeds/packages'
            for name in names[1:]:
                subprocess.run(['git', '-C', str(packages), 'worktree', 'add', '-q',
                                '--detach', str(base / 'feeds' / name)], check=True)
            (base / 'feeds.conf.default').write_text(''.join(
                f'src-git{ "-full" if name == "luci" else ""} {name} https://example.invalid/{name}\n'
                for name in names))
            for name in names:
                (base / 'feeds' / (name + '.index')).symlink_to(name + '.tmp/.packageinfo')
            result = fixture.run_record(base)
            self.assertEqual(result.returncode, 0, result.stderr)
            feeds = json.loads((base / 'record/build.json').read_text())['feeds']
            self.assertEqual([row['name'] for row in feeds], ['feed/' + name for name in sorted(names)])
            for row in feeds:
                actual = subprocess.check_output(['git', '-C', str(base / 'feeds' / row['name'][5:]),
                                                  'rev-parse', 'HEAD'], text=True).strip()
                self.assertEqual(row['sha'], actual)
                self.assertEqual(row['url'], 'https://example.invalid/local')

    def test_active_feed_config_overrides_default_and_ignores_indexes(self):
        fixture = test_record_contract.RecordContract()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixture.fixture(base)
            (base / 'feeds.conf').write_text(
                '# src-git disabled https://example.invalid/disabled\n'
                'src-git-full packages https://example.invalid/packages;stable\n')
            (base / 'feeds.conf.default').write_text('src-git absent https://example.invalid/absent\n')
            metadata = base / 'feeds/packages.tmp'
            metadata.mkdir()
            (metadata / '.packageinfo').write_text('fixture index\n')
            (base / 'feeds/packages.index').symlink_to('packages.tmp/.packageinfo')
            (base / 'feeds/packages.targetindex').symlink_to('packages.tmp/.targetinfo')
            result = fixture.run_record(base)
            self.assertEqual(result.returncode, 0, result.stderr)
            revisions = json.loads((base / 'record/revisions.json').read_text())
            self.assertEqual([row['name'] for row in revisions], ['source', 'feed/packages', 'custom/yahuisme/packages'])
            self.assertEqual(json.loads((base / 'record/diagnostics.json').read_text())['errors'], [])
