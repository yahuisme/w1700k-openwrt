"""Exact TC member-graph policy, adapted from bootstrap's reviewed validator."""
import os
from pathlib import Path
import stat
import tarfile

def policy_bytes():
    return Path(__file__).read_bytes()


def allowed(path):
    parts = path.split('/')
    return (len(parts) >= 2 and parts[0] in ('build_dir', 'staging_dir')
            and (parts[1] == 'host' or parts[1].startswith('toolchain-')
                 and len(parts[1]) > len('toolchain-')))


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
    for base in ('build_dir', 'staging_dir'):
        if (base + '/host' not in members or not members[base + '/host'].isdir()
                or not any(name.startswith(base + '/toolchain-') and '/' not in name[len(base) + 1:]
                           and entry.isdir() for name, entry in members.items())):
            raise ValueError('incomplete toolchain artifact set')
