#!/usr/bin/env python3
"""Exact OpenWrt host artifacts; rolling caches are deliberately separate."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

EPOCH = 946684800
INPUTS = ('tools', 'toolchain', 'include', 'scripts', 'config', 'target/linux/generic', 'target/linux/airoha',
          'rules.mk', 'Makefile', 'Config.in', '.config')
# Fixed per-variant budgets.  dl is deliberately above the measured rolling
# archives (1.49/1.92 GB); do not turn a useful download cache into a miss.
LIMITS = {'toolchain': 2_000_000_000, 'ccache': 1_500_000_000, 'dl': 2_200_000_000}


def key(root, image):
    digest = hashlib.sha256(json.dumps([image, os.uname().machine, str(root),
                                      Path(__file__).read_text()]).encode())
    for name in INPUTS:
        base = root / name
        if not base.exists():
            raise ValueError('missing input: ' + name)
        for p in sorted(base.rglob('*')) if base.is_dir() else [base]:
            rel = p.relative_to(root)
            # Generated Kconfig binaries must not fingerprint the previous host.
            if rel.parts[:2] == ('scripts', 'config') and subprocess.run(
                    ['git', 'check-ignore', '-q', str(rel)], cwd=root).returncode == 0:
                continue
            if p.is_symlink():
                raise ValueError('unsupported linked input: ' + str(rel))
            if p.is_file():
                digest.update(json.dumps([str(rel), p.stat().st_mode,
                                          hashlib.sha256(p.read_bytes()).hexdigest()]).encode())
                os.utime(p, (EPOCH, EPOCH))
    return digest.hexdigest()


def artifacts(root):
    return [p for pattern in ('build_dir/host', 'build_dir/toolchain-*',
                             'staging_dir/host', 'staging_dir/toolchain-*')
            for p in sorted(root.glob(pattern))]


def restore(root, cache, expected):
    # Never merge an image's staging or target objects with another generation.
    for name in ('build_dir', 'staging_dir'):
        p = root / name
        if p.is_symlink():
            p.unlink()
        elif p.exists():
            shutil.rmtree(p)
    if (cache / 'toolchain.tar.gz').exists():
        if (cache / 'key').read_text().strip() != expected:
            raise ValueError('toolchain key mismatch')
        subprocess.run(['tar', '--gzip', '-xf', str(cache / 'toolchain.tar.gz'),
                        '-C', str(root)], check=True)
        print('exact toolchain restored')
    else:
        print('cold toolchain')


def pack(root, cache, kind, expected):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (kind + '.tar.gz')
    archive.unlink(missing_ok=True)
    paths = artifacts(root) if kind == 'toolchain' else [root]
    if kind == 'toolchain':
        if not (root / 'build_dir/host').is_dir() or not (root / 'staging_dir/host').is_dir() or not list(root.glob('build_dir/toolchain-*')) or not list(root.glob('staging_dir/toolchain-*')):
            raise ValueError('incomplete toolchain artifact set')
        names = [str(p.relative_to(root)) for p in paths]
        base = root
    else:
        names, base = ['.'], root
    subprocess.run(['tar', '--format=posix', '--gzip', '-cf', str(archive), '-C', str(base), *names], check=True)
    size = archive.stat().st_size
    print(f'{kind}: measured compressed bytes={size}, cap={LIMITS[kind]}')
    if size > LIMITS[kind]:
        archive.unlink()
        print('cache upload declined: over per-entry budget')
        return
    if kind == 'toolchain':
        (cache / 'key').write_text(expected + '\n')


def admit(cache, prefix, keep):
    slots = {'tc-v3-ubi2-': 2_000_000_000, 'tc-v3-ubi2-oc-': 2_000_000_000,
             'cc-v3-ubi2.': 1_500_000_000, 'cc-v3-ubi2-oc.': 1_500_000_000,
             'dl-v3.': 2_200_000_000}
    filename = {'tcarchive': 'toolchain.tar.gz', 'ccarchive': 'ccache.tar.gz',
                'dlarchive': 'dl.tar.gz'}.get(cache.name)
    archive = cache / filename if filename else None
    allowed = False
    if prefix not in slots or not archive or not archive.is_file():
        print('cache upload declined: no valid archive')
    elif archive.stat().st_size > slots[prefix]:
        print('cache upload declined: oversized archive')
    else:
        pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
                           'repos/{owner}/{repo}/actions/caches?per_page=100']))
        entries = [e for page in pages for e in page['actions_caches']]
        # Reserve all five slots even when the peer job has not uploaded yet.
        # Old-format and unrelated caches remain untouched and consume budget.
        unknown = sum(e['size_in_bytes'] for e in entries
                      if not any(e['key'].startswith(slot) for slot in slots))
        allowed = sum(slots.values()) + unknown + 300_000_000 <= 10_000_000_000
        if allowed:
            old = [e for e in entries if next((slot for slot in sorted(slots, key=len, reverse=True)
                         if e['key'].startswith(slot)), None) == prefix and e['key'] != keep]
            for e in old:
                subprocess.run(['gh', 'cache', 'delete', str(e['id'])], check=True)
            pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
                               'repos/{owner}/{repo}/actions/caches?per_page=100']))
            remaining = {e['id'] for page in pages for e in page['actions_caches']}
            if any(e['id'] in remaining for e in old):
                raise RuntimeError('cache replacement deletion not confirmed')
        else:
            print('cache upload declined: legacy/unrelated cache migration requires approval')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
        out.write('save=' + str(allowed).lower() + '\n')


if __name__ == '__main__':
    mode, root, cache, value = sys.argv[1:5]
    root, cache = Path(root).resolve(), Path(cache).resolve()
    if mode == 'key':
        print(key(root, value))
    elif mode == 'restore':
        restore(root, cache, value)
    elif mode == 'admit':
        admit(root, str(sys.argv[3]), value)
    else:
        pack(root, cache, mode, value)
