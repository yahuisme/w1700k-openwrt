#!/usr/bin/env python3
"""Exact OpenWrt host artifacts; rolling caches are deliberately separate."""
import hashlib
import inspect
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


PROJECTION_SOURCE_LOCKS = ('e58781c24397662be7cec712c0416a6eb47821e85334f7a5a62a7a4921a8552c',)
PROJECTION_AUDIT = '{"include/kernel.mk": ["75293fc36bdc27597d96441ed974f99c356631b18ffd9cee18a0f2e0802f97f0"], "include/package-bin.mk": ["4f4e58ccb42cd6ae0d9c75408575aeeddf109f1585e6c16a1c4050f14b620649"], "include/package-pack.mk": ["2f5bf4d0c6bb12b86ea42952e9c4b145450f249385e9c4eb02e5da2ba21f110d"], "include/target.mk": ["e0d503f836eb75794120a1d1bd3b1ea26fcccd437fce086dfe0dbd39b5271e6c"], "include/version.mk": ["21ff5a921d3e56cb4463298695d0088c06bf8a6a4a4437180568ddfdd6f47d76"], "scripts/ext-toolchain.sh": ["3035f33a1640932f9907d4b5d28d49200102439fe927dad50e19da00cb4a9bd0"], "scripts/json_overview_image_info.py": ["2ab7bcb2dcbd80f72ca83af64d809fd3bf6c3f43467eb5d29cd2447cbc169f8d"], "scripts/package-metadata.pl": ["39bee5749e82b0d2966a47f3fe92a1e5759c4d46c2c2cb3489f2ce3ce750aebb"]}'

def project_inputs(files):
    """Conservative projection: only package selections / image version labels.

    All other final symbols remain locked, including indirect Kconfig effects.
    Audit exclusions are content locked; unfamiliar consumers retain full config.
    Dynamic references retain every matching prefix (empty prefix = all).
    """
    import re
    excluded = json.loads(PROJECTION_AUDIT)
    texts = []
    conservative = False
    for name, data in files.items():
        if name == '.config':
            continue
        if name in excluded:
            if hashlib.sha256(data).hexdigest() not in excluded[name]:
                conservative = True
            continue
        texts.append(data.decode('utf-8', errors='replace'))
    corpus = '\n'.join(texts)
    # New consumers or executable package-list expressions cannot inherit the
    # old dump-only audit. A cold full key is safe until explicitly reviewed.
    for name, data in files.items():
        if name in excluded:
            continue
        for line in data.decode('utf-8', errors='replace').splitlines():
            if 'DEFAULT_PACKAGES' in line and not line.lstrip().startswith('#'):
                if not (name.startswith('target/linux/airoha/') or name == 'include/default-packages.mk') or not re.match(r'^\s*DEFAULT_PACKAGES\s*\+=\s*[A-Za-z0-9_+./ \\t\\\\-]*$', line):
                    conservative = True
    if any(name not in files for name in excluded):
        conservative = True
    # External mutable trees are not content-addressed by this inventory.
    if re.search(r'^CONFIG_(EXTERNAL_TOOLCHAIN|SRC_TREE_OVERRIDE)=y|^CONFIG_EXTERNAL_KERNEL_TREE="[^"]+', files['.config'].decode(), re.M):
        raise ValueError('external compiler/kernel/source tree is outside the input lock')
    refs = set(re.findall(r'(?<![A-Za-z0-9_])CONFIG_[A-Za-z0-9_-]+', corpus))
    prefixes = re.findall(r'(?<![A-Za-z0-9_])(CONFIG_[A-Za-z0-9_-]*)\$', corpus)
    config = files['.config'].decode()
    projected = []
    for line in config.splitlines():
        m = re.fullmatch(r'(CONFIG_[A-Za-z0-9_-]+)=.*|# (CONFIG_[A-Za-z0-9_-]+) is not set', line)
        if not m:
            # Keep malformed/unknown lines rather than interpreting new syntax.
            if line and not line.startswith('#'):
                projected.append(line)
            continue
        symbol = m[1] or m[2]
        if (not conservative and symbol.startswith(('CONFIG_PACKAGE_', 'CONFIG_VERSION_'))
                and symbol not in refs and not any(symbol.startswith(p) for p in prefixes)):
            continue
        projected.append(line)
    result = dict(files)
    result['.config'] = ('\n'.join(sorted(projected)) + '\n').encode()
    # Only literal package lists: no variable/functions/recipes may be erased.
    # Consumer audit protects the assertion that DEFAULT_PACKAGES is dump-only.
    if not conservative:
        for name, data in files.items():
            if name.startswith('target/linux/airoha/') and (name.endswith('/target.mk') or name.endswith('/Makefile')):
                text = data.decode()
                result[name] = re.sub(
                    r'(?m)^DEFAULT_PACKAGES[ \t]*\+=[ \t]*([A-Za-z0-9_+./ \t-]|\\\n)*\n',
                    'DEFAULT_PACKAGES += <runtime-package-list>\n', text).encode()
    # The reviewed dependency closure is valid only for these complete source
    # inventories, not arbitrary future make metaprograms. Unknown source uses
    # the full config AND unprojected recipes (strict key, never restore fallback).
    lock = hashlib.sha256()
    for name, data in sorted(result.items()):
        if name != '.config':
            lock.update(json.dumps([name, hashlib.sha256(data).hexdigest()]).encode())
    if lock.hexdigest() not in PROJECTION_SOURCE_LOCKS:
        return files
    return result

def key(root, image):
    # v5 deliberately cold-starts exact toolchain keys (no legacy fallback).
    # Only fingerprint policy participates, not archive/upload helper edits.
    digest = hashlib.sha256(json.dumps(['tc-inputs-v5', image, os.uname().machine,
                                      str(root), EPOCH, INPUTS,
                                      inspect.getsource(key), inspect.getsource(project_inputs), PROJECTION_AUDIT, PROJECTION_SOURCE_LOCKS]).encode())
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
    for name, data in sorted(project_inputs(files).items()):
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
    subprocess.run(['tar', '--format=posix', '--gzip', '-cf', str(archive), '-C', str(base), *names], check=True)
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
