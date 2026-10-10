"""Local-only metadata fixtures for publication shell replay."""
import hashlib
import json
from pathlib import Path
import subprocess


def prepare(base):
    """Use real local Git objects; no clone/fetch or remote call."""
    for path in (base, base / 'feeds/packages'):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '-q', str(path)], check=True)
        subprocess.run(['git', '-C', str(path), '-c', 'user.name=fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
        subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', 'https://example.invalid/local'], check=True)
    (base / '.custom-revisions.tsv').write_text(''.join(
        f'{name}\thttps://example.invalid/{name}\t' + 'a' * 40 + '\n'
        for name in ('yahuisme/packages', 'luci-theme-aurora', 'luci-app-aurora-config')))
    (base / 'bin').mkdir(exist_ok=True)
    (base / 'bin/targets').symlink_to(base / 'openwrt_bin/targets')
    target = base / 'openwrt_bin/targets/airoha/an7581'
    (target / 'fixture.manifest').write_text('fixture-package - 1\n')


# Embedded in private gh stubs: respond from the local bytes only.
READBACK = '''
    images = sorted(Path('firmware').glob('*sysupgrade.itb'))
    import hashlib
    assets = [dict(id=i+1, name=p.name, size=p.stat().st_size, state='uploaded',
                   digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for i,p in enumerate(images)]
    print(json.dumps(dict(tag_name=Path('firmware/version.txt').read_text().strip(),
                          draft=False, prerelease=False, assets=assets)))
'''
