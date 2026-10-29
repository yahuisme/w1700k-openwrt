#!/usr/bin/env python3
"""Fail closed before retention unless release identity and image bytes match."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

try:
    from .build_profile import load
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_profile import load


def verify(tag, files):
    expected = {Path(name).name: Path(name) for name in files}
    if (not files or len(expected) != len(files)
            or set(expected) != set(load(Path(__file__).resolve().parents[1] / 'user/default')['images'])
            or any(p.is_symlink() or not p.is_file() or not p.stat().st_size
                   for p in expected.values())):
        raise ValueError('Expected complete nonempty firmware image set')
    workflow_sha = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', workflow_sha):
        raise ValueError('GITHUB_SHA must be an explicit full commit SHA')
    repository = os.environ['GITHUB_REPOSITORY']
    release = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/{repository}/releases/tags/{quote(tag, safe="")}']))
    if (release['tag_name'] != tag or release.get('name') != tag
            or release['draft'] or release['prerelease']):
        raise ValueError('Unexpected release identity/state')
    target = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/{repository}/git/ref/tags/{quote(tag, safe="")}'])).get('object')
    seen = set()
    # At most ten annotated tag objects; never follow a cycle or a non-tag object.
    for _ in range(11):
        if (not isinstance(target, dict) or not isinstance(target.get('sha'), str)
                or not re.fullmatch(r'[0-9a-f]{40}', target['sha'])):
            raise ValueError('Missing or malformed release tag object')
        sha = target['sha']
        if target.get('type') == 'commit':
            if sha != workflow_sha:
                raise ValueError('Release tag commit does not match GITHUB_SHA')
            break
        if target.get('type') != 'tag' or sha in seen:
            raise ValueError('Unexpected release tag object type or cycle')
        seen.add(sha)
        if len(seen) > 10:
            raise ValueError('Release tag chain exceeds dereference limit')
        target = json.loads(subprocess.check_output([
            'gh', 'api', f'repos/{repository}/git/tags/{sha}'])).get('object')
    assets = release['assets']
    if len(assets) != len(expected):
        raise ValueError('Release asset count mismatch')
    if {asset['name'] for asset in assets} != set(expected):
        raise ValueError('Release asset names mismatch')
    for asset in assets:
        path = expected[asset['name']]
        if asset['state'] != 'uploaded' or asset['size'] != path.stat().st_size:
            raise ValueError('Release asset state/size mismatch: ' + path.name)
        with path.open('rb') as stream:
            digest = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
        if asset.get('digest'):
            if asset['digest'] != digest:
                raise ValueError('Release asset digest mismatch: ' + path.name)
        else:
            # Older GitHub assets may lack digest metadata. Stream a readback,
            # avoiding another firmware-sized allocation or temporary artifact.
            with subprocess.Popen(['gh', 'api', f'repos/{repository}/releases/assets/{asset["id"]}',
                                   '-H', 'Accept: application/octet-stream'], stdout=subprocess.PIPE) as proc:
                assert proc.stdout is not None
                downloaded = hashlib.sha256()
                for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b''):
                    downloaded.update(chunk)
                actual = 'sha256:' + downloaded.hexdigest()
                if proc.wait() or actual != digest:
                    raise ValueError('Release asset download mismatch: ' + path.name)
    print('Verified release title, tag commit, image names, count, sizes, uploaded state and SHA-256')


if __name__ == '__main__':
    verify(sys.argv[1], sys.argv[2:])
