#!/usr/bin/env python3
"""Collect local build inputs/outputs; retain partial evidence on failure."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def collect(source, destination):
    # The collector runs as root in Docker; artifacts must be runner-readable.
    os.umask(0o022)
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    errors, revisions = [], []

    def revision(label, path):
        try:
            sha = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'], text=True).strip()
            url = subprocess.check_output(['git', '-C', str(path), 'remote', 'get-url', 'origin'], text=True).strip()
            revisions.append(dict(name=label, url=url, sha=sha))
        except subprocess.CalledProcessError:
            errors.append('Git revision unavailable: ' + label)

    def copy(path, name):
        try:
            if path.is_file() and path.stat().st_size:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            else:
                errors.append('Missing or empty: ' + str(path))
        except OSError as exc:
            errors.append(f'Copy failed: {path}: {exc}')

    try:
        inventory = subprocess.check_output(
            ['dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\n'], text=True)
        if not inventory.strip():
            errors.append('Empty container package inventory')
        (destination / 'dpkg-packages.tsv').write_text(
            '\n'.join(sorted(inventory.splitlines())) + '\n')
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f'Container package inventory failed: {exc}')

    revision('source', source)
    feeds = sorted(p for p in (source / 'feeds').glob('*') if (p / '.git').exists())
    if not feeds:
        errors.append('No Git feed revisions')
    for feed in feeds:
        revision('feed/' + feed.name, feed)
    (destination / 'revisions.json').write_text(json.dumps(revisions, indent=2) + '\n')
    copy(source / '.config', 'final.config')
    copy(source / '.custom-revisions.tsv', 'custom-revisions.tsv')
    for name in ('feeds.conf', 'feeds.conf.default'):
        if (source / name).is_file():
            copy(source / name, name)
    custom = source / '.custom-revisions.tsv'
    if custom.is_file():
        rows = [line.split('\t') for line in custom.read_text().splitlines()]
        expected = {'yahuisme/packages', 'luci-theme-aurora', 'luci-app-aurora-config'}
        if ({row[0] for row in rows} != expected or len(rows) != len(expected)
                or any(len(row) != 3 or len(row[2]) != 40
                       or any(c not in '0123456789abcdef' for c in row[2]) for row in rows)):
            errors.append('Incomplete custom package revisions')
    targets = source / 'bin/targets'
    manifests = sorted(targets.glob('**/*.manifest'))
    if not manifests:
        errors.append('No package manifest')
    for path in manifests + sorted(targets.glob('**/profiles.json')):
        relative = path.relative_to(targets)
        target = destination / 'targets' / relative
        copy(path, str(target.relative_to(destination)))
    images = sorted(targets.glob('**/*sysupgrade.itb'))
    if not images:
        errors.append('No sysupgrade image')
    checksums = []
    for path in images:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        checksums.append(f'{digest}  {path.relative_to(targets)}\n')
    (destination / 'sha256sums').write_text(''.join(checksums))
    (destination / 'diagnostics.json').write_text(json.dumps({'errors': errors}, indent=2) + '\n')
    if errors:
        raise SystemExit('; '.join(errors))


if __name__ == '__main__':
    collect(*sys.argv[1:])
