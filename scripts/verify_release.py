#!/usr/bin/env python3
"""Fail closed before retention if uploaded image assets differ from local bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote


def verify(tag, files):
    repository = os.environ['GITHUB_REPOSITORY']
    release = json.loads(subprocess.check_output([
        'gh', 'api', f'repos/{repository}/releases/tags/{quote(tag, safe="")}']))
    if release['tag_name'] != tag or release['draft'] or release['prerelease']:
        raise ValueError('Unexpected release identity/state')
    assets = release['assets']
    expected = {Path(name).name: Path(name) for name in files}
    if not expected or len(expected) != len(files) or len(assets) != len(expected):
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
    print('Verified release image names, count, sizes, uploaded state and SHA-256')


if __name__ == '__main__':
    verify(sys.argv[1], sys.argv[2:])
