#!/usr/bin/env python3
"""Fail-clean restoration for W1700K cache archives."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import gzip
import zlib
from contextlib import redirect_stdout

try:
    from . import cache as toolchain, bootstrap_cache as bootstrap
except ImportError:
    import cache as toolchain
    import bootstrap_cache as bootstrap


def clear(path):
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def clear_restored(kind, root):
    if kind == 'toolchain':
        for name in ('build_dir', 'staging_dir'):
            clear(root / name)
    elif kind == 'bootstrap':
        bootstrap.clear_host(root)
    else:
        clear(root)
        root.mkdir(parents=True, exist_ok=True)


def restore(kind, root, archive, expected, restored, outcome):
    exact = kind in ('toolchain', 'bootstrap')
    candidate = archive / (kind + '.tar.gz')
    clear_restored(kind, root)
    hit = False
    try:
        if outcome == 'success' and restored and (not exact or restored == expected):
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError('missing/linked cache archive')
            if exact:
                keyfile = archive / 'key'
                if keyfile.is_symlink() or not keyfile.is_file():
                    raise ValueError('missing/linked exact cache metadata')
                keyfile.read_text()
                with redirect_stdout(sys.stderr):
                    if kind == 'toolchain':
                        toolchain.restore(root, archive, expected)
                        toolchain.validate_artifacts(root)
                    else:
                        bootstrap.restore(root, archive, expected)
            else:
                subprocess.run(['tar', '--gzip', '-xf', str(candidate), '-C', str(root)], check=True)
            hit = True
    except (ValueError, EOFError, tarfile.TarError, gzip.BadGzipFile, zlib.error,
            subprocess.CalledProcessError) as exc:
        print(f'::warning::Cache restore rejected; cold {kind}: {exc}', file=sys.stderr)
    if not hit:
        clear_restored(kind, root)
        archive.mkdir(parents=True, exist_ok=True)
        # Cache folders are bind mounts; clear their contents, not the mount point.
        for path in archive.iterdir():
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                clear(path)
    print('hit=' + str(hit).lower())
    print('matched-key=' + (restored if hit else ''))
    print('poisoned=' + str(exact and not hit and bool(restored or outcome != 'success')).lower())



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    unpack = commands.add_parser('restore')
    unpack.add_argument('kind', choices=['ccache', 'dl', 'toolchain', 'bootstrap'])
    unpack.add_argument('root', type=Path)
    unpack.add_argument('archive', type=Path)
    unpack.add_argument('expected')
    unpack.add_argument('--restored', default='')
    unpack.add_argument('--outcome', default='success')
    args = parser.parse_args()
    restore(args.kind, args.root, args.archive, args.expected, args.restored, args.outcome)
