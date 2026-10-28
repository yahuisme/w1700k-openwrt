#!/usr/bin/env python3
"""Validate the final build, before staging any release payload.

Field contract: official OpenWrt/ImmortalWrt scripts/json_add_image_info.py,
include/image.mk and target/linux/airoha/image/an7581.mk.
"""
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
    if not re.fullmatch(r'r[0-9]+-[0-9a-f]+', data['version_code']):
        raise ValueError('invalid version_code')


if __name__ == '__main__':
    validate(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
