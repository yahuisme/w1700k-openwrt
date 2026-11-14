#!/usr/bin/env python3
"""Materialize a distro overlay at the existing runner/container profile path."""
from pathlib import Path
import json
import sys


def select(system, root):
    root = Path(root)
    if system not in ('openwrt', 'immortalwrt'):
        raise ValueError('unsupported distribution')
    profile = root / 'user/default'
    current = json.loads((profile / 'build.json').read_text())['system']
    if current == system:
        return
    if current != 'openwrt' or system != 'immortalwrt':
        raise ValueError('select the distribution from a fresh checkout')
    overlay = root / 'user/immortalwrt'
    inputs = {name: (overlay / name).read_bytes() for name in ('build.json', 'config.diff', 'settings.ini')}
    contract = json.loads(inputs['build.json'])
    if contract['system'] != system:
        raise ValueError('distribution overlay mismatch')
    installer = root / 'installer/files/installer/install.sh'
    script = installer.read_text()
    if script.count('/openwrt-airoha-an7581-') != 2:
        raise ValueError('unexpected installer payload paths')
    custom = profile / 'custom.sh'
    commands = custom.read_text()
    marker = 'mkdir -p package/firmware/wireless-regdb/patches\n'
    if commands.count(marker) != 1:
        raise ValueError('unexpected regdb customization')
    commands = commands.replace('official OpenWrt version', 'official ImmortalWrt version')
    commands = commands.replace(marker, marker +
        '# Shared 610 replaces the upstream CN/US customization.\n'
        'rm -f package/firmware/wireless-regdb/patches/600-custom-change-txpower-and-dfs.patch\n')
    commands += (
        '\n# Refresh the ImmortalWrt FullCone patch for firewall4 3722eadc.\n'
        'cp -f "$DK_USER/immortalwrt/firewall4-fullcone.patch" '
        'package/network/config/firewall4/patches/001-firewall4-add-support-for-fullcone-nat.patch\n'
        '# End firewall4 patch refresh.\n')
    custom.write_text(commands)
    installer.write_text(script.replace('/openwrt-airoha-an7581-', '/immortalwrt-airoha-an7581-'))
    # Publish the selected identity last; interrupted writes cannot look selected.
    for name in ('config.diff', 'settings.ini', 'build.json'):
        (profile / name).write_bytes(inputs[name])


if __name__ == '__main__':
    select(sys.argv[1], Path(__file__).resolve().parents[1])
