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


def installer_fixture(base, target, image):
    """Complete three-member evidence fixture, not a FIT/content test."""
    subprocess.run(['git', 'init', '-q', str(base)], check=True)
    subprocess.run(['git', '-C', str(base), '-c', 'user.name=fixture', '-c',
                    'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'], check=True)
    prefix = image.removesuffix('squashfs-sysupgrade.itb')
    installer = target / (prefix + 'initramfs-installer.itb')
    chain = target / (prefix + 'chainload-uboot.itb')
    recovery = target / (prefix + 'initramfs-recovery.itb')
    installer.write_bytes(b'fixture-installer')
    chain.write_bytes(b'fixture-chainloader')
    recovery.write_bytes(b'fixture-inner-recovery')
    def row(path):
        return dict(name=path.name, size=path.stat().st_size,
                    digest='sha256:' + hashlib.sha256(path.read_bytes()).hexdigest())
    record = dict(version=1, source=subprocess.check_output(
        ['git', '-C', str(base), 'rev-parse', 'HEAD'], text=True).strip(),
        images=[row(installer)], payload=row(target / image), recovery=row(recovery))
    (target / 'installer.json').write_text(json.dumps(record))
    return dict(name=chain.name, type='chainload-uboot.itb', size=chain.stat().st_size,
                sha256=hashlib.sha256(chain.read_bytes()).hexdigest())


def staged_images(base):
    """Materialize every exact publish member for shell-only fixtures."""
    profile = json.loads((Path(__file__).resolve().parents[1] / 'user/default/build.json').read_text())
    for name in profile['images']:
        path = base / 'firmware' / name
        if not path.exists():
            path.write_bytes(('fixture-' + name).encode())


def acceptance(base):
    """Freeze private staged fixture bytes for the production publish gate."""
    images = sorted((base / 'firmware').glob('*.itb'))
    raw = (json.dumps(dict(version=1, images=[
        dict(name=p.name, size=p.stat().st_size,
             digest='sha256:' + hashlib.sha256(p.read_bytes()).hexdigest())
        for p in images]), sort_keys=True) + '\n').encode()
    (base / 'firmware/accepted-images.json').write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


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
    metadata = target / 'installer.json'
    if metadata.exists():
        record = json.loads(metadata.read_text())
        record['source'] = subprocess.check_output(['git', '-C', str(base), 'rev-parse', 'HEAD'], text=True).strip()
        metadata.write_text(json.dumps(record))


# Embedded in private gh stubs: respond from the local bytes only.
READBACK = '''
    images = sorted(Path('firmware').glob('*.itb'))
    import hashlib
    assets = [dict(id=i+1, name=p.name, size=p.stat().st_size, state='uploaded',
                   digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for i,p in enumerate(images)]
    print(json.dumps(dict(tag_name=Path('firmware/version.txt').read_text().strip(),
                          name=Path('firmware/version.txt').read_text().strip(),
                          target_commitish=os.environ['GITHUB_SHA'],
                          draft=False, prerelease=False, assets=assets)))
'''
