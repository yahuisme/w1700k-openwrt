"""Exercise two native lean image passes without compiling or invoking real make."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

BASE = {'busybox', 'dropbear', 'fitblk', 'ubi-utils', 'netifd',
        'uci', 'ubus', 'ubusd', 'ubox', 'fstools', 'fwtool', 'jsonfilter',
        'logd', 'mtd', 'procd', 'procd-seccomp', 'uboot-envtools', 'ucode',
        'ucode-mod-digest', 'ucode-mod-fs', 'urandom-seed', 'urngd', 'usign'}
DRIVERS = {'kmod-mt7996e', 'kmod-mt7996-firmware',
           'kmod-airoha-eth', 'kmod-usb3', 'airoha-en7581-npu-firmware',
           'rtl8261c-firmware'}
APPS = {'luci', 'luci-base', 'luci-app-firewall', 'luci-theme-aurora',
        'rpcd', 'rpcd-mod-uci', 'uhttpd', 'uhttpd-mod-ubus', 'ttyd', 'nano',
        'curl', 'jq', 'etherwake', 'relayd'}
REFRESH = '\tpython3 /cache-scripts/external_packages.py snapshot $(TOPDIR) $(STAGING_DIR_HOST)/bin/apk\n'
VERIFY_ROOT = '\tpython3 /cache-scripts/external_packages.py verify-root $(1) $(TOPDIR)/.external-packages/provenance.json\n'
METADATA = ('json_overview_image_info', 'checksum')
LEAN_RECOVERY = b'lean-native-recovery-without-installer'
OUTER_INSTALLER = b'lean-native-outer-installer'


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def tree_bytes(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in root.rglob('*') if p.is_file()}


def write_installed(root, names):
    database = root / 'lib/apk/db/installed'
    database.parent.mkdir(parents=True, exist_ok=True)
    database.write_text(''.join('P:' + name + '\nV:1\nA:aarch64_cortex-a53\n\n'
                                for name in sorted(names)))


class InstallerBuild(unittest.TestCase):
    def exercise(self, fail=None, dns='dnsmasq-full'):
        script = ROOT / 'scripts/build_installer.py'
        self.assertTrue(script.is_file(), 'missing native incremental installer assembly')
        spec = importlib.util.spec_from_file_location('isolated_build_installer', script)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'; source.mkdir()
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'user.name=fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture', '--allow-empty'], check=True)
            installer = Path(tmp) / 'installer'
            entrypoints = ('installer/install.sh', 'lib/preinit/00_installer')
            for relative in entrypoints:
                path = installer / 'files' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            (source / 'files/etc/apk/repositories.d').mkdir(parents=True)
            (source / 'files/formal').write_bytes(b'formal-overlay')
            (source / 'files/etc/apk/repositories.d/customfeeds.list').write_text('@eamonxg https://fixture.invalid/packages.adb\n')
            (source / 'files/etc/apk/keys').mkdir(parents=True)
            (source / 'files/etc/apk/keys/eamonxg.pem').write_bytes(b'signing-key')
            formal_overlay = tree_bytes(source / 'files')
            package_make = source / 'package/Makefile'
            package_make.parent.mkdir()
            original_make = '# keep native package installation\n' + REFRESH + '# keep remaining rules\n'
            package_make.write_text(original_make)
            rootfs_make = source / 'include/rootfs.mk'
            rootfs_make.parent.mkdir()
            original_rootfs = '# keep native rootfs creation\n' + VERIFY_ROOT + '# keep remaining checks\n'
            rootfs_make.write_text(original_rootfs)
            (source / '.external-packages').mkdir()
            (source / '.external-packages/provenance.json').write_text('{"frozen":true}')
            (source / '.config').write_bytes(b'formal-config\nCONFIG_PACKAGE_luci=y\n')
            original_config = (source / '.config').read_bytes()
            roots = source / 'build_dir/target-test/root-airoha'
            formal_packages = BASE | DRIVERS | APPS | {dns, 'kernel', 'base-files'}
            write_installed(roots, formal_packages)
            profile = json.loads((ROOT / 'user/default/build.json').read_text())
            prefix = profile['system'] + '-airoha-an7581-gemtek_w1700k-ubi-'
            names = [prefix + suffix + '.itb' for suffix in
                     ('squashfs-sysupgrade', 'initramfs-recovery', 'chainload-uboot')]
            upgrade, recovery, chain = names
            directory = source / 'bin/targets' / profile['target']
            directory.mkdir(parents=True)
            for name in names:
                (directory / name).write_bytes(('formal-' + name).encode())
            (directory / 'formal.manifest').write_text('\n'.join(sorted(formal_packages)) + '\n')

            def manifest():
                rows = [dict(name=name, size=(directory / name).stat().st_size,
                             sha256=hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                             type='initramfs' if 'recovery' in name else
                             'chainload-uboot.itb' if 'chainload' in name else 'sysupgrade')
                        for name in names]
                (directory / 'profiles.json').write_text(json.dumps(
                    {'profiles': {'gemtek_w1700k-ubi': {'images': rows}}}))

            manifest()
            original = tree_bytes(directory)
            original_copy = shutil.copytree
            real_run = subprocess.run
            real_rename, real_write = Path.rename, Path.write_bytes
            injected = []

            def rename(path, target):
                if path == source / "files":
                    if fail == "rename-before":
                        injected.append("rename")
                        raise OSError("injected rename failure")
                    result = real_rename(path, target)
                    if fail in ("rename-interrupt", "rename-error"):
                        injected.append("rename")
                        error = KeyboardInterrupt if fail == "rename-interrupt" else OSError
                        raise error("injected rename failure")
                    return result
                return real_rename(path, target)

            def write(path, data):
                if (len(calls) == 6 and fail in ("first-restore-failure", "multi-restore-failure")
                        and (path == package_make or (fail == "multi-restore-failure" and path == rootfs_make))):
                    injected.append(str(path))
                    raise OSError("injected restore failure: " + str(path))
                return real_write(path, data)
            calls, seed_sets, frozen = [], [], {}

            def restore_copy(a, b, *args, **kwargs):
                if fail == 'restore-failure' and calls and len(calls) == 6 and Path(a).name == 'formal-target':
                    raise OSError('injected restore failure')
                return original_copy(a, b, *args, **kwargs)

            def run(command, **kwargs):
                if command[0] == 'git':
                    return real_run(command, **kwargs)
                if 'fwtool' in str(command[0]):
                    Path(command[2]).write_text('{}')
                    return subprocess.CompletedProcess(command, 0)
                self.assertEqual(command[0], 'make', 'no clone, alternate tree or config resolver is allowed')
                self.assertEqual(Path(kwargs['cwd']), source)
                self.assertEqual(kwargs['env']['FORCE_UNSAFE_CONFIGURE'], '1')
                self.assertEqual((source / '.config').read_bytes(), original_config)
                self.assertEqual(package_make.read_text(), original_make.replace(REFRESH, '\t@:\n'))
                self.assertEqual(rootfs_make.read_text(), original_rootfs.replace(VERIFY_ROOT, '\t@:\n'))
                self.assertEqual((source / '.external-packages/provenance.json').read_text(), '{"frozen":true}')
                self.assertFalse((source / 'files/formal').exists())
                self.assertIn('EXTERNAL_PACKAGES=', command)
                self.assertIn('EXTERNAL_REPOSITORIES=', command)
                forbidden = {'world', 'defconfig', 'oldconfig', 'download', 'tools/install', 'toolchain/install'}
                self.assertFalse(forbidden & set(command))
                index = len(calls)
                self.assertLess(index, 6, 'only package/install, target/install and metadata for two passes')
                round_number, stage = divmod(index, 3)
                if stage == 0:
                    self.assertIn('package/install', command)
                    files = [arg.split('=', 1)[1] for arg in command if arg.startswith('PACKAGE_INSTALL_FILES=')]
                    self.assertEqual(len(files), 1)
                    seed_file = Path(files[0])
                    self.assertTrue(seed_file.is_absolute())
                    seeds = set(seed_file.read_text().split())
                    self.assertTrue(BASE | DRIVERS | {dns} <= seeds, 'all necessary base, driver and firmware seeds must survive')
                    self.assertFalse(APPS & seeds, 'formal applications must not become lean seeds')
                    self.assertTrue(seeds <= formal_packages, 'derive seeds from formal installed metadata')
                    seed_sets.append(seeds)
                elif stage == 1:
                    self.assertIn('target/install', command)
                else:
                    self.assertTrue(set(METADATA) <= set(command))
                targets = [arg for arg in command[1:] if not arg.startswith('-j') and '=' not in arg]
                self.assertEqual(targets, [['package/install'], ['target/install'], list(METADATA)][stage])
                if round_number == 0:
                    self.assertFalse((source / 'files/installer').exists())
                    self.assertFalse((source / 'files/lib/preinit/00_installer').exists())
                else:
                    for relative in entrypoints:
                        path = source / 'files' / relative
                        self.assertEqual(path.read_bytes(), (installer / 'files' / relative).read_bytes())
                        self.assertTrue(path.stat().st_mode & 0o111)
                    self.assertEqual((source / 'files/installer' / upgrade).read_bytes(), original[upgrade][0])
                    self.assertEqual((source / 'files/installer' / recovery).read_bytes(), LEAN_RECOVERY)
                    self.assertEqual((source / 'files/installer/payload.sha256').read_text(),
                                     digest(original[upgrade][0])[7:] + '  ' + upgrade + '\n' +
                                     digest(LEAN_RECOVERY)[7:] + '  ' + recovery + '\n')
                    if index == 3:
                        frozen.update({relative: digest((source / 'files' / relative).read_bytes())
                                       for relative in (*entrypoints, 'installer/' + upgrade, 'installer/' + recovery, 'installer/payload.sha256')})
                calls.append(tuple(command))
                if fail == 'inner-build-failure' and index == 1:
                    raise subprocess.CalledProcessError(9, command)
                if fail == 'outer-build-failure' and index == 4:
                    raise subprocess.CalledProcessError(9, command)
                if stage == 0:
                    if round_number == 1 and fail == 'stale-rootfs':
                        return subprocess.CompletedProcess(command, 0)
                    shutil.rmtree(roots)
                    original_copy(source / 'files', roots)
                    installed = set(seed_sets[-1])
                    if ((fail == 'app-leaked' and round_number == 1) or
                            (fail == 'inner-app-leaked' and round_number == 0)):
                        installed.add('luci-theme-aurora')
                    if fail == 'inner-entrypoint' and round_number == 0:
                        path = roots / 'lib/preinit/00_installer'
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text('#!/bin/sh\nexit 0\n')
                    if fail == 'driver-missing' and round_number == 1:
                        installed.remove('kmod-mt7996e')
                    write_installed(roots, installed)
                elif stage == 1:
                    (directory / upgrade).write_bytes(b'not-the-formal-sysupgrade')
                    (directory / recovery).write_bytes(original[recovery][0] if round_number == 0 and fail == 'stale-inner-image' else LEAN_RECOVERY if round_number == 0 else OUTER_INSTALLER)
                    (directory / chain).write_bytes(b'not-the-formal-chainloader')
                else:
                    manifest()
                    if index == 5 and fail == 'config-mutated':
                        (source / '.config').write_bytes(b'changed-config\n')
                    if index == 5 and fail == 'manifest-mutated':
                        for tree in (source / 'files', roots):
                            (tree / 'installer/payload.sha256').write_bytes(b'changed-manifest')
                    if index == 5 and fail == 'overlay-mutated':
                        for tree in (source / 'files', roots):
                            (tree / 'installer' / upgrade).write_bytes(b'changed-payload')
                return subprocess.CompletedProcess(command, 0)

            with patch.object(helper, 'verify_fit') as fit_check, \
                 patch.object(helper, 'verify_metadata') as metadata_check, \
                 patch.object(helper, 'print', create=True) as printed, \
                 patch.object(helper, 'verify_embedded') as embedded_check, \
                 patch.object(Path, 'rename', rename), \
                 patch.object(Path, 'write_bytes', write), \
                 patch.object(helper.shutil, 'copytree', side_effect=restore_copy), \
                 patch.object(helper.subprocess, 'run', side_effect=run):
                errors = {
                    'config-mutated': (ValueError, 'configuration changed'),
                    'overlay-mutated': (ValueError, 'frozen input'),
                    'manifest-mutated': (ValueError, 'frozen input'),
                    'embedded-corrupt': (ValueError, 'embedded mismatch'),
                    'restore-failure': (OSError, 'restor'),
                    'first-restore-failure': (OSError, 'restor'),
                    'multi-restore-failure': (OSError, 'restor'),
                    'rename-before': (OSError, 'rename failure'),
                    'rename-error': (OSError, 'rename failure'),
                    'rename-interrupt': (KeyboardInterrupt, 'rename failure'),
                    'fit-corrupt': (ValueError, 'FIT mismatch'),
                    'metadata-corrupt': (ValueError, 'metadata mismatch'),
                    'inner-build-failure': (subprocess.CalledProcessError, None),
                    'outer-build-failure': (subprocess.CalledProcessError, None),
                    'stale-rootfs': (ValueError, None),
                    'stale-inner-image': (ValueError, 'not regenerated'),
                    'app-leaked': (ValueError, None),
                    'driver-missing': (ValueError, None),
                    'inner-app-leaked': (ValueError, None),
                    'inner-entrypoint': (ValueError, None),
                }
                if fail == 'embedded-corrupt':
                    embedded_check.side_effect = ValueError('injected embedded mismatch')
                if fail == 'fit-corrupt':
                    fit_check.side_effect = ValueError('injected FIT mismatch')
                if fail == 'metadata-corrupt':
                    metadata_check.side_effect = ValueError('injected metadata mismatch')
                if fail:
                    exception, pattern = errors[fail]
                    with (self.assertRaisesRegex(exception, pattern) if pattern else
                          self.assertRaises(exception)) as caught:
                        helper.build(source, installer, profile)
                    if fail in ('first-restore-failure', 'multi-restore-failure'):
                        self.assertIn('package/Makefile', str(caught.exception))
                    if fail == 'multi-restore-failure':
                        self.assertIn('include/rootfs.mk', str(caught.exception))
                else:
                    helper.build(source, installer, profile)
                    self.assertEqual(len(calls), 6)
                    self.assertEqual(seed_sets[0], seed_sets[1])
                    metadata_check.assert_called()
                    self.assertGreaterEqual(fit_check.call_count, 4)
                    embedded_check.assert_called_once()
                    self.assertEqual(embedded_check.call_args.args[1], frozen,
                                     'all five digests must be frozen before the outer make')
                    self.assertEqual(frozen['installer/' + upgrade], digest(original[upgrade][0]))
                    self.assertEqual(frozen['installer/' + recovery], digest(LEAN_RECOVERY))
                reached = {'inner-build-failure': 2, 'outer-build-failure': 5,
                           'inner-app-leaked': 3, 'inner-entrypoint': 3, 'stale-inner-image': 3,
                           'fit-corrupt': 0, 'metadata-corrupt': 0,
                           'rename-before': 0, 'rename-error': 0, 'rename-interrupt': 0}
                self.assertEqual(len(calls), reached.get(fail or '', 6),
                                 'a negative case must reach its intended fault, not fail early')
                timing = [call.args[0] for call in printed.call_args_list
                          if call.args and str(call.args[0]).startswith('Build timing:')]
                if calls:
                    self.assertTrue(timing, 'native rebuild timing must remain visible')
                    if fail in ('inner-build-failure', 'outer-build-failure'):
                        self.assertTrue(any(str(line).endswith('status=9') for line in timing))
                    else:
                        self.assertTrue(all(str(line).endswith('status=0') for line in timing))
            self.assertEqual(package_make.read_text(),
                             original_make.replace(REFRESH, '\t@:\n') if fail in
                             ('first-restore-failure', 'multi-restore-failure') else original_make)
            self.assertEqual(rootfs_make.read_text(), original_rootfs.replace(VERIFY_ROOT, '\t@:\n')
                             if fail == 'multi-restore-failure' else original_rootfs)
            self.assertEqual((source / '.external-packages/provenance.json').read_text(), '{"frozen":true}')
            self.assertEqual((source / '.config').read_bytes(), original_config)
            self.assertEqual(tree_bytes(source / 'files'), formal_overlay)
            if fail in ('restore-failure', 'first-restore-failure', 'multi-restore-failure'):
                backups = list(source.glob('.installer-*/formal-target'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(tree_bytes(backups[0]), original)
                work = backups[0].parent
                self.assertEqual(tree_bytes(work / 'formal-files'), formal_overlay)
                self.assertEqual((work / 'formal-config').read_bytes(), original_config)
                self.assertEqual((work / 'formal-package-Makefile').read_text(), original_make)
                self.assertEqual((work / 'formal-rootfs.mk').read_text(), original_rootfs)
                if fail != 'restore-failure':
                    self.assertEqual(tree_bytes(directory), original)
                    self.assertEqual(len(injected), 2 if fail == 'multi-restore-failure' else 1)
                self.assertFalse((directory / 'installer.json').exists())
                self.assertFalse((directory / (prefix + 'initramfs-installer.itb')).exists())
                self.assertTrue(any('backup retained' in str(call) and str(backups[0].parent) in str(call)
                                    for call in printed.call_args_list))
                return
            expected = dict(original)
            output = prefix + 'initramfs-installer.itb'
            if not fail:
                self.assertEqual((directory / output).read_bytes(), OUTER_INSTALLER)
                proof = json.loads((directory / 'installer.json').read_text())
                self.assertEqual(proof['payload']['digest'], digest(original[upgrade][0]))
                self.assertEqual(proof['recovery']['digest'], digest(LEAN_RECOVERY))
                self.assertEqual(set(proof['recovery_packages']), seed_sets[0])
                self.assertNotEqual(proof['recovery']['digest'], digest(original[recovery][0]))
                self.assertEqual(proof['images'][0]['digest'], digest(OUTER_INSTALLER))
                expected[output] = (OUTER_INSTALLER, (directory / output).stat().st_mode & 0o777)
                expected['installer.json'] = ((directory / 'installer.json').read_bytes(),
                                              (directory / 'installer.json').stat().st_mode & 0o777)
            self.assertEqual(tree_bytes(directory), expected)
            self.assertFalse(list(source.glob('.installer-*')), 'successful restoration should remove temporary backups')

    def test_two_native_lean_passes_preserve_same_build_payload_and_formal_inputs(self):
        for dns in ('dnsmasq', 'dnsmasq-full'):
            with self.subTest(dns=dns):
                self.exercise(dns=dns)

    def test_native_failure_at_either_pass_restores_formal_inputs(self):
        for fail in ('inner-build-failure', 'outer-build-failure'):
            with self.subTest(fail=fail):
                self.exercise(fail)

    def test_rejects_stale_or_nonlean_native_root(self):
        for fail in ('stale-inner-image', 'stale-rootfs', 'app-leaked', 'driver-missing',
                     'inner-app-leaked', 'inner-entrypoint'):
            with self.subTest(fail=fail):
                self.exercise(fail)

    def test_frozen_config_overlay_and_embedded_fit_checks_remain_enforced(self):
        for fail in ('config-mutated', 'overlay-mutated', 'manifest-mutated', 'embedded-corrupt'):
            with self.subTest(fail=fail):
                self.exercise(fail)

    def test_native_fit_and_sysupgrade_metadata_checks_remain_enforced(self):
        for fail in ('fit-corrupt', 'metadata-corrupt'):
            with self.subTest(fail=fail):
                self.exercise(fail)

    def test_restore_failure_retains_complete_backup_and_tries_remaining_items(self):
        for fail in ('restore-failure', 'first-restore-failure', 'multi-restore-failure'):
            with self.subTest(fail=fail):
                self.exercise(fail)

    def test_interruptions_before_and_after_overlay_rename_restore_formal_inputs(self):
        for fail in ('rename-before', 'rename-error', 'rename-interrupt'):
            with self.subTest(fail=fail):
                self.exercise(fail)
