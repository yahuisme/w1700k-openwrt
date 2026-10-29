#!/usr/bin/env python3
"""Budgeted admission with verified retention and optional download replacement.

Only an explicitly requested W1700K download replacement may remove old seeds
before upload. Other tiers retain save/readback/prune ordering within 10 GB.
Workflow concurrency excludes overlapping runs; inventory must be complete.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

try:
    from .build_profile import load
except ImportError:
    try:
        from scripts.build_profile import load
    except ImportError:
        from build_profile import load

PROFILE = load(Path(__file__).resolve().parents[1] / 'user/default')
SLOTS = {PROFILE['cache_prefix'][kind]: limit for kind, limit in
         [('tc', 2_000_000_000), ('cc', 3_000_000_000), ('dl', 4_000_000_000)]}
# Independent bootstrap tier; keep the build_profile tc/cc/dl contract intact.
BOOTSTRAP_PREFIX = 'tb-v1-ubi2-'
SLOTS[BOOTSTRAP_PREFIX] = 1_000_000_000
BUDGET = 10_000_000_000
HEADROOM = 64 * 1024 * 1024


def inv():
    raw = subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
                                  'repos/{owner}/{repo}/actions/caches?per_page=100'], text=True)
    pages = json.loads(raw)
    if not isinstance(pages, list) or not pages:
        raise ValueError('missing cache inventory pages')
    entries = []
    seen = set()
    total = None
    for page in pages:
        if (not isinstance(page, dict) or type(page.get('total_count')) is not int
                or page['total_count'] < 0 or not isinstance(page.get('actions_caches'), list)):
            raise ValueError('invalid cache inventory page')
        if total is not None and page['total_count'] != total:
            raise ValueError('cache inventory changed during pagination')
        total = page['total_count']
        for e in page['actions_caches']:
            if (type(e['id']) is not int or type(e['size_in_bytes']) is not int
                    or e['size_in_bytes'] < 0 or not isinstance(e['key'], str)
                    or not isinstance(e['ref'], str) or e['id'] in seen):
                raise ValueError('invalid or duplicate cache inventory entry')
            seen.add(e['id'])
            entries.append(e)
    if len(entries) != total:
        raise ValueError('incomplete cache inventory')
    return entries


def owner(key):
    # Retired toolchain keys share the standard prefix; charge as legacy,
    # never restore/save/prune them as standard generations.
    if any(key.startswith(prefix) for prefix in PROFILE.get('retired_cache_prefix', [])):
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


def replace_download(entries, prefix, key, ref, reserve):
    """Free only this branch's old download seeds, after a complete preflight."""
    used = sum(e['size_in_bytes'] for e in entries)
    if any(e['key'] == key and e['ref'] == ref for e in entries):
        raise ValueError('download candidate key already exists; no caches deleted')
    if used + reserve <= BUDGET:
        return entries
    old = sorted((e for e in entries if owner(e['key']) == prefix
                  and e['ref'] == ref and e['key'] != key and e['size_in_bytes'] > 0),
                 key=lambda e: (-e['size_in_bytes'], e['id']))
    if used - sum(e['size_in_bytes'] for e in old) + reserve > BUDGET:
        raise ValueError('download replacement cannot fit; no caches deleted')
    selected = []
    for entry in old:
        selected.append(entry)
        used -= entry['size_in_bytes']
        if used + reserve <= BUDGET:
            break
    removed = {e['id'] for e in selected}
    protected = {e['id'] for e in entries} - removed
    for entry in selected:
        subprocess.run(['gh', 'cache', 'delete', str(entry['id'])], check=True)
    after = inv()
    remaining = {e['id'] for e in after}
    if removed & remaining or not protected <= remaining:
        raise ValueError('download replacement deletion/protected readback failed')
    if sum(e['size_in_bytes'] for e in after) + reserve > BUDGET:
        raise ValueError('download replacement budget changed after deletion')
    print(f'download replacement verified: removed {len(removed)} old seeds before upload')
    return after


def admit(prefix, archive, key, replace=False):
    ok = False
    try:
        ref = validate(prefix, key)
        if replace and (PROFILE['device'] != 'W1700K' or prefix != PROFILE['cache_prefix']['dl']):
            raise ValueError('pre-upload replacement is download-only for W1700K')
        path = Path(archive)
        if path.is_symlink() or not path.is_file():
            raise ValueError('replacement archive missing or linked')
        size = path.stat().st_size
        if not 0 < size <= SLOTS[prefix]:
            raise ValueError('replacement archive empty or oversized')
        entries = inv()
        # Include wrapper tar/compression expansion and metadata, not just the
        # inner gzip. Never subtract an old generation before it is deleted.
        reserve = size + max(HEADROOM, (size + 99) // 100)
        if replace:
            entries = replace_download(entries, prefix, key, ref, reserve)
        used = sum(e['size_in_bytes'] for e in entries)
        ok = used + reserve <= BUDGET
        print(f'cache budget: inventory={used} candidate+margin={reserve} cap={BUDGET}')
        if not ok:
            warn('repository budget exceeded; retaining old caches')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        warn(f'admission denied; no further deletion: {exc}')
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
    if (len(sys.argv) in (5, 6) and sys.argv[1] == 'admit'
            and (len(sys.argv) == 5 or sys.argv[5] == '--replace-download')):
        admit(*sys.argv[2:5], replace=len(sys.argv) == 6)
    elif len(sys.argv) == 4 and sys.argv[1] == 'cleanup':
        # Admission denial is read-only and may continue to a smaller tier.
        # An attempted upload must be confirmed before later admissions.
        sys.exit(0 if cleanup(*sys.argv[2:]) else 1)
    else:
        sys.exit('usage: cache_helper.py admit PREFIX ARCHIVE KEY [--replace-download] | cleanup PREFIX KEY')
