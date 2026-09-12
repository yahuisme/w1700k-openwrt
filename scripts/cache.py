#!/usr/bin/env python3
"""Exact OpenWrt host artifacts; rolling caches are deliberately separate."""
import hashlib
import inspect
import json
import os
import re
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
    # Full final configuration and source; no historical projection or fallback.
    # Archive/upload edits do not participate in the compatibility policy.
    digest = hashlib.sha256(json.dumps(['tc-inputs-v6', image, os.uname().machine,
                                      str(root), EPOCH, INPUTS,
                                      inspect.getsource(key)]).encode())
    if not (root / '.config').is_file():
        raise ValueError('missing input: .config')
    config = (root / '.config').read_text()
    if re.search(r'^CONFIG_(EXTERNAL_TOOLCHAIN|SRC_TREE_OVERRIDE)=y|^CONFIG_EXTERNAL_KERNEL_TREE="[^"]+', config, re.M):
        raise ValueError('external compiler/kernel/source tree is outside the input lock')
    files = {}
    modes = {}
    for name in INPUTS:
        base = root / name
        if not base.exists():
            raise ValueError('missing input: ' + name)
        for p in sorted(base.rglob('*')) if base.is_dir() else [base]:
            rel = p.relative_to(root)
            # Runtime rootfs overlays, consumed by package/base-files/install;
            # not kernel files/patches. Keep base-files.mk and all target.mk.
            if any(rel.is_relative_to(Path('target/linux') / overlay) for overlay in (
                    'generic/base-files', 'airoha/base-files', 'airoha/an7581/base-files')):
                continue
            # Generated Kconfig binaries must not fingerprint the previous host.
            if rel.parts[:2] == ('scripts', 'config') and subprocess.run(
                    ['git', 'check-ignore', '-q', str(rel)], cwd=root).returncode == 0:
                continue
            if p.is_symlink():
                raise ValueError('unsupported linked input: ' + str(rel))
            if p.is_file():
                files[str(rel)] = p.read_bytes()
                modes[str(rel)] = p.stat().st_mode
                os.utime(p, (EPOCH, EPOCH))
    for name, data in sorted(files.items()):
        digest.update(json.dumps([name, modes[name], hashlib.sha256(data).hexdigest()]).encode())
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
    compressor = 'pigz -1' if shutil.which('pigz') else 'gzip -1'
    subprocess.run(['tar', '--format=posix', '-I', compressor, '-cf', str(archive),
                    '-C', str(base), *names], check=True)
    size = archive.stat().st_size
    print(f'{kind}: measured compressed bytes={size}, cap={LIMITS[kind]}')
    if size > LIMITS[kind]:
        archive.unlink()
        print('cache upload declined: over per-entry budget')
        return
    if kind == 'toolchain':
        (cache / 'key').write_text(expected + '\n')


if __name__ == '__main__':
    mode, root, cache, value = sys.argv[1:5]
    root, cache = Path(root).resolve(), Path(cache).resolve()
    if mode == 'key':
        print(key(root, value))
    elif mode == 'restore':
        restore(root, cache, value)
    elif mode in LIMITS:
        pack(root, cache, mode, value)
    else:
        raise ValueError('unknown cache command: ' + mode)
