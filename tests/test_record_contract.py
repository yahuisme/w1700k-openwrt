"""Shared record/publication contract; no network, Docker or compilation."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from record_fixture import external_provenance

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class RecordContract(unittest.TestCase):
    def fixture(self, base):
        profile = json.loads((ROOT / 'user/default/build.json').read_text())
        for path in (base, base / 'feeds/packages'):
            path.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'init', '-q', str(path)], check=True)
            subprocess.run(['git', '-C', str(path), '-c', 'user.name=Fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture', '--allow-empty'], check=True)
            subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', 'https://example.invalid/local'], check=True)
        (base / '.config').write_text('CONFIG_FIXTURE=y\n')
        (base / '.custom-revisions.tsv').write_text(''.join(
            f'{name}\thttps://example.invalid/{name}\t' + 'a' * 40 + '\n'
            for name in ('yahuisme/packages',)))
        external_provenance(base)
        target = base / 'bin/targets' / profile['target']
        target.mkdir(parents=True)
        manifest = next(name for name in profile['images'] if name.endswith('-squashfs-sysupgrade.itb'))
        (target / (manifest.removesuffix('-squashfs-sysupgrade.itb') + '.manifest')).write_text('fixture - 1\n')
        (target / 'profiles.json').write_text('{}\n')
        paths = [target / name for name in profile['images']]
        for path in paths:
            path.write_bytes(b'fixture image')
        return profile, paths

    def test_only_the_expected_device_manifest_satisfies_record(self):
        for state in ('valid', 'missing', 'empty', 'symlink'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                profile, paths = self.fixture(base)
                directory = paths[0].parent
                manifest, = directory.glob('*.manifest')
                peer = directory / manifest.name.replace('gemtek_w1700k-ubi', 'other_device')
                peer.write_text('other device - 1\n')
                if state == 'missing':
                    manifest.unlink()
                elif state == 'empty':
                    manifest.write_text('')
                elif state == 'symlink':
                    manifest.unlink()
                    manifest.symlink_to(peer.name)

                result = self.run_record(base)
                record = base / 'record'
                errors = json.loads((record / 'diagnostics.json').read_text())['errors']
                self.assertEqual(result.returncode == 0, state == 'valid', result.stderr)
                recorded = record / 'targets' / profile['target']
                if state == 'valid':
                    self.assertEqual(errors, [])
                    self.assertEqual((recorded / manifest.name).read_bytes(), manifest.read_bytes())
                else:
                    self.assertTrue(any(manifest.name in error for error in errors), errors)
                    self.assertFalse((recorded / manifest.name).exists())
                self.assertFalse((recorded / peer.name).exists())
                self.assertTrue((recorded / 'profiles.json').is_file())
                self.assertTrue(json.loads((record / 'build.json').read_text())['images'])

    def run_record(self, base):
        return subprocess.run(['python3', str(ROOT / 'scripts/build_record.py'), str(base),
                               str(base / 'record')], capture_output=True, text=True)

    def test_versioned_record_and_legacy_revisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            profile, paths = self.fixture(base)
            (base / 'record').mkdir()
            environment = dict(repository='fixture/recipe', workflow_sha='b' * 40, run_id='1', run_attempt='2',
                               runner_os='Linux', runner_arch='ARM64', image_id='sha256:' + 'c' * 64,
                               builder_fingerprint='d' * 64)
            (base / 'record/environment.txt').write_text(''.join(f'{k}={v}\n' for k, v in environment.items()))
            result = self.run_record(base)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads((base / 'record/build.json').read_text())
            revisions = json.loads((base / 'record/revisions.json').read_text())
            self.assertEqual(record['version'], 1)
            self.assertEqual(record['recipe']['workflow_sha'], 'b' * 40)
            self.assertEqual(record['builder']['image_id'], environment['image_id'])
            self.assertEqual(record['source'], revisions[0])
            self.assertEqual(record['feeds'] + record['custom_sources'], revisions[1:])
            self.assertEqual([row['name'] for row in record['custom_sources']], ['custom/yahuisme/packages'])
            self.assertEqual(record['external_packages'], json.loads((base / '.external-packages/provenance.json').read_text()))
            self.assertEqual((base / 'record/external-packages.json').read_bytes(),
                             (base / '.external-packages/provenance.json').read_bytes())
            self.assertEqual(record['target'], profile['target'])
            self.assertEqual(record['config']['digest'], 'sha256:' + hashlib.sha256((base / '.config').read_bytes()).hexdigest())
            self.assertEqual({e['name'] for e in record['images']}, {p.name for p in paths})
            self.assertEqual(json.loads((base / 'record/diagnostics.json').read_text()), dict(errors=[], warnings=[]))
            self.assertFalse((base / 'record/images.json').exists())
            self.assertFalse((base / 'record/source-revisions.txt').exists())

    def test_external_metadata_failures_keep_git_and_raw_provenance(self):
        mutations = {
            'json': lambda r: None,
            'version': lambda r: r.update(version=True),
            'architecture': lambda r: r.update(architecture='wrong'),
            'repository-missing': lambda r: r.update(repositories=[]),
            'repository-duplicate': lambda r: r['repositories'].append(r['repositories'][0]),
            'repository-name': lambda r: r['repositories'][0].update(name='wrong'),
            'repository-url': lambda r: r['repositories'][0].update(url='http://example.invalid'),
            'repository-credentials': lambda r: r['repositories'][0].update(url='https://user:pass@example.invalid'),
            'index-digest': lambda r: r['repositories'][0].update(index_sha256='x' * 64),
            'key-digest': lambda r: r['repositories'][0].update(key_sha256=None),
            'package-missing': lambda r: r['packages'].pop(),
            'package-duplicate': lambda r: r['packages'].append(r['packages'][0]),
            'package-name': lambda r: r['packages'][0].update(name='wrong'),
            'package-version': lambda r: r['packages'][0].update(version=''),
            'package-arch': lambda r: r['packages'][0].update(arch='wrong'),
            'package-repository': lambda r: r['packages'][0].update(repository='wrong'),
            'package-filename': lambda r: r['packages'][0].update(filename='../payload.apk'),
            'package-digest': lambda r: r['packages'][0].update(sha256='invalid'),
        }
        for fault, mutate in mutations.items():
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                self.fixture(base)
                path = base / '.external-packages/provenance.json'
                external = json.loads(path.read_text())
                mutate(external)
                path.write_text('{' if fault == 'json' else json.dumps(external))
                result = self.run_record(base)
                self.assertNotEqual(result.returncode, 0)
                record = json.loads((base / 'record/build.json').read_text())
                self.assertIsNone(record['external_packages'])
                self.assertEqual([r['name'] for r in record['custom_sources']], ['custom/yahuisme/packages'])
                self.assertEqual((base / 'record/external-packages.json').read_bytes(), path.read_bytes())
                self.assertTrue(record['config'])
                self.assertTrue(record['images'])
                errors = json.loads((base / 'record/diagnostics.json').read_text())['errors']
                self.assertTrue(any(e.startswith('External package provenance invalid:') for e in errors), errors)

    def test_obsolete_aurora_git_rows_rejected_without_losing_apk_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.fixture(base)
            path = base / '.custom-revisions.tsv'
            path.write_text(path.read_text() + 'luci-theme-aurora\thttps://example.invalid/aurora\t' + 'a' * 40 + '\n')
            result = self.run_record(base)
            self.assertNotEqual(result.returncode, 0)
            record = json.loads((base / 'record/build.json').read_text())
            self.assertEqual(record['custom_sources'], [])
            self.assertIsNotNone(record['external_packages'])

    def test_partial_failures_keep_config_revisions_and_diagnostics(self):
        for fault in ('empty', 'symlink', 'extra', 'wrong-name', 'missing', 'profiles', 'custom', 'git'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                profile, paths = self.fixture(base)
                image = paths[0]
                if fault == 'empty': image.write_bytes(b'')
                if fault == 'symlink':
                    image.rename(image.parent / 'payload')
                    image.symlink_to('payload')
                if fault == 'extra': (image.parent / ('extra-' + image.name)).write_bytes(b'extra')
                if fault == 'wrong-name': image.rename(image.parent / ('wrong-' + image.name))
                if fault == 'missing': image.unlink()
                if fault == 'profiles': (image.parent / 'profiles.json').unlink()
                if fault == 'custom': (base / '.custom-revisions.tsv').write_text('\n')
                if fault == 'git': (base / '.git').rename(base / 'hidden-git')
                result = self.run_record(base)
                self.assertNotEqual(result.returncode, 0)
                record = json.loads((base / 'record/build.json').read_text())
                self.assertIsNotNone(record['config'])
                self.assertTrue(json.loads((base / 'record/diagnostics.json').read_text())['errors'])
                self.assertTrue((base / 'record/revisions.json').exists())

    def test_explicit_profile_and_missing_profile_fail_closed(self):
        helper = module('build_profile')
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DK_PROFILE=tmp):
            with self.assertRaises(OSError): helper.load()
            data = json.loads((ROOT / 'user/default/build.json').read_text())
            (Path(tmp) / 'build.json').write_text(json.dumps(data))
            self.assertEqual(helper.load(), data)

    @staticmethod
    def freeze_assets(base, assets):
        proof = base / 'accepted-images.json'
        raw = json.dumps(dict(version=1, images=[
            {key: asset[key] for key in ('name', 'size', 'digest')} for asset in assets])).encode()
        proof.write_bytes(raw)
        return proof, hashlib.sha256(raw).hexdigest()

    def test_readback_contract(self):
        helper = module('verify_release')
        for fault in ('ok', 'missing', 'extra', 'duplicate', 'name', 'size', 'state', 'digest',
                      'tag', 'release-id', 'draft', 'prerelease', 'download', 'download-wrong', 'download-failure',
                      'digest-installer', 'digest-chainloader'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                profile, paths = self.fixture(base)
                digest = 'sha256:' + hashlib.sha256(b'fixture image').hexdigest()
                assets = [dict(id=i, name=p.name, size=p.stat().st_size, state='uploaded', digest=digest)
                          for i, p in enumerate(paths, 1)]
                proof = self.freeze_assets(base, assets)
                release = dict(id=1000, tag_name='tag/a', name='tag/a', draft=False, prerelease=False, assets=assets)
                if fault == 'missing': assets.pop()
                if fault == 'extra': assets.append(dict(assets[0], name='extra'))
                if fault == 'duplicate': assets.append(dict(assets[0]))
                if fault == 'name': assets[0]['name'] = 'wrong'
                if fault == 'size': assets[0]['size'] += 1
                if fault == 'state': assets[0]['state'] = 'new'
                if fault == 'digest': assets[0]['digest'] = 'sha256:' + '0' * 64
                if fault in ('digest-installer', 'digest-chainloader'):
                    token = 'installer' if fault == 'digest-installer' else 'chainload-uboot'
                    next(asset for asset in assets if token in asset['name'])['digest'] = 'sha256:' + '0' * 64
                if fault == 'tag': release['tag_name'] = 'wrong'
                if fault == 'release-id': release['id'] = True
                if fault in ('draft', 'prerelease'): release[fault] = True
                if fault.startswith('download'):
                    for asset in assets: asset.pop('digest')
                class Download:
                    stdout = io.BytesIO(b'wrong' if fault == 'download-wrong' else b'fixture image')
                    def __enter__(self):
                        self.stdout = io.BytesIO(b'wrong' if fault == 'download-wrong' else b'fixture image')
                        return self
                    def __exit__(self, *args): self.stdout.close()
                    def wait(self): return 17 if fault == 'download-failure' else 0
                with patch.dict(os.environ, GITHUB_REPOSITORY='fixture/repo', GITHUB_SHA='a' * 40), \
                     patch.object(helper.subprocess, 'check_output', side_effect=[json.dumps(release).encode(),
                         json.dumps(dict(object=dict(type='commit', sha='a' * 40))).encode()]) as api, \
                     patch.object(helper.subprocess, 'Popen', side_effect=lambda *a, **k: Download()) as download, \
                     contextlib.redirect_stdout(io.StringIO()):
                    if fault in ('ok', 'download'):
                        self.assertEqual(helper.verify('tag/a', *proof), 1000)
                        self.assertIn('/tags/tag%2Fa', api.call_args[0][0][-1])
                        self.assertEqual(download.call_count, len(paths) if fault == 'download' else 0)
                    else:
                        with self.assertRaises(ValueError): helper.verify('tag/a', *proof)

    def test_title_full_workflow_sha_and_bounded_real_tag_identity(self):
        helper = module('verify_release')
        cases = ('lightweight', 'wrong-target-commitish', 'annotated', 'ten-tags',
                 'title', 'missing-title', 'wrong-commit', 'missing-object',
                 'malformed-sha', 'non-tag', 'cycle', 'eleven-tags', 'tag-api-failure',
                 'missing-workflow-sha', 'short-workflow-sha', 'invalid-workflow-sha')
        good = {'lightweight', 'wrong-target-commitish', 'annotated', 'ten-tags'}
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                _, paths = self.fixture(Path(tmp))
                release = dict(id=1000, tag_name='tag/a', name='tag/a', draft=False, prerelease=False,
                               target_commitish='b' * 40 if case == 'wrong-target-commitish' else 'a' * 40,
                               assets=[dict(name=p.name, size=p.stat().st_size, state='uploaded',
                                            digest='sha256:' + hashlib.sha256(p.read_bytes()).hexdigest())
                                       for p in paths])
                proof = self.freeze_assets(Path(tmp), release['assets'])
                if case == 'title': release['name'] = 'wrong'
                if case == 'missing-title': release.pop('name')
                workflow_sha = {'missing-workflow-sha': '', 'short-workflow-sha': 'a' * 7,
                                'invalid-workflow-sha': 'g' * 40}.get(case, 'a' * 40)
                tag_count = 10 if case == 'ten-tags' else 11 if case == 'eleven-tags' else 1
                reads = []
                def api(command):
                    endpoint = command[-1]
                    reads.append(endpoint)
                    if '/releases/tags/' in endpoint:
                        self.assertTrue(endpoint.endswith('tag%2Fa'))
                        return json.dumps(release).encode()
                    if '/git/ref/tags/' in endpoint:
                        self.assertTrue(endpoint.endswith('tag%2Fa'))
                        if case == 'tag-api-failure':
                            raise subprocess.CalledProcessError(17, command)
                        if case == 'missing-object': return b'{}'
                        target = dict(type='commit', sha='a' * 40)
                        if case == 'wrong-commit': target['sha'] = 'b' * 40
                        if case == 'malformed-sha': target['sha'] = 'a' * 7
                        if case == 'non-tag': target['type'] = 'tree'
                        if case in ('annotated', 'cycle', 'ten-tags', 'eleven-tags'):
                            target = dict(type='tag', sha=f'{1:040x}')
                        return json.dumps(dict(object=target)).encode()
                    self.assertIn('/git/tags/', endpoint)
                    depth = int(endpoint.rsplit('/', 1)[1], 16)
                    if case == 'cycle': target = dict(type='tag', sha=f'{1:040x}')
                    elif depth < tag_count: target = dict(type='tag', sha=f'{depth + 1:040x}')
                    else: target = dict(type='commit', sha='a' * 40)
                    return json.dumps(dict(object=target)).encode()
                with patch.dict(os.environ, GITHUB_REPOSITORY='fixture/repo', GITHUB_SHA=workflow_sha), \
                     patch.object(helper.subprocess, 'check_output', side_effect=api), \
                     contextlib.redirect_stdout(io.StringIO()):
                    if case in good:
                        helper.verify('tag/a', *proof)
                    else:
                        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                            helper.verify('tag/a', *proof)
                if case.endswith('workflow-sha'):
                    self.assertEqual(reads, [])
                self.assertLessEqual(sum('/git/tags/' in endpoint for endpoint in reads), 10)

    def test_invalid_acceptance_rejected_before_api(self):
        helper = module('verify_release')
        for fault in ('empty-list', 'duplicate', 'missing-image', 'name', 'size', 'digest',
                      'symlink', 'changed-proof', 'missing-proof'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                _, paths = self.fixture(base)
                rows: list[dict[str, str | int]] = [dict(name=p.name, size=p.stat().st_size,
                             digest='sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
                if fault == 'empty-list': rows.clear()
                if fault == 'duplicate': rows[0] = rows[1]
                if fault == 'missing-image': rows.pop()
                if fault == 'name': rows[0]['name'] = 'wrong.itb'
                if fault == 'size': rows[0]['size'] = 0
                if fault == 'digest': rows[0]['digest'] = 'invalid'
                proof, binding = self.freeze_assets(base, rows)
                if fault == 'symlink':
                    proof.rename(base / 'target.json')
                    proof.symlink_to('target.json')
                if fault == 'changed-proof': proof.write_bytes(proof.read_bytes() + b'\n')
                if fault == 'missing-proof': proof.unlink()
                with patch.object(helper.subprocess, 'check_output') as api:
                    with self.assertRaises(ValueError): helper.verify('tag', proof, binding)
                    api.assert_not_called()
