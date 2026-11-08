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
    actual = collect(Path(directory), dict(profile, target='.'))
    for entry in entries:
        if (type(entry.get('size')) is not int or entry['size'] <= 0
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(entry.get('digest')))):
            raise ValueError('invalid native acceptance digest/size')
    if sorted(entries, key=lambda e: e['name']) != actual:
        raise ValueError('staged image differs from native acceptance')


if __name__ == '__main__':
    verify(*sys.argv[1:])
