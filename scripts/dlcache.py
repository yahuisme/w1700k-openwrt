#!/usr/bin/env python3
"""Skip unchanged download archives; never use timestamps as cache evidence."""
import argparse
import hashlib
import json
from pathlib import Path


def fingerprint(root):
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('unsupported linked download: ' + str(path))
        if path.is_file():
            content = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    content.update(chunk)
            digest.update(json.dumps([str(path.relative_to(root)), content.hexdigest()]).encode())
            count += 1
    return {'digest': digest.hexdigest(), 'files': count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('snapshot', 'check'))
    parser.add_argument('root', type=Path)
    parser.add_argument('state', type=Path)
    parser.add_argument('--restored', default='')
    args = parser.parse_args()
    current = fingerprint(args.root)
    if args.mode == 'snapshot':
        args.state.write_text(json.dumps(current) + '\n')
    else:
        before = json.loads(args.state.read_text())
        # A populated legacy/cold cache must seed the current archive format.
        save = current['files'] > 0 and (not args.restored or current != before)
        print('save=' + str(save).lower())


if __name__ == '__main__':
    main()
