#!/usr/bin/env python3
"""Skip unchanged download archives; never use timestamps as cache evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

if __package__:
    from .cache_recovery import clear_restored
else:
    from cache_recovery import clear_restored


def download_files(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError('not a download directory: ' + str(root))

    def onerror(exc):
        raise exc

    for base, dirs, files in os.walk(root, onerror=onerror):
        for name in dirs + files:
            path = Path(base) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError('unsupported linked download: ' + str(path))
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError('unsupported download item: ' + str(path))
            yield path


def fingerprint(root):
    digest = hashlib.sha256()
    count = 0
    for path in sorted(download_files(root)):
        with path.open('rb') as source:
            content = hashlib.file_digest(source, 'sha256')
        digest.update(json.dumps([str(path.relative_to(root)), content.hexdigest()]).encode())
        count += 1
    return {'digest': digest.hexdigest(), 'files': count}


def snapshot(root, state):
    current = fingerprint(root)
    with tempfile.NamedTemporaryFile(mode='w', dir=state.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(json.dumps(current) + '\n')
            stream.close()
            pending.replace(state)
        finally:
            pending.unlink(missing_ok=True)


def prepare(root, state):
    # Never let a failed snapshot leave usable state from a previous attempt.
    try:
        mode = state.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        pass
    else:
        if stat.S_ISREG(mode):
            state.unlink()
    try:
        snapshot(root, state)
        return
    except (OSError, ValueError) as exc:
        print(f'::warning::Download cache snapshot unavailable; starting cold: {exc}', file=sys.stderr)
    # A cleanup failure must stop preparation; the build would otherwise use
    # the rejected input. This runs before the directory is mounted in Docker.
    clear_restored('dl', root)
    try:
        snapshot(root, state)
    except (OSError, ValueError) as exc:
        print(f'::warning::Cold download cache snapshot unavailable; save disabled: {exc}', file=sys.stderr)


def changed(root, state, restored):
    try:
        if not stat.S_ISREG(state.lstat().st_mode):
            raise ValueError('not a regular snapshot file')
        before = json.loads(state.read_text())
        if (not isinstance(before, dict) or set(before) != {'digest', 'files'}
                or not isinstance(before['digest'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', before['digest'])
                or type(before['files']) is not int or before['files'] < 0):
            raise ValueError('invalid download cache snapshot')
    except (OSError, ValueError) as exc:
        print(f'::warning::Download cache comparison unavailable; save disabled: {exc}', file=sys.stderr)
        return False
    # A cold tree needs a seed regardless of content equality. Scan the
    # entire inventory to keep type checks, but leave payload I/O to tar.
    if not restored:
        return sum(1 for _ in download_files(root)) > 0
    current = fingerprint(root)
    return current['files'] > 0 and current != before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('snapshot', 'prepare', 'check'))
    parser.add_argument('root', type=Path)
    parser.add_argument('state', type=Path)
    parser.add_argument('--restored', default='')
    args = parser.parse_args()
    if args.mode == 'snapshot':
        snapshot(args.root, args.state)
    elif args.mode == 'prepare':
        prepare(args.root, args.state)
    else:
        save = changed(args.root, args.state, args.restored)
        print('save=' + str(save).lower())


if __name__ == '__main__':
    main()
