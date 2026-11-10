"""Exact three-image contract; fixtures are bytes, not flashable firmware."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from firmware_images import collect




class InstallerAcceptance(unittest.TestCase):
    def test_missing_native_installer_configuration_is_rejected(self):
        from validate_firmware import finalize
        system = json.loads((ROOT / 'user/default/build.json').read_text())['system']
        for symbol in ('TARGET_ROOTFS_INITRAMFS', 'PACKAGE_u-boot-an7581_gemtek_w1700k',
                       'PACKAGE_ubi-utils', 'PACKAGE_fitblk'):
            with self.subTest(symbol=symbol), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                self.fixture(base)
                config = base / '.config'
                config.write_text(config.read_text().replace('CONFIG_' + symbol + '=y\n', ''))
                with self.assertRaisesRegex(ValueError, symbol):
                    finalize(config, base / 'openwrt_bin/targets', system)

    def fixture(self, base):
        from test_release_safety import ReleaseTests, IMAGE
        target, data = ReleaseTests().fixture(base)
        return target, data, IMAGE

    def test_finalize_cli_and_staged_binding_cover_every_image(self):
        import hashlib
        import os
        import subprocess
        system = json.loads((ROOT / 'user/default/build.json').read_text())['system']
        for corrupt in ('', 'sysupgrade', 'installer', 'chainload-uboot', 'record', 'partial'):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                target, _, _ = self.fixture(base)
                record = base / 'accepted.json'
                command = [sys.executable, str(ROOT / 'scripts/validate_firmware.py'),
                           str(base / '.config'), str(base / 'openwrt_bin/targets'), system,
                           str(record), '--installer']
                result = subprocess.run(command, capture_output=True, text=True,
                                        env=dict(os.environ, DK_PROFILE='/bld/user/default'))
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = record.read_bytes()
                accepted = json.loads(raw)
                entries = accepted['images'] if isinstance(accepted, dict) else accepted
                self.assertEqual({row['name'] for row in entries},
                                 set(json.loads((ROOT / 'user/default/build.json').read_text())['images']))
                binding = hashlib.sha256(raw).hexdigest()
                if not isinstance(accepted, dict):
                    self.assertEqual(result.stdout.strip(), binding)
                stage = base / 'firmware'
                stage.mkdir()
                for row in entries:
                    (stage / row['name']).write_bytes((target / row['name']).read_bytes())
                if corrupt in ('sysupgrade', 'installer', 'chainload-uboot'):
                    path = next(p for p in stage.iterdir() if corrupt in p.name)
                    raw_image = path.read_bytes()
                    path.write_bytes(bytes([raw_image[0] ^ 1]) + raw_image[1:])
                elif corrupt == 'record':
                    record.write_bytes(raw + b' ')
                elif corrupt == 'partial':
                    entries.pop()
                    record.write_text(json.dumps(accepted))
                    binding = hashlib.sha256(record.read_bytes()).hexdigest()
                    next(stage.iterdir()).unlink()
                if isinstance(accepted, dict):
                    verify = [sys.executable, str(ROOT / 'scripts/verify_staged.py'),
                              str(stage), str(record), binding]
                else:
                    verify = [sys.executable, str(ROOT / 'scripts/staged_firmware.py'),
                              str(record), binding, *map(str, stage.glob('*.itb'))]
                checked = subprocess.run(verify, capture_output=True, text=True,
                                         env=dict(os.environ, DK_PROFILE='/bld/user/default'))
                self.assertEqual(checked.returncode == 0, not corrupt, checked.stderr)

    def test_finalize_rejects_unproven_installer_and_chainloader(self):
        from validate_firmware import finalize
        import copy
        system = json.loads((ROOT / 'user/default/build.json').read_text())['system']
        cases = ('chain-missing', 'chain-type', 'chain-name', 'chain-duplicate',
                 'chain-size', 'chain-digest', 'chain-no-digest', 'chain-oversize',
                 'chain-corrupt', 'installer-corrupt', 'sysupgrade-corrupt',
                 'record-missing', 'record-symlink', 'record-json', 'record-version',
                 'record-image', 'record-duplicate', 'record-payload', 'record-source',
                 'record-recovery', 'record-recovery-name', 'record-recovery-size',
                 'extra-installer', 'extra-chainloader')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                target, data, image_name = self.fixture(base)
                native = data['profiles']['gemtek_w1700k-ubi']['images']
                chain = native[1]
                metadata = target / 'installer.json'
                record = json.loads(metadata.read_text())
                if case == 'chain-missing': native.pop()
                if case == 'chain-type': chain['type'] = 'kernel'
                if case == 'chain-name': chain['name'] = 'other-chainload-uboot.itb'
                if case == 'chain-duplicate': native.append(copy.deepcopy(chain))
                if case == 'chain-size': chain['size'] += 1
                if case == 'chain-digest': chain['sha256'] = '0' * 64
                if case == 'chain-no-digest': chain.pop('sha256')
                if case == 'chain-oversize':
                    import hashlib
                    path = target / chain['name']
                    path.write_bytes(b'x' * (0x100000 + 1))
                    chain.update(size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                if case in ('chain-corrupt', 'installer-corrupt', 'sysupgrade-corrupt'):
                    name = chain['name'] if case == 'chain-corrupt' else record['images'][0]['name'] if case == 'installer-corrupt' else image_name
                    path = target / name
                    raw = path.read_bytes()
                    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                if case == 'record-version': record['version'] = True
                if case == 'record-image': record['images'][0]['digest'] = 'sha256:' + '0' * 64
                if case == 'record-duplicate': record['images'] *= 2
                if case == 'record-payload': record['payload']['digest'] = 'sha256:' + '0' * 64
                if case == 'record-source': record['source'] = '0' * 39
                if case == 'record-recovery': record.pop('recovery')
                if case == 'record-recovery-name': record['recovery']['name'] = '../recovery.itb'
                if case == 'record-recovery-size': record['recovery']['size'] = True
                if case == 'extra-installer': (target / 'extra-installer.itb').write_bytes(b'extra')
                if case == 'extra-chainloader': (target / 'extra-chainload-uboot.itb').write_bytes(b'extra')
                (target / 'profiles.json').write_text(json.dumps(data))
                metadata.write_text(json.dumps(record))
                if case == 'record-missing': metadata.unlink()
                if case == 'record-json': metadata.write_text('{')
                if case == 'record-symlink':
                    metadata.rename(target / 'metadata')
                    metadata.symlink_to('metadata')
                with self.assertRaises((ValueError, OSError)):
                    finalize(base / '.config', base / 'openwrt_bin/targets', system)


class InstallerImages(unittest.TestCase):
    def test_profile_and_collection_include_exact_three_images(self):
        profile = json.loads((ROOT / 'user/default/build.json').read_text())
        prefix = profile['system'] + '-airoha-an7581-gemtek_w1700k-ubi-'
        expected = {prefix + suffix + '.itb' for suffix in (
            'squashfs-sysupgrade', 'initramfs-installer', 'chainload-uboot')}
        self.assertEqual(set(profile['images']), expected)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / profile['target']
            directory.mkdir(parents=True)
            for name in expected:
                (directory / name).write_bytes(b'fixture')
            self.assertEqual({r['name'] for r in collect(tmp, profile)}, expected)
            # Native recovery is embedded, never an additional Release asset.
            (directory / (prefix + 'initramfs-recovery.itb')).write_bytes(b'recovery')
            self.assertEqual({r['name'] for r in collect(tmp, profile)}, expected)
            for extra in ('other-sysupgrade.itb', 'other-installer.itb', 'other-chainload-uboot.itb'):
                with self.subTest(extra=extra):
                    path = directory / extra
                    path.write_bytes(b'extra')
                    with self.assertRaises(ValueError):
                        collect(tmp, profile)
                    path.unlink()

    def test_each_release_image_is_required_and_regular(self):
        profile = json.loads((ROOT / 'user/default/build.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / profile['target']
            directory.mkdir(parents=True)
            for name in profile['images']:
                (directory / name).write_bytes(b'fixture')
            for name in profile['images']:
                for fault in ('missing', 'empty', 'symlink'):
                    with self.subTest(name=name, fault=fault):
                        path = directory / name
                        path.unlink()
                        if fault == 'empty':
                            path.touch()
                        elif fault == 'symlink':
                            path.symlink_to(directory / profile['images'][0] if name != profile['images'][0] else '/dev/null')
                        with self.assertRaises(ValueError):
                            collect(tmp, profile)
                        if path.exists() or path.is_symlink():
                            path.unlink()
                        path.write_bytes(b'fixture')
