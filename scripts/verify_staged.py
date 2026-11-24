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


def verify(directory, accepted, binding):
    profile = load(Path(__file__).resolve().parents[1] / 'user/default')
    directory = Path(directory)
    path = Path(accepted)
    if path.is_symlink() or not re.fullmatch(r'[0-9a-f]{64}', binding):
        raise ValueError('invalid native acceptance binding')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding:
        raise ValueError('native acceptance record changed')
    record = json.loads(raw)
    entries = record.get('images')
    if (record.get('version') != 1 or not isinstance(entries, list)
            or len(entries) != len(profile['images'])
            or any(not isinstance(e, dict) for e in entries)
            or {e.get('name') for e in entries} != set(profile['images'])):
        raise ValueError('invalid native acceptance inventory')
    if {path.name for path in directory.glob('*.itb')} != set(profile['images']):
        raise ValueError('unexpected staged ITB inventory')
    actual = collect(directory, dict(profile, target='.'))
    for entry in entries:
        if (type(entry.get('size')) is not int or entry['size'] <= 0
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(entry.get('digest')))):
            raise ValueError('invalid native acceptance digest/size')
    if sorted(entries, key=lambda e: e['name']) != actual:
        raise ValueError('staged image differs from native acceptance')
    return [directory / entry['name'] for entry in actual]


if __name__ == '__main__':
    print(*verify(*sys.argv[1:]), sep='\n')
