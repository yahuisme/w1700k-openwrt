#!/usr/bin/env python3
"""Bind staged bytes to native acceptance independently of best-effort records."""
import hashlib
import json
from pathlib import Path
import re
import sys

try:
    from .build_profile import load
    from .firmware_images import collect
except ImportError:
    from build_profile import load
    from firmware_images import collect


def load_acceptance(accepted, binding):
    profile = load(Path(__file__).resolve().parents[1] / 'user/default')
    path = Path(accepted)
    if path.is_symlink() or not path.is_file() or not re.fullmatch(r'[0-9a-f]{64}', binding):
        raise ValueError('invalid native acceptance binding')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding:
        raise ValueError('native acceptance record changed')
    record = json.loads(raw)
    entries = record.get('images') if isinstance(record, dict) else None
    if (not isinstance(entries, list) or type(record.get('version')) is not int or record['version'] != 1
            or len(entries) != len(profile['images'])
            or any(not isinstance(e, dict) or set(e) != {'name', 'size', 'digest'}
                   or not isinstance(e['name'], str) for e in entries)
            or {e.get('name') for e in entries} != set(profile['images'])):
        raise ValueError('invalid native acceptance inventory')
    for entry in entries:
        if (type(entry.get('size')) is not int or entry['size'] <= 0
                or not isinstance(entry['digest'], str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['digest'])):
            raise ValueError('invalid native acceptance digest/size')
    return sorted(entries, key=lambda e: e['name'])


def verify(directory, accepted, binding):
    directory = Path(directory)
    expected = load_acceptance(accepted, binding)
    names = {entry['name'] for entry in expected}
    if {path.name for path in directory.glob('*.itb')} != names:
        raise ValueError('unexpected staged ITB inventory')
    actual = collect(directory, dict(target='.', device='W1700K', images=names))
    if expected != actual:
        raise ValueError('staged image differs from native acceptance')
    return [directory / entry['name'] for entry in actual]


if __name__ == '__main__':
    print(*verify(*sys.argv[1:]), sep='\n')
