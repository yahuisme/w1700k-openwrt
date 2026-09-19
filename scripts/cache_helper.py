#!/usr/bin/env python3
"""Read-only admission; delete old generations only after a verified save.

The single standard writer counts every generation, ref and legacy entry,
plus candidate and packaging headroom inside a 10 GB repository cap.
Workflow concurrency excludes overlapping runs; inventory must be readable.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SLOTS = {'tc-v3-ubi2-': 2_000_000_000,
         'cc-v3-ubi2.': 1_500_000_000, 'dl-v3.': 2_200_000_000}
BUDGET = 10_000_000_000
HEADROOM = 64 * 1024 * 1024


def inv():
    raw = subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
                                  'repos/{owner}/{repo}/actions/caches?per_page=100'], text=True)
    pages = json.loads(raw)
    entries = []
    seen = set()
    for page in pages:
        for e in page['actions_caches']:
            if (type(e['id']) is not int or type(e['size_in_bytes']) is not int
                    or e['size_in_bytes'] < 0 or not isinstance(e['key'], str)
                    or not isinstance(e['ref'], str) or e['id'] in seen):
                raise ValueError('invalid or duplicate cache inventory entry')
            seen.add(e['id'])
            entries.append(e)
    return entries


def owner(key):
    # Retired toolchain keys share the standard prefix; charge as legacy,
    # never restore/save/prune them as standard generations.
    if key.startswith('tc-v3-ubi2-oc-'):
        return None
    return next((p for p in sorted(SLOTS, key=len, reverse=True)
                 if key.startswith(p)), None)


def warn(message):
    print('::warning::Cache safety: ' + str(message).replace('\n', ' '))


def validate(prefix, key):
    if prefix not in SLOTS or owner(key) != prefix or key == prefix:
        raise ValueError('cache key ownership mismatch')
    ref = os.environ['GITHUB_REF']
    if not ref.startswith('refs/heads/'):
        raise ValueError('cache writes require a current branch ref')
    return ref


def admit(prefix, archive, key):
    ok = False
    try:
        validate(prefix, key)
        path = Path(archive)
        if not path.is_file():
            raise ValueError('replacement archive missing')
        size = path.stat().st_size
        if not 0 < size <= SLOTS[prefix]:
            raise ValueError('replacement archive empty or oversized')
        entries = inv()
        used = sum(e['size_in_bytes'] for e in entries)
        # Include wrapper tar/compression expansion and metadata, not just the
        # inner gzip. Never subtract an old generation before it is deleted.
        reserve = size + max(HEADROOM, (size + 99) // 100)
        ok = used + reserve <= BUDGET
        print(f'cache budget: inventory={used} candidate+margin={reserve} cap={BUDGET}')
        if not ok:
            warn('repository budget exceeded; retaining old caches')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        warn(f'admission denied; retaining old caches: {exc}')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('save=' + str(ok).lower() + '\n')
    return ok


def saved(entries, prefix, keep, ref):
    return [e for e in entries if e['key'] == keep and owner(e['key']) == prefix
            and e['ref'] == ref and e['size_in_bytes'] > 0]


def cleanup(prefix, keep):
    deleted = []
    try:
        ref = validate(prefix, keep)
        entries = inv()
        # The cache list can briefly lag a completed upload.
        for delay in (2, 4):
            if saved(entries, prefix, keep, ref):
                break
            time.sleep(delay)
            entries = inv()
        if not saved(entries, prefix, keep, ref):
            raise ValueError('saved key missing, empty or wrong branch')
        old = [e for e in entries if owner(e['key']) == prefix
               and e['ref'] == ref and e['key'] != keep]
        # Peers may legitimately prune their own old generations concurrently.
        protected = {e['id'] for e in entries
                     if owner(e['key']) == prefix and e not in old}
        for e in old:
            subprocess.run(['gh', 'cache', 'delete', str(e['id'])], check=True)
            deleted.append(e['id'])
        after = inv()
        remaining = {e['id'] for e in after}
        if not saved(after, prefix, keep, ref) or not protected <= remaining:
            raise ValueError('new/protected cache retention readback failed')
        if any(e['id'] in remaining for e in old):
            raise ValueError('old generation deletion not confirmed')
        print(f'cache cleanup verified: removed {len(deleted)} old generations; new/protected retained')
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        state = ('no further deletion; already deleted IDs=' + repr(deleted)
                 if deleted else 'retaining old caches')
        warn(f'cleanup unverified; {state}: {exc}')
        return False


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == 'admit':
        admit(*sys.argv[2:])
    elif len(sys.argv) == 4 and sys.argv[1] == 'cleanup':
        # Admission denial is read-only and may continue to a smaller tier.
        # An attempted upload must be confirmed before later admissions.
        sys.exit(0 if cleanup(*sys.argv[2:]) else 1)
    else:
        sys.exit('usage: cache_helper.py admit PREFIX ARCHIVE KEY | cleanup PREFIX KEY')
