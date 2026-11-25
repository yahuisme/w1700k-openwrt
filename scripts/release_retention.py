#!/usr/bin/env python3
"""Select only provably older W1700K releases from a complete inventory."""
from datetime import datetime
import json
import re
import sys

TITLES = {'openwrt': 'OpenWrt', 'immortalwrt': 'ImmortalWrt'}
DATE = r'(?P<date>[0-9]{2}\.[0-9]{2}\.[0-9]{2})'
TIME = r'(?P<time>[0-9]{2}\.[0-9]{2}\.[0-9]{2})'
REV = r'r[0-9]+'


def build_time(tag, patterns):
    for pattern in patterns:
        match = re.fullmatch(pattern, tag)
        if match:
            try:
                return datetime.strptime(f"{match['date']}_{match['time']}", '%y.%m.%d_%H.%M.%S')
            except ValueError:
                return None
    return None


def published_at(row):
    value = row.get('published_at')
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value):
        raise ValueError('Missing or invalid publication timestamp: ' + row['tag_name'])
    return datetime.fromisoformat(value)


def select(pages, system, current, verified_id):
    title = TITLES[system]
    current_pattern = rf'W1700K-{title}-{REV}-{DATE}_{TIME}'
    current_build = build_time(current, (current_pattern,))
    if current_build is None:
        raise ValueError('Invalid current W1700K release tag')
    # Legacy unlabelled UBI2 tags belong to OpenWrt; require full standard
    # date/revision syntax so unrelated and retired OC tags cannot match.
    families = (title, 'ubi2') if system == 'openwrt' else (title,)
    legacy = [pattern for family in families for pattern in (
        rf'W1700K-{family}-{REV}-{DATE}[-_]{TIME}',
        rf'W1700K-{family}_{DATE}[-_]{TIME}_{REV}',
    )]
    if (not isinstance(pages, list) or not pages or any(not isinstance(p, list) for p in pages)
            or any(len(p) != 100 for p in pages[:-1]) or not 1 <= len(pages[-1]) <= 100):
        raise ValueError('Invalid or inconsistent release inventory pages')
    ids, inventory = set(), {}
    for page in pages:
        for row in page:
            if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0
                    or not isinstance(row.get('tag_name'), str) or not row['tag_name']
                    or type(row.get('draft')) is not bool or type(row.get('prerelease')) is not bool):
                raise ValueError('Invalid release inventory entry')
            tag = row['tag_name']
            if row['id'] in ids or tag in inventory:
                raise ValueError('Duplicate release ID or tag across pages')
            ids.add(row['id'])
            inventory[tag] = row
    anchor = inventory.get(current)
    if (anchor is None or anchor['id'] != verified_id
            or anchor['draft'] or anchor['prerelease']):
        raise ValueError('Verified release missing or replaced in inventory')
    current_publication = published_at(anchor)
    older = []
    for tag, row in inventory.items():
        if tag == current or row['draft'] or row['prerelease']:
            continue
        built = build_time(tag, legacy)
        if built is not None and published_at(row) < current_publication and built < current_build:
            older.append(tag)
    return older


if __name__ == '__main__':
    system, current, release_id = sys.argv[1:]
    try:
        older = select(json.load(sys.stdin), system, current, int(release_id))
    except (KeyError, ValueError) as error:
        sys.exit(str(error))
    print('\n'.join(older))
