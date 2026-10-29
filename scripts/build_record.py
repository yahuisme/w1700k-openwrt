#!/usr/bin/env python3
"""Collect compact build provenance, retaining partial evidence on failure."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

try:
    from .build_profile import load
    from .firmware_images import collect as collect_images
    from .external_packages import ARCH, REPOSITORIES
except ImportError:
    # Also support direct execution and importlib file-based test loaders.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_profile import load
    from firmware_images import collect as collect_images
    from external_packages import ARCH, REPOSITORIES


def validate_external(record):
    """Validate snapshot metadata, not Git identities or APK signatures anew."""
    if (not isinstance(record, dict) or type(record.get('version')) is not int
            or record['version'] != 1 or record.get('architecture') != ARCH):
        raise ValueError('Expected provenance version 1 and architecture ' + ARCH)

    def rows(field, expected):
        values = record.get(field)
        if (not isinstance(values, list) or len(values) != len(expected)
                or any(not isinstance(row, dict) or not isinstance(row.get('name'), str)
                       for row in values)
                or {row['name'] for row in values} != set(expected)):
            raise ValueError('Incomplete or duplicate external ' + field)
        return values

    def sha256(value, label):
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
            raise ValueError('Invalid SHA-256: ' + label)

    for row in rows('repositories', REPOSITORIES):
        url = row.get('url')
        if not isinstance(url, str) or any(char.isspace() for char in url):
            raise ValueError('Invalid HTTPS repository URL: ' + row['name'])
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError('Invalid HTTPS repository URL: ' + row['name'])
        for field in ('index_sha256', 'key_sha256'):
            sha256(row.get(field), row['name'] + '/' + field)

    expected = {name: tag for tag, repo in REPOSITORIES.items() for name in repo['packages']}
    for row in rows('packages', expected):
        name, version = row['name'], row.get('version')
        if (not isinstance(version, str) or not version.strip()
                or row.get('arch') not in (ARCH, 'noarch')
                or row.get('repository') != expected[name]):
            raise ValueError('Invalid external package identity: ' + name)
        filename = row.get('filename')
        if (not isinstance(filename, str) or filename != f'{name}-{version}.apk'
                or not re.fullmatch(r'[A-Za-z0-9_.+~\-]+\.apk', filename)):
            raise ValueError('Invalid external APK filename: ' + name)
        sha256(row.get('sha256'), name)
    return record


def collect(source, destination):
    os.umask(0o022)
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    errors, warnings, revisions = [], [], []

    def write(name, data):
        try:
            (destination / name).write_text(data)
        except OSError as exc:
            errors.append(f'Write failed: {name}: {exc}')

    def copy(path, name):
        try:
            if not path.is_file() or not path.stat().st_size:
                errors.append('Missing or empty: ' + str(path))
                return
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        except OSError as exc:
            errors.append(f'Copy failed: {path}: {exc}')

    def revision(label, path):
        try:
            sha = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'], text=True).strip()
            url = subprocess.check_output(['git', '-C', str(path), 'remote', 'get-url', 'origin'], text=True).strip()
            if not re.fullmatch(r'[0-9a-f]{40}', sha) or not url:
                raise ValueError('invalid revision')
            revisions.append(dict(name=label, url=url, sha=sha))
        except (OSError, ValueError, subprocess.CalledProcessError):
            errors.append('Git revision unavailable: ' + label)

    try:
        profile = load(Path(__file__).resolve().parents[1] / 'user/default')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        profile = None
        errors.append('Build profile unavailable: ' + str(exc))
    try:
        inventory = subprocess.check_output(
            ['dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\n'], text=True)
        if not inventory.strip():
            errors.append('Empty container package inventory')
        write('dpkg-packages.tsv', '\n'.join(sorted(inventory.splitlines())) + '\n')
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f'Container package inventory failed: {exc}')

    revision('source', source)
    feeds = {p.name for p in (source / 'feeds').glob('*') if (p / '.git').exists()}
    # The configured inventory must not shrink when one checkout loses .git.
    # feeds.conf overrides the default, just as it does for scripts/feeds.
    feed_config = source / 'feeds.conf'
    if not feed_config.exists():
        feed_config = source / 'feeds.conf.default'
    if feed_config.exists():
        try:
            feeds.update(re.findall(r'^\s*src-git(?:-full)?\s+([\w-]+)\s+',
                                    feed_config.read_text(), re.M))
        except OSError as exc:
            errors.append(f'Feed configuration unavailable: {exc}')
    if not feeds:
        errors.append('No Git feed revisions')
    for name in sorted(feeds):
        feed = source / 'feeds' / name
        # Without this guard Git can silently return the parent source identity.
        if not (feed / '.git').exists():
            errors.append('Git revision unavailable: feed/' + name)
        else:
            revision('feed/' + name, feed)
    copy(source / '.config', 'final.config')
    copy(source / '.custom-revisions.tsv', 'custom-revisions.tsv')
    provenance = source / '.external-packages/provenance.json'
    copy(provenance, 'external-packages.json')
    for name in ('feeds.conf', 'feeds.conf.default'):
        if (source / name).is_file():
            copy(source / name, name)
    custom = []
    try:
        rows = [line.split('\t') for line in (source / '.custom-revisions.tsv').read_text().splitlines()]
        names = {'yahuisme/packages'}
        if (len(rows) != len(names) or any(len(row) != 3 for row in rows)
                or {row[0] for row in rows if row} != names
                or any(not row[1] or not re.fullmatch(r'[0-9a-f]{40}', row[2])
                       for row in rows if len(row) == 3)):
            raise ValueError('Incomplete custom package revisions')
        custom = [dict(name='custom/' + name, url=url, sha=sha) for name, url, sha in rows]
    except (OSError, ValueError) as exc:
        errors.append('Custom revisions invalid: ' + str(exc))
    revisions.extend(custom)
    external = None
    try:
        external = validate_external(json.loads(provenance.read_text()))
    except (OSError, ValueError) as exc:
        errors.append('External package provenance invalid: ' + str(exc))
    write('revisions.json', json.dumps(revisions, indent=2) + '\n')

    targets = source / 'bin/targets'
    entries = []
    if profile:
        directory = targets / profile['target']
        manifests = sorted(directory.glob('*.manifest'))
        if not manifests:
            errors.append('No package manifest')
        for path in manifests + [directory / 'profiles.json']:
            copy(path, str(Path('targets') / path.relative_to(targets)))
        try:
            entries = collect_images(targets, profile)
        except (OSError, ValueError) as exc:
            errors.append('Firmware images invalid: ' + str(exc))
    write('sha256sums', ''.join(f"{e['digest'].removeprefix('sha256:')}  {profile['target']}/{e['name']}\n" for e in entries) if profile else '')

    environment = {}
    try:
        environment = dict(line.split('=', 1) for line in (destination / 'environment.txt').read_text().splitlines())
    except (OSError, ValueError):
        warnings.append('Runner environment record unavailable or malformed')
    def env(key, variable):
        return environment.get(key) or os.environ.get(variable)
    recipe = {key: env(key, var) for key, var in (
        ('repository', 'GITHUB_REPOSITORY'), ('workflow_sha', 'GITHUB_SHA'),
        ('run_id', 'GITHUB_RUN_ID'), ('run_attempt', 'GITHUB_RUN_ATTEMPT'))}
    builder = {key: env(key, var) for key, var in (
        ('runner_os', 'RUNNER_OS'), ('runner_arch', 'RUNNER_ARCH'),
        ('image_id', 'IMAGE_ID'), ('builder_fingerprint', 'BUILDER_FINGERPRINT'))}
    if not all(recipe.values()) or not all(builder.values()):
        warnings.append('Incomplete optional recipe/builder identity')
    config = None
    try:
        with (source / '.config').open('rb') as stream:
            config = dict(path='final.config', digest='sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest())
    except OSError:
        pass  # The missing/copy diagnostic was recorded above.
    record = dict(version=1, recipe=recipe, source=next((r for r in revisions if r['name'] == 'source'), None),
                  feeds=[r for r in revisions if r['name'].startswith('feed/')],
                  custom_sources=custom, external_packages=external,
                  builder=builder, config=config, images=entries)
    if profile:
        record.update(system=profile['system'], device=profile['device'], target=profile['target'])
    write('build.json', json.dumps(record, indent=2) + '\n')
    write('diagnostics.json', json.dumps(dict(errors=errors, warnings=warnings), indent=2) + '\n')
    for path in [destination, *destination.rglob('*')]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    if errors:
        raise SystemExit('; '.join(errors))


if __name__ == '__main__':
    collect(*sys.argv[1:])
