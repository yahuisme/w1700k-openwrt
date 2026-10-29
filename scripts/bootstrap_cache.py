#!/usr/bin/env python3
"""Exact early tools/ccache bootstrap cache; never a post-world host cache."""
import hashlib
import json
import os
from pathlib import Path
import sys
import re
import stat
import subprocess
import shutil
import tarfile

try:
    from . import cache_config
except ImportError:
    try:
        from scripts import cache_config
    except ImportError:
        import cache_config

EPOCH = 946684800
# Reviewed post-customization source locks; provenance and producer closure:
# tests/BOOTSTRAP_SOURCE_REVIEW.md. Canonical Git path/mode/content records.
# Unknown inventory uses TC_KEY, never a guessed config projection.
REVIEWED = {
    'b3f6c374eef006bf64bce517c965fc25c41ad9bbe88ea9fc418f9580d922f93e',
    '1833836d0460ca850a3bd03429a430ead837513e4899eb20725e1f6dbf6c2da6',
    '04fe4b66fa7d80b01fab7f3a608ce169799c5e107c4c14bd9d21c92c7932acf7',
    '1bef18e2273cc6ba0f0d2f8306a9df8b3fa0d31979ef0e9d8b059ee92ddf5ce3',
}
FIXED_INPUTS = ('Makefile', 'rules.mk', 'package/Makefile', 'target/Makefile',
                'toolchain/Makefile', *('include/' + name for name in (
                    'autotools.mk', 'cmake.mk', 'debug.mk', 'depends.mk', 'download.mk',
                    'feeds.mk', 'host-build.mk', 'meson.mk', 'prereq-build.mk', 'prereq.mk',
                    'quilt.mk', 'rootfs.mk', 'shell.sh', 'site/cache', 'site/darwin',
                    'subdir.mk', 'toplevel.mk', 'unpack.mk', 'verbose.mk')))
INCLUDE_INPUTS = tuple(name for name in FIXED_INPUTS if name.startswith('include/'))
ESCAPES = ('include/prepare.mk', 'tests/Makefile', 'git-src')
ENVIRONMENT = ('PATH', 'HOME', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'TMPDIR',
               'SOURCE_DATE_EPOCH', 'FORCE_UNSAFE_CONFIGURE', 'GCC_HONOUR_COPTS')
# These can redirect recursive make outside the reviewed source contract.
OVERRIDES = ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES', 'MAKEFILES', 'CC', 'CXX', 'CPP',
             'CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LD_PRELOAD', 'LD_LIBRARY_PATH',
             'CPATH', 'LIBRARY_PATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH',
             'TOPDIR', 'INCLUDE_DIR', 'BUILD_DIR_HOST', 'STAGING_DIR_HOST',
             'STAGING_DIR', 'BUILD_DIR', 'HOSTCC', 'HOSTCXX', 'HOST_CFLAGS',
             'HOST_CXXFLAGS', 'HOST_LDFLAGS', 'CONFIG_SITE', 'BASH_ENV', 'ENV')


def serialized(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def inventory(root):
    paths = set(root / name for name in FIXED_INPUTS)
    # Aurora's rootfs helper includes this generated makefile at parse time.
    # Hash it when present; legacy/MX trees without it keep their existing lock.
    external = root / '.external-packages.mk'
    if external.exists() or external.is_symlink():
        if external.is_symlink() or not external.is_file():
            raise ValueError('nonregular external make input')
        paths.add(external)
    for name in ('tools', 'scripts'):
        base = root / name
        if base.is_symlink() or not base.is_dir():
            raise ValueError('missing/linked input directory: ' + name)
        paths.update(base.rglob('*'))
    records = []
    for p in sorted(paths):
        rel = p.relative_to(root).as_posix()
        if rel.startswith('scripts/config/') and subprocess.run(
                ['git', 'check-ignore', '-q', '--', rel], cwd=root,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            continue
        # Check every ancestor too: rglob does not follow linked directories.
        if any(q.is_symlink() for q in (p, *p.parents) if q != root and root in q.parents):
            raise ValueError('linked input: ' + rel)
        if not p.exists():
            records.append({'path': rel, 'missing': True})
        elif p.is_file():
            records.append({'path': rel, 'mode': stat.S_IMODE(p.stat().st_mode),
                            'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            os.utime(p, (EPOCH, EPOCH))
        elif not p.is_dir():
            raise ValueError('special input: ' + rel)
    return hashlib.sha256(serialized(sorted(records, key=lambda row: row['path']))).hexdigest()


def configuration(root):
    p = root / '.config'
    if p.is_symlink() or not p.is_file():
        raise ValueError('missing/linked .config')
    raw = p.read_bytes()
    values = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'(CONFIG_[A-Za-z0-9_+.-]+)=(y|m|n|-?[0-9]+|0x[0-9a-fA-F]+|"(?:[^"\\\x00-\x1f]|\\["\\])*")', line)
        if not match or '$' in line or '`' in line or match[1] in values:
            raise ValueError('unsupported generated .config syntax')
        values[match[1]] = match[2]
    if not values:
        raise ValueError('empty generated .config')
    for name in ('EXTERNAL_TOOLCHAIN', 'SRC_TREE_OVERRIDE', 'NATIVE_TOOLCHAIN', 'SDK'):
        if values.get('CONFIG_' + name) == 'y':
            raise ValueError('external/mutable bootstrap input: ' + name)
    for name in ('EXTERNAL_KERNEL_TREE', 'TOOLCHAIN_ROOT', 'TOOLCHAIN_BIN_PATH',
                 'TOOLCHAIN_INC_PATH', 'TOOLCHAIN_LIB_PATH', 'DOWNLOAD_TOOL_CUSTOM', 'DOWNLOAD_FOLDER',
                 'BUILD_SUFFIX'):
        if values.get('CONFIG_' + name, '""') != '""':
            raise ValueError('unlocked external input: ' + name)
    for name in ('HOST_EXTRA_CFLAGS', 'HOST_EXTRA_CPPFLAGS', 'HOST_EXTRA_CXXFLAGS',
                 'HOST_EXTRA_LDFLAGS', 'HOST_FLAGS_OPT', 'HOST_FLAGS_STRIP'):
        flags = values.get('CONFIG_' + name, '""')[1:-1].split()
        if any(not re.fullmatch(r'-O[0-3sgz]|-pipe|-g[0-3]?|-f(no-)?(plt|omit-frame-pointer)', flag)
               for flag in flags):
            raise ValueError('unlocked external host flags: ' + name)
    os.utime(p, (EPOCH, EPOCH))
    return raw, values


def key(root, builder, tc_key):
    if not builder or not tc_key:
        raise ValueError('builder and full toolchain key required')
    if any(os.environ.get(name) for name in OVERRIDES):
        raise ValueError('environment overrides are outside the bootstrap input lock')
    if any((root / name).exists() or (root / name).is_symlink() for name in ESCAPES):
        raise ValueError('unreviewed make/source escape')
    raw, values = configuration(root)
    source = inventory(root)
    independent = source in REVIEWED and values.get('CONFIG_BUILD_ALL_HOST_TOOLS') != 'y'
    environment = {name: os.environ.get(name) for name in ENVIRONMENT}
    host = os.uname()
    data = ['bootstrap-v3', builder, [host.sysname, host.release, host.version, host.machine], str(root), EPOCH,
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), environment,
            hashlib.sha256(cache_config.policy_bytes()).hexdigest(),
            hashlib.sha256(cache_config.fingerprint_bytes(raw)).hexdigest(), stat.S_IMODE((root / '.config').stat().st_mode),
            source, None if independent else tc_key]
    print('bootstrap contract=' + ('reviewed-independent' if independent else 'full-toolchain-bound'),
          file=sys.stderr)
    return hashlib.sha256(serialized(data)).hexdigest()


ROOTS = ('build_dir/host', 'staging_dir/host')
LIMIT = 1_000_000_000  # Compressed admission cap; decline locally, never delete remote.


def allowed(path):
    return any(path == name or path.startswith(name + '/') for name in ROOTS)


def _link_target(name, entry, root):
    target = Path(entry.linkname)
    if entry.islnk():
        resolved = Path(os.path.normpath(root / target))
        if not resolved.is_relative_to(root) or not allowed(resolved.relative_to(root).as_posix()):
            raise ValueError('archive hardlink escapes host pair: ' + name)
        return resolved
    if target.is_absolute():
        target = Path(os.path.normpath(target))
        if target.is_relative_to(root):
            if not allowed(target.relative_to(root).as_posix()):
                # Official prereq links only: scripts/ is already hashed with its
                # permissions by inventory(). Never admit arbitrary TOPDIR links.
                script = {'staging_dir/host/bin/xxd': 'scripts/xxdi.pl',
                          'staging_dir/host/bin/ldconfig': 'scripts/noop.sh'}.get(name)
                if script is None or entry.linkname != str(root / script):
                    raise ValueError('archive link escapes host pair: ' + name)
                if any(p.is_symlink() for p in (target, *target.parents)):
                    raise ValueError('linked prerequisite script/ancestor: ' + name)
                if any(not p.is_dir() or stat.S_IMODE(p.stat().st_mode) & 0o7022
                       for p in (root, root / 'scripts')):
                    raise ValueError('unsafe prerequisite script ancestor: ' + name)
                if (not target.is_file() or not os.access(target, os.X_OK)
                        or stat.S_IMODE(target.stat().st_mode) & 0o7022):
                    raise ValueError('unsafe/nonexecutable prerequisite script: ' + name)
            return target
        # Prerequisite compiler/tools links may intentionally reference builder OS files.
        # They are never dereferenced into the archive and are accepted only in the
        # audited system locations; the complete builder fingerprint remains in key().
        if not any(target == Path(prefix) or target.is_relative_to(prefix)
                   for prefix in (Path('/usr/bin'), Path('/bin'), Path('/usr/lib'))):
            raise ValueError('archive system link escapes builder locations: ' + name)
        if not target.exists():
            raise ValueError('archive system link target missing: ' + name)
        resolved = target.resolve(strict=True)
        if not any(resolved == Path(prefix) or resolved.is_relative_to(prefix)
                   for prefix in (Path('/usr/bin'), Path('/bin'), Path('/usr/lib'), Path('/lib'))):
            raise ValueError('archive system link chain escapes builder locations: ' + name)
        if '/bin/' in ('/' + name) and (not resolved.is_file() or not os.access(resolved, os.X_OK)):
            raise ValueError('archive system tool link is not executable: ' + name)
        return target
    resolved = Path(os.path.normpath(root / Path(name).parent / target))
    if not resolved.is_relative_to(root) or not allowed(resolved.relative_to(root).as_posix()):
        raise ValueError('archive link escapes host pair: ' + name)
    return resolved


def _link_chain(resolved, members, root, seen):
    if not resolved.is_relative_to(root):
        return
    relative = resolved.relative_to(root)
    item = members.get(relative.as_posix())
    if not item or not (item.issym() or item.islnk()):
        return
    if relative.as_posix() in seen:
        raise ValueError('archive link cycle')
    seen.add(relative.as_posix())
    _link_chain(_link_target(relative.as_posix(), item, root), members, root, seen)


def validate_archive(archive, root):
    """Validate all headers before extraction; never follow archive link parents."""
    members = {}
    with tarfile.open(archive, 'r:gz') as tf:
        for entry in tf:
            name = entry.name.rstrip('/')
            if (not allowed(name) or Path(name).is_absolute()
                    or any(part in ('', '.', '..') for part in name.split('/'))
                    or name in members):
                raise ValueError('unsafe/duplicate archive path: ' + name)
            if not (entry.isdir() or entry.isfile() or entry.issym() or entry.islnk()):
                raise ValueError('special archive member: ' + name)
            if entry.mode & 0o7000:
                raise ValueError('privileged archive mode: ' + name)
            members[name] = entry
    for name, entry in members.items():
        parent = Path(name).parent
        while str(parent) != '.':
            existing = members.get(parent.as_posix())
            if existing and not existing.isdir():
                raise ValueError('archive writes through a link/non-directory')
            parent = parent.parent
        if entry.issym() or entry.islnk():
            # Do not collapse '..' over an archive symlink: lexical normalization
            # alone can conceal an OS-resolved escape through an intermediate link.
            raw_target = Path(entry.linkname)
            if raw_target.is_absolute() and raw_target.is_relative_to(root):
                raw_target = raw_target.relative_to(root)
            elif not raw_target.is_absolute():
                raw_target = (Path(name).parent if entry.issym() else Path('.')) / raw_target
            if not raw_target.is_absolute():
                prefix = Path('.')
                for part in raw_target.parts[:-1]:
                    prefix = Path(os.path.normpath(prefix / part))
                    linked = members.get(prefix.as_posix())
                    if linked and (linked.issym() or linked.islnk()):
                        raise ValueError('archive link target traverses another link')
            target = _link_target(name, entry, root)
            _link_chain(target, members, root, {name})
            if entry.islnk() and (target.relative_to(root).as_posix() not in members
                                  or not members[target.relative_to(root).as_posix()].isfile()):
                raise ValueError('invalid archive hardlink')
    if any(name not in members or not members[name].isdir() for name in ROOTS):
        raise ValueError('incomplete host artifact pair')


def validate_pair(root):
    for name in ROOTS:
        p = root / name
        if p.is_symlink() or not p.is_dir() or not any(p.iterdir()):
            raise ValueError('incomplete/empty host artifact pair')
    binary = root / 'staging_dir/host/bin/ccache'
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('missing executable host ccache')
    for tool in ('ccache', 'cmake'):
        built = list(root.glob('build_dir/host/' + tool + '-*/.built'))
        stamp = root / ('staging_dir/host/stamp/.' + tool + '_installed')
        if not any(p.is_file() and not p.is_symlink() for p in built) or not stamp.is_file() or stamp.is_symlink():
            raise ValueError('missing bootstrap completion stamps: ' + tool)


def clear_host(root):
    for name in ROOTS:
        p = root / name
        parent = p.parent
        if parent.is_symlink():
            raise ValueError('linked build/staging parent')
        if p.is_symlink():
            p.unlink()
        elif p.exists():
            shutil.rmtree(p)


def restore(root, cache, expected):
    archive = cache / 'bootstrap.tar.gz'
    if not archive.exists():
        clear_host(root)
        print('cold bootstrap')
        return
    if (archive.is_symlink() or (cache / 'key').is_symlink()
            or (cache / 'key').read_text() != expected + '\n'):
        raise ValueError('bootstrap key mismatch')
    validate_archive(archive, root)
    clear_host(root)  # Only host roots; never remove an already restored toolchain.
    try:
        subprocess.run(['tar', '--gzip', '--no-same-owner', '-xf', str(archive),
                        '-C', str(root)], check=True)
        validate_pair(root)
    except Exception:
        clear_host(root)
        raise
    print('exact bootstrap restored')


def pack(root, cache, expected):
    if not expected or '\n' in expected:
        raise ValueError('missing/invalid bootstrap key')
    cache.mkdir(parents=True, exist_ok=True)
    archive, keyfile = cache / 'bootstrap.tar.gz', cache / 'key'
    # Failure/decline leaves no local upload candidate; remote retention is separate.
    archive.unlink(missing_ok=True)
    keyfile.unlink(missing_ok=True)
    validate_pair(root)
    if any((root / name).is_symlink() for name in ('build_dir', 'staging_dir')):
        raise ValueError('linked build/staging parent')
    compressor = 'pigz -1' if shutil.which('pigz') else 'gzip -1'
    try:
        subprocess.run(['tar', '--format=posix', '-I', compressor, '-cf', str(archive),
                        '-C', str(root), *ROOTS], check=True)
        validate_archive(archive, root)
        size = archive.stat().st_size
        print(f'bootstrap: measured compressed bytes={size}, cap={LIMIT}')
        if size > LIMIT:
            archive.unlink()
            print('bootstrap upload declined: over per-entry budget')
            return
        keyfile.write_text(expected + '\n')
    except Exception:
        archive.unlink(missing_ok=True)
        keyfile.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    mode, root, cache, *args = sys.argv[1:]
    root, cache = Path(root).resolve(), Path(cache).resolve()
    if mode == 'key' and len(args) == 2:
        print(key(root, *args))
    elif mode == 'pack' and len(args) == 1:
        pack(root, cache, args[0])
    elif mode == 'restore' and len(args) == 1:
        restore(root, cache, args[0])
    else:
        raise ValueError('usage: key ROOT CACHE BUILDER TC_KEY | pack/restore ROOT CACHE EXPECTED')
