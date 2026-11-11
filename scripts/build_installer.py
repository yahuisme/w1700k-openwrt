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
import time

from build_profile import load
from installer_payload import verify_fit, verify_metadata, verify_embedded


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


def installed_packages(root):
    return {line[2:] for line in (Path(root) / 'lib/apk/db/installed').read_text().splitlines()
            if line.startswith('P:')}


def lean_packages(root):
    """Let native APK resolve dependencies; retain the existing driver set."""
    installed = installed_packages(root)
    seeds = set('busybox dropbear fstools fwtool jsonfilter logd mtd netifd procd '
                'procd-seccomp uboot-envtools ubox ubus ubusd uci ubi-utils ucode '
                'ucode-mod-digest ucode-mod-fs urandom-seed urngd usign fitblk'.split())
    dns = installed & {'dnsmasq', 'dnsmasq-full'}
    if len(dns) != 1 or not seeds <= installed:
        raise ValueError('Missing/ambiguous native recovery packages')
    seeds |= dns | {name for name in installed if name.startswith('kmod-') or name.endswith('-firmware')}
    return sorted(seeds)


def validate_lean(root, seeds):
    installed = installed_packages(root)
    if not set(seeds) <= installed:
        raise ValueError('Missing native recovery packages')
    if any(name.startswith(('luci', 'rpcd', 'uhttpd')) or name in
           {'ttyd', 'nano', 'curl', 'jq', 'etherwake', 'relayd'} for name in installed):
        raise ValueError('Unexpected application in lean recovery')


def rebuild(source, packages, phase):
    """Use native package resolution/image generation, never another world."""
    environment = dict(os.environ, FORCE_UNSAFE_CONFIGURE='1', CCACHE_MAXSIZE='3G',
                       CCACHE_NOHASHDIR='true', CCACHE_COMPILERCHECK='content')
    overrides = ['PACKAGE_INSTALL_FILES=' + str(packages),
                 'EXTERNAL_PACKAGES=', 'EXTERNAL_REPOSITORIES=']
    started, status = time.monotonic(), 'not-started'
    try:
        for targets in (['-j1', 'package/install'],
                        ['-j' + str(os.cpu_count() or 1), 'target/install'],
                        ['-j1', 'json_overview_image_info', 'checksum']):
            subprocess.run(['make', *targets, *overrides], cwd=source,
                           env=environment, check=True)
        status = 0
    except subprocess.CalledProcessError as error:
        status = error.returncode
        raise
    finally:
        print(f'Build timing: {phase}={time.monotonic() - started:.1f}s status={status}', flush=True)


def build(source, installer, profile):
    source, installer = Path(source).resolve(), Path(installer).resolve()
    directory = source / 'bin/targets' / profile['target']
    prefix = profile['system'] + '-airoha-an7581-gemtek_w1700k-ubi-'
    upgrade, recovery, chain = [prefix + suffix + '.itb' for suffix in (
        'squashfs-sysupgrade', 'initramfs-recovery', 'chainload-uboot')]
    output = prefix + 'initramfs-installer.itb'
    if (directory / output).exists() or (directory / 'installer.json').exists():
        raise ValueError('Installer output already exists')
    roots = list(source.glob('build_dir/target-*/root-airoha'))
    if len(roots) != 1:
        raise ValueError('Missing/ambiguous native installer rootfs')
    runtime = roots[0]
    seeds = lean_packages(runtime)
    config_lines = (source / '.config').read_text().splitlines()
    if any(line in config_lines for line in ('CONFIG_TARGET_MULTI_PROFILE=y', 'CONFIG_TARGET_PER_DEVICE_ROOTFS=y')):
        raise ValueError('Lean installer requires the single native rootfs')
    payload, formal_recovery, bootloader = [native(directory, name) for name in (upgrade, recovery, chain)]
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
        shutil.copytree(directory, work / 'formal-target', symlinks=True)
        original_config = (source / '.config').read_bytes()
        package_make = source / 'package/Makefile'
        original_make = package_make.read_text()
        refresh = '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n'
        if original_make.count(refresh) != 1:
            raise ValueError('Unexpected Aurora snapshot build hook')
        entry(source / '.external-packages/provenance.json')
        rootfs_make = source / 'include/rootfs.mk'
        original_rootfs = rootfs_make.read_text()
        check_root = '\tpython3 /cache-scripts/external_packages.py verify-root $(1) $(TOPDIR)/.external-packages/provenance.json\n'
        if original_rootfs.count(check_root) != 1:
            raise ValueError('Unexpected Aurora rootfs verification hook')
        packages = work / 'recovery-packages.list'
        packages.write_text('\n'.join(seeds) + '\n')
        # Persist every original before the first destructive overlay swap.
        (work / 'formal-config').write_bytes(original_config)
        (work / 'formal-package-Makefile').write_text(original_make)
        (work / 'formal-rootfs.mk').write_text(original_rootfs)
        had_files = (source / 'files').exists()
        restored = False
        try:
            if had_files:
                (source / 'files').rename(work / 'formal-files')
            (source / 'files').mkdir()
            package_make.write_text(original_make.replace(refresh, '\t@:\n'))
            rootfs_make.write_text(original_rootfs.replace(check_root, '\t@:\n'))
            # First create a clean, lean recovery without the auto-install hook.
            rebuild(source, packages, 'recovery')
            if (source / '.config').read_bytes() != original_config:
                raise ValueError('Installer configuration changed during native rebuild')
            validate_lean(runtime, seeds)
            if (runtime / 'installer').exists() or (runtime / 'lib/preinit/00_installer').exists():
                raise ValueError('Lean recovery contains installer entrypoint')
            inner = native(directory, recovery)
            if inner['digest'] == formal_recovery['digest']:
                raise ValueError('Lean recovery was not regenerated')
            verify_fit(directory / recovery, kind='recovery')
            shutil.copy2(directory / recovery, work / recovery)
            shutil.copytree(installer / 'files', source / 'files', dirs_exist_ok=True)
            embedded = source / 'files/installer'
            shutil.copy2(work / 'formal-target' / upgrade, embedded / upgrade)
            shutil.copy2(work / recovery, embedded / recovery)
            for path in ('installer/install.sh', 'lib/preinit/00_installer'):
                (source / 'files' / path).chmod(0o755)
            (embedded / 'payload.sha256').write_text(
                payload['digest'][7:] + '  ' + upgrade + '\n' +
                inner['digest'][7:] + '  ' + recovery + '\n')
            frozen = {relative: entry(source / 'files' / relative)['digest'] for relative in (
                'installer/install.sh', 'lib/preinit/00_installer', 'installer/payload.sha256',
                'installer/' + upgrade, 'installer/' + recovery)}
            if frozen['installer/' + upgrade] != payload['digest'] or frozen['installer/' + recovery] != inner['digest']:
                raise ValueError('Installer payload differs from frozen input')
            rebuild(source, packages, 'installer')
            if (source / '.config').read_bytes() != original_config:
                raise ValueError('Installer configuration changed during native rebuild')
            validate_lean(runtime, seeds)
            roots = list(source.glob('build_dir/target-*/root-airoha'))
            if len(roots) != 1:
                raise ValueError('Missing/ambiguous native installer rootfs')
            for relative, digest in frozen.items():
                if (entry(source / 'files' / relative)['digest'] != digest
                        or entry(roots[0] / relative)['digest'] != digest):
                    raise ValueError('Native installer rootfs differs from frozen input: ' + relative)
            outer = native(directory, recovery)
            if outer['digest'] == inner['digest']:
                raise ValueError('Native recovery was not regenerated with installer payload')
            verify_fit(directory / recovery, kind='recovery')
            verify_embedded(directory / recovery, frozen)
            shutil.copy2(directory / recovery, work / output)
            proof = dict(version=1, images=[dict(outer, name=output)],
                         payload=payload, recovery=inner, recovery_packages=seeds,
                         source=subprocess.check_output(['git', '-C', str(source), 'rev-parse',
                                                         '--verify', 'HEAD'], text=True).strip())
        finally:
            errors = []

            def restore_tree(backup, target):
                if target.exists():
                    shutil.rmtree(target)
                # Copy, never consume the only backup during restoration.
                if backup is not None:
                    shutil.copytree(backup, target, symlinks=True)

            actions = [
                ('package/Makefile', lambda: package_make.write_bytes((work / 'formal-package-Makefile').read_bytes())),
                ('include/rootfs.mk', lambda: rootfs_make.write_bytes((work / 'formal-rootfs.mk').read_bytes())),
                ('.config', lambda: (source / '.config').write_bytes((work / 'formal-config').read_bytes())),
                ('target', lambda: restore_tree(work / 'formal-target', directory)),
            ]
            # A rename can fail before OR after moving. Trust the backup's
            # existence, not an assignment after rename; never erase an unmoved overlay.
            if (work / 'formal-files').exists() or not had_files:
                actions.append(('files', lambda: restore_tree(
                    work / 'formal-files' if had_files else None, source / 'files')))
            for name, action in actions:
                try:
                    action()
                except BaseException as error:
                    errors.append(name + ': ' + repr(error))
            if errors:
                raise OSError('Formal build restoration failed: ' + '; '.join(errors))
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
