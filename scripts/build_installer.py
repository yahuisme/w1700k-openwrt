#!/usr/bin/env python3
"""Reassemble the native recovery with this build's frozen installation payload."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from build_profile import load
from installer_payload import verify_fit, verify_metadata


def entry(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError('Missing/empty/nonregular installer input: ' + str(path))
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(name=path.name, size=path.stat().st_size, digest='sha256:' + digest)


def native(directory, name):
    actual = entry(directory / name)
    data = json.loads((directory / 'profiles.json').read_text())
    rows = [row for row in data['profiles']['gemtek_w1700k-ubi']['images'] if row.get('name') == name]
    if (len(rows) != 1 or rows[0].get('size') != actual['size'] or
            'sha256:' + str(rows[0].get('sha256')) != actual['digest']):
        raise ValueError('Installer input differs from native profiles.json: ' + name)
    return actual


def build(source, installer, profile):
    source, installer = Path(source).resolve(), Path(installer).resolve()
    directory = source / 'bin/targets' / profile['target']
    prefix = profile['system'] + '-airoha-an7581-gemtek_w1700k-ubi-'
    upgrade, recovery, chain = [prefix + suffix + '.itb' for suffix in (
        'squashfs-sysupgrade', 'initramfs-recovery', 'chainload-uboot')]
    output = prefix + 'initramfs-installer.itb'
    if (directory / output).exists() or (directory / 'installer.json').exists():
        raise ValueError('Installer output already exists')
    payload, inner, bootloader = [native(directory, name) for name in (upgrade, recovery, chain)]
    if bootloader['size'] > 0x100000:
        raise ValueError('Chainloader exceeds its flash partition')
    verify_fit(directory / upgrade)
    verify_fit(directory / recovery, kind='recovery')
    verify_fit(directory / chain, kind='chainloader')
    for path in ('installer/install.sh', 'lib/preinit/00_installer'):
        entry(installer / 'files' / path)
    if (source / 'files/installer').exists() or (source / 'files/lib/preinit/00_installer').exists():
        raise ValueError('Formal firmware overlay contains installer files')
    # Keep backups on the same filesystem for atomic directory swaps. The target
    # directory may be below a bind mount; never rename that mount itself.
    work = Path(tempfile.mkdtemp(prefix='.installer-', dir=source))
    restored = True
    try:
        metadata = work / 'metadata.json'
        subprocess.run([str(source / 'staging_dir/host/bin/fwtool'), '-i', str(metadata),
                        str(directory / upgrade)], check=True)
        verify_metadata(json.loads(metadata.read_text()))
        shutil.copytree(directory, work / 'formal-target')
        original_config = (source / '.config').read_bytes()
        package_make = source / 'package/Makefile'
        original_make = package_make.read_text()
        refresh = '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n'
        if original_make.count(refresh) != 1:
            raise ValueError('Unexpected Aurora snapshot build hook')
        entry(source / '.external-packages/provenance.json')
        had_files = (source / 'files').exists()
        if had_files:
            (source / 'files').rename(work / 'formal-files')
        restored = False
        try:
            shutil.copytree(installer / 'files', source / 'files')
            # The same signed packages remain installed in the temporary system;
            # retain only their runtime feed/key overlay, not formal defaults.
            shutil.copytree(work / 'formal-files/etc/apk', source / 'files/etc/apk')
            package_make.write_text(original_make.replace(refresh, '\t@:\n'))
            embedded = source / 'files/installer'
            for name in (upgrade, recovery):
                shutil.copy2(work / 'formal-target' / name, embedded / name)
            for path in ('installer/install.sh', 'lib/preinit/00_installer'):
                (source / 'files' / path).chmod(0o755)
            # No second clone, defconfig, toolchain or package selection. Native
            # package/install rebuilds rootfs from the unchanged package set;
            # target/install regenerates initramfs with this separate overlay.
            environment = dict(os.environ, FORCE_UNSAFE_CONFIGURE='1', CCACHE_MAXSIZE='3G',
                               CCACHE_NOHASHDIR='true', CCACHE_COMPILERCHECK='content')
            subprocess.run(['make', '-j' + str(os.cpu_count() or 1)], cwd=source,
                           env=environment, check=True)
            roots = list(source.glob('build_dir/target-*/root-airoha'))
            if len(roots) != 1:
                raise ValueError('Missing/ambiguous native installer rootfs')
            for relative in ('installer/install.sh', 'lib/preinit/00_installer',
                             'installer/' + upgrade, 'installer/' + recovery):
                if entry(roots[0] / relative)['digest'] != entry(source / 'files' / relative)['digest']:
                    raise ValueError('Native installer rootfs differs from frozen input: ' + relative)
            outer = native(directory, recovery)
            if outer['digest'] == inner['digest']:
                raise ValueError('Native recovery was not regenerated with installer payload')
            verify_fit(directory / recovery, kind='recovery')
            shutil.copy2(directory / recovery, work / output)
            proof = dict(version=1, images=[dict(outer, name=output)],
                         payload=payload, recovery=inner,
                         source=subprocess.check_output(['git', '-C', str(source), 'rev-parse',
                                                         '--verify', 'HEAD'], text=True).strip())
        finally:
            package_make.write_text(original_make)
            if (source / 'files').exists():
                shutil.rmtree(source / 'files')
            if had_files:
                (work / 'formal-files').rename(source / 'files')
            (source / '.config').write_bytes(original_config)
            shutil.rmtree(directory)
            shutil.copytree(work / 'formal-target', directory)
            restored = True
        shutil.copy2(work / output, directory / output)
        (directory / 'installer.json').write_text(json.dumps(proof, indent=2) + '\n')
    finally:
        if restored:
            shutil.rmtree(work)
        else:
            print('Formal build backup retained: ' + str(work), file=sys.stderr)


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]), load())
