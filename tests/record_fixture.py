"""Local-only metadata fixtures for publication shell replay."""
import hashlib
import json
from pathlib import Path
import subprocess


def external_provenance(base):
    """Schema-only metadata fixture; no network, APK or signature verification."""
    record = dict(version=1, architecture='aarch64_cortex-a53',
                  repositories=[dict(name='eamonxg',
                      url='https://openwrt.eamonxg.fun/snapshots/apk',
                      index_sha256='1' * 64, key_sha256='2' * 64)],
                  packages=[dict(name=name, version='1.0-r1', arch='noarch',
                      repository='eamonxg', filename=name + '-1.0-r1.apk', sha256='3' * 64)
                      for name in ('luci-theme-aurora', 'luci-app-aurora-config', 'luci-i18n-aurora-config-zh-cn')])
    directory = base / '.external-packages'
    directory.mkdir(exist_ok=True)
    (directory / 'provenance.json').write_text(json.dumps(record) + '\n')
    return record


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
        for name in ('yahuisme/packages',)))
    external_provenance(base)
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
