#!/usr/bin/env python3
"""Validate the final build, before staging any release payload.

Field contract: official OpenWrt/ImmortalWrt scripts/json_add_image_info.py,
include/image.mk and target/linux/airoha/image/an7581.mk.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

DEVICE = 'gemtek_w1700k-ubi'


def validate(config, targets, distro):
    if distro not in ('openwrt', 'immortalwrt'):
        raise ValueError('unsupported distribution: ' + distro)
    image_name = f'{distro}-airoha-an7581-{DEVICE}-squashfs-sysupgrade.itb'
    lines = config.read_text().splitlines()
    for required in ('CONFIG_TARGET_airoha=y', 'CONFIG_TARGET_airoha_an7581=y',
                     f'CONFIG_TARGET_airoha_an7581_DEVICE_{DEVICE}=y',
                     'CONFIG_TARGET_BOARD="airoha"', 'CONFIG_TARGET_SUBTARGET="an7581"'):
        if lines.count(required) != 1:
            raise ValueError('missing/duplicate final target: ' + required)
    for app in ('airoha-fancontrol', 'airoha-flowsense', 'airoha-npu', 'wifi7', 'wol', 'ttyd'):
        for package in ('luci-app-' + app, 'luci-i18n-' + app + '-zh-cn'):
            if lines.count('CONFIG_PACKAGE_' + package + '=y') != 1:
                raise ValueError('missing/duplicate required application: ' + package)
    for package in ('etherwake', 'ttyd', 'wpad-openssl'):
        if lines.count('CONFIG_PACKAGE_' + package + '=y') != 1:
            raise ValueError('missing/duplicate required dependency: ' + package)
    for package in ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn'):
        if any('CONFIG_PACKAGE_' + package + '=' + state in lines for state in ('y', 'm')):
            raise ValueError('Forbidden package: ' + package)
    devices = [line for line in lines if re.match(r'CONFIG_TARGET_.*_DEVICE_.*=[ym]$', line)]
    if devices != [f'CONFIG_TARGET_airoha_an7581_DEVICE_{DEVICE}=y']:
        raise ValueError('final.config must select exactly the W1700K UBI device')
    images = sorted(targets.rglob('*sysupgrade*'))
    image = targets / 'airoha/an7581' / image_name
    profiles = targets / 'airoha/an7581/profiles.json'
    if images != [image] or not image.is_file() or image.is_symlink() or image.stat().st_size == 0:
        raise ValueError('expected exactly one nonempty W1700K sysupgrade image')
    if sorted(targets.rglob('profiles.json')) != [profiles] or not profiles.is_file():
        raise ValueError('expected exactly one profiles.json for airoha/an7581')
    data = json.loads(profiles.read_text())
    if data['target'] != 'airoha/an7581' or set(data['profiles']) != {DEVICE}:
        raise ValueError('wrong target/device in profiles.json')
    profile = data['profiles'][DEVICE]
    if profile['supported_devices'] != ['gemtek,w1700k-ubi']:
        raise ValueError('wrong supported_devices')
    if not any(t.get('vendor') == 'Gemtek' and t.get('model') == 'W1700K'
               and t.get('variant') == 'UBI' for t in profile['titles']):
        raise ValueError('wrong device title')
    upgrades = [entry for entry in profile['images'] if entry.get('type') == 'sysupgrade'
                or 'sysupgrade' in entry.get('name', '')]
    if len(upgrades) != 1 or upgrades[0].get('name') != image_name or upgrades[0].get('type') != 'sysupgrade' or upgrades[0].get('filesystem') != 'squashfs':
        raise ValueError('wrong/duplicate sysupgrade metadata')
    if upgrades[0].get('size') != image.stat().st_size:
        raise ValueError('image size differs from profiles.json')
    digest = upgrades[0].get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise ValueError('missing/invalid native image sha256')
    with image.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual.lower() != digest.lower():
        raise ValueError('image digest differs from profiles.json')
    if not re.fullmatch(r'r[0-9]+-[0-9a-f]+', data['version_code']):
        raise ValueError('invalid version_code')
    return dict(version=1, images=[dict(name=image_name, size=image.stat().st_size,
                                       digest='sha256:' + actual)])


def finalize(config, targets, distro):
    """Accept all release bytes against native and installer-builder evidence."""
    try:
        from .firmware_images import collect
    except ImportError:
        from firmware_images import collect
    lines = config.read_text().splitlines()
    for symbol in ('TARGET_ROOTFS_INITRAMFS', 'PACKAGE_u-boot-an7581_gemtek_w1700k',
                   'PACKAGE_ubi-utils', 'PACKAGE_fitblk'):
        if lines.count('CONFIG_' + symbol + '=y') != 1:
            raise ValueError('missing/duplicate native installer dependency: ' + symbol)
    native = validate(config, targets, distro)
    upgrade = native['images'][0]
    prefix = f'{distro}-airoha-an7581-{DEVICE}-'
    names = [prefix + suffix + '.itb' for suffix in (
        'squashfs-sysupgrade', 'initramfs-installer', 'chainload-uboot')]
    entries = collect(targets, dict(target='airoha/an7581', device='W1700K', images=names))
    accepted = {row['name']: row for row in entries}
    directory = targets / 'airoha/an7581'
    data = json.loads((directory / 'profiles.json').read_text())
    chains = [row for row in data['profiles'][DEVICE]['images']
              if row.get('type') == 'chainload-uboot.itb' or 'chainload-uboot' in row.get('name', '')]
    chain = accepted[names[2]]
    if (len(chains) != 1 or chains[0].get('name') != names[2]
            or chains[0].get('type') != 'chainload-uboot.itb'
            or type(chains[0].get('size')) is not int
            or chains[0]['size'] != chain['size'] or chain['size'] > 0x100000
            or not isinstance(chains[0].get('sha256'), str)
            or not re.fullmatch(r'[0-9a-fA-F]{64}', chains[0]['sha256'])
            or 'sha256:' + chains[0]['sha256'].lower() != chain['digest']):
        raise ValueError('chainloader differs from native profiles.json or exceeds 1 MiB')
    metadata = directory / 'installer.json'
    if metadata.is_symlink() or not metadata.is_file():
        raise ValueError('missing regular installer.json')
    record = json.loads(metadata.read_text())
    if (not isinstance(record, dict) or type(record.get('version')) is not int
            or record['version'] != 1 or record.get('images') != [accepted[names[1]]]
            or record.get('payload') != upgrade):
        raise ValueError('installer metadata image/payload differs from accepted bytes')
    # Runner final.config belongs to the recipe checkout, not the container's
    # source Git tree. Source identity is captured by the builder, not inferred
    # from that unrelated checkout at staging.
    if not re.fullmatch(r'[0-9a-f]{40}', str(record.get('source'))):
        raise ValueError('invalid installer source commit')
    recovery = record.get('recovery')
    recovery_name = prefix + 'initramfs-recovery.itb'
    if (not isinstance(recovery, dict) or set(recovery) != {'name', 'size', 'digest'}
            or recovery.get('name') != recovery_name
            or type(recovery.get('size')) is not int or recovery['size'] <= 0
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', str(recovery.get('digest')))):
        raise ValueError('invalid embedded recovery evidence')
    # The builder verifies embedded recovery and outer native recovery->installer
    # mapping before writing this record. Native recovery is not a release asset.
    return dict(version=1, images=entries)


if __name__ == '__main__':
    installer = '--installer' in sys.argv
    if installer:
        sys.argv.remove('--installer')
    validator = finalize if installer else validate
    accepted = validator(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    if len(sys.argv) == 5:
        Path(sys.argv[4]).write_text(json.dumps(accepted, indent=2) + '\n')
