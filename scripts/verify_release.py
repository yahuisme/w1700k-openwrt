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
    from .verify_staged import load_acceptance
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verify_staged import load_acceptance


def verify(tag, accepted, binding):
    expected = {entry['name']: entry for entry in load_acceptance(accepted, binding)}
    workflow_sha = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', workflow_sha):
        raise ValueError('GITHUB_SHA must be an explicit full commit SHA')
    repository = os.environ['GITHUB_REPOSITORY']
    release = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/{repository}/releases/tags/{quote(tag, safe="")}']))
    release_id = release.get('id')
    if (release.get('tag_name') != tag or release.get('name') != tag
            or type(release_id) is not int or release_id <= 0
            or release.get('draft') is not False or release.get('prerelease') is not False):
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
        name = asset['name']
        row = expected[name]
        if asset['state'] != 'uploaded' or type(asset.get('size')) is not int or asset['size'] != row['size']:
            raise ValueError('Release asset state/size mismatch: ' + name)
        digest = row['digest']
        if asset.get('digest'):
            if asset['digest'] != digest:
                raise ValueError('Release asset digest mismatch: ' + name)
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
                    raise ValueError('Release asset download mismatch: ' + name)
    print('Verified release title, tag commit, image names, count, sizes, uploaded state and SHA-256', file=sys.stderr)
    return release_id


if __name__ == '__main__':
    print(verify(*sys.argv[1:]))
