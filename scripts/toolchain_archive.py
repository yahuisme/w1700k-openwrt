"""Exact TC member-graph policy, adapted from bootstrap's reviewed validator."""
from contextlib import contextmanager
import gzip
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import time

PACKED = 'toolchain.tar.zst'
LEGACY = 'toolchain.tar.gz'


def candidate(directory):
    paths = [p for p in (directory / PACKED, directory / LEGACY) if p.exists() or p.is_symlink()]
    if len(paths) > 1 or paths and (paths[0].is_symlink() or not paths[0].is_file()):
        raise ValueError('ambiguous or nonregular toolchain archive')
    return paths[0] if paths else None


@contextmanager
def headers(archive):
    # tarfile stops at the tar end marker, before codec integrity checks may run.
    if archive.name == LEGACY:
        with gzip.GzipFile(archive, 'rb') as stream:
            with tarfile.open(fileobj=stream, mode='r:') as tf:
                yield tf
            while stream.read(1024 * 1024):
                pass
        return
    with archive.open('rb') as stream:
        if stream.read(4) != b'\x28\xb5\x2f\xfd':
            raise ValueError('invalid toolchain zstd frame')
    with subprocess.Popen(['zstd', '-dc', '--', str(archive)], stdout=subprocess.PIPE) as proc:
        stream = proc.stdout
        assert stream is not None  # stdout=PIPE
        try:
            with tarfile.open(fileobj=stream, mode='r|', bufsize=1024 * 1024) as tf:
                yield tf
            while stream.read(1024 * 1024):
                pass
            if proc.wait():
                raise ValueError('toolchain zstd decoding failed')
        finally:
            if proc.poll() is None:
                proc.kill()


def extract(archive, root):
    start = time.monotonic()
    validate_archive(archive, root)
    validated = time.monotonic()
    legacy = archive.name == LEGACY
    subprocess.run(['tar', '--gzip' if legacy else '--zstd', '--no-same-owner',
                    '-xf', str(archive), '-C', str(root)], check=True)
    print(f'Toolchain archive timing: format={"gzip" if legacy else "zstd"} '
          f'validate={validated - start:.3f}s extract={time.monotonic() - validated:.3f}s')

def policy_bytes():
    return Path(__file__).read_bytes()


def allowed(path):
    parts = path.split('/')
    return (len(parts) >= 2 and parts[0] in ('build_dir', 'staging_dir')
            and (parts[1] == 'host' or parts[1].startswith('toolchain-')
                 and len(parts[1]) > len('toolchain-')))


def validate_roots(roots):
    build = roots['build_dir']
    staging = roots['staging_dir']
    if any(not side.get('host') or len(side) < 2 or not all(side.values())
           for side in (build, staging)):
        raise ValueError('incomplete toolchain artifact set')
    # Both native rules.mk files use TOOLCHAIN_DIR_NAME for BUILD_DIR_TOOLCHAIN
    # and TOOLCHAIN_DIR. Compare every basename, including extra generations.
    if build.keys() != staging.keys():
        raise ValueError('mismatched toolchain artifact roots: '
                         f'build_dir={sorted(build.keys() - {"host"})}, '
                         f'staging_dir={sorted(staging.keys() - {"host"})}')


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
                # Native autoreconf supplies this input to host build trees.
                if (name.startswith('build_dir/host/') and len(Path(name).parts) >= 4
                        and Path(name).name == 'config.rpath'):
                    script = 'scripts/config.rpath'
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
    with headers(archive) as tf:
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
    roots = {'build_dir': {}, 'staging_dir': {}}
    for name, entry in members.items():
        base, basename, *_ = name.split('/', 2)
        top = members.get(base + '/' + basename)
        roots[base][basename] = top is not None and top.isdir()
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
    validate_roots(roots)
