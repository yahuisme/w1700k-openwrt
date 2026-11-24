"""Exercise Aurora defaults through native boot and UCI in a private chroot."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_defaults_cleanup import CALLER

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / 'user/default/files/etc/uci-defaults'
AURORA = '99-w1700k-aurora'
MAIN = '99-w1700k-defaults'
NAV = 'aurora.theme.nav_type'
RADIUS = 'aurora.theme.struct_radius_base'


class AuroraDefaultsTests(unittest.TestCase):
    def run_boot(self, *, retained=None, section='aurora', fault='', main=False, already=False):
        self.assertEqual(os.geteuid(), 0, 'isolated chroot requires root')
        uci = os.environ.get('DEFAULTS_UCI') or shutil.which('uci')
        if not uci:
            self.fail('source /opt/test-tools/env.sh (native UCI required)')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('bin', 'sbin', 'etc/config', 'etc/uci-defaults', 'lib/functions',
                         'tmp/.uci', 'var/run/uci', 'dev'):
                (root / name).mkdir(parents=True)
            for binary, destination in (('/usr/bin/busybox', 'bin/busybox'), (uci, 'sbin/uci-real')):
                shutil.copy2(binary, root / destination)
                for token in subprocess.check_output(['ldd', binary], text=True).split():
                    if token.startswith('/') and Path(token).is_file():
                        target = root / token.lstrip('/')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(token, target)
            for applet in ('sh', 'ls', 'basename', 'rm', 'sed', 'mktemp', 'mkdir', 'cp', 'cat', 'ln'):
                (root / 'bin' / applet).symlink_to('busybox')
            for name in ('dev/null', 'lib/functions/system.sh'):
                (root / name).touch()
            for name, text in {
                'bin/sync': '#!/bin/sh\nexit 0\n',
                'bin/mv': '''#!/bin/sh
if [ "$3" = /tmp/.uci/aurora ]; then
    case "$FAULT" in
        publish|missing-source)
            echo "$FAULT" >> /faults
            [ "$FAULT" = missing-source ] || exit 1
            rm "$2" || exit 1;;
        before-*)
            echo "$FAULT" >> /faults
            kill -"${FAULT#before-}" "$PPID"
            exit 1;;
        after-*|nonzero-after)
            /bin/busybox mv "$@" || exit $?
            echo "$FAULT" >> /faults
            [ "$FAULT" != nonzero-after ] || exit 1
            kill -"${FAULT#after-}" "$PPID"
            exit 0;;
    esac
fi
exec /bin/busybox mv "$@"
''',
                'sbin/uci': '''#!/bin/sh
printf '%s\\n' "$*" >> /calls
# Fail just the targeted set; all real changes (and native boot's commit)
# otherwise go through the installed UCI binary and its delta directories.
for arg; do
    if [ -n "$FAULT" ] && [ "${arg%%=*}" = "$FAULT" ]; then
        printf '%s\\n' "$FAULT" >> /faults
        exit 1
    fi
done
exec /sbin/uci-real "$@"
''',
            }.items():
                path = root / name
                path.write_text(text)
                path.chmod(0o755)
            configs = {
                'aurora': (f"config {section} 'theme'\n"
                           "option nav_type 'mega-menu'\noption struct_radius_base '0.5rem'\n"
                           "option light_brand '#0086bf'\noption toolbar_enabled '1'\n") if section else '',
                'system': "config system 'main'\noption hostname 'operator'\n",
                'network': "config interface 'lan'\noption ipaddr '192.168.1.1'\n",
                'wireless': ''.join(f"config wifi-device 'radio{n}'\noption band '{band}'\n"
                                    for n, band in enumerate(('2g', '5g', '6g'))),
                'dhcp': "config dhcp 'lan'\n", 'luci': "config core 'main'\n",
                'firewall': "config defaults\noption flow_offloading_hw '0'\n",
            }
            if already:
                configs['aurora'] = (configs['aurora'].replace("'mega-menu'", "'sidebar'")
                                     .replace("'0.5rem'", "'0.125rem'"))
            for name, text in configs.items():
                (root / 'etc/config' / name).write_text(text)
            if section:
                (root / 'tmp/.uci/aurora').write_text("aurora.theme.toolbar_enabled='0'\n")
            (root / 'tmp/.uci/system').write_text("system.main.description='earlier-default'\n")
            scripts = root / 'etc/uci-defaults'
            shutil.copy2(DEFAULTS / AURORA, scripts)
            if main:
                shutil.copy2(DEFAULTS / MAIN, scripts)
            if retained:
                (root / retained.lstrip('/')).touch()
            caller = CALLER
            if os.environ.get('DEFAULTS_BOOT_SOURCE'):
                source = Path(os.environ['DEFAULTS_BOOT_SOURCE']).read_text()
                caller = source[source.index('uci_apply_defaults() {'):source.index('\nboot() {')]
            (root / 'boot-caller').write_text(caller + '\nuci_apply_defaults\n')
            env = dict(os.environ, PATH='/sbin:/bin', FAULT=fault)

            def sh(code):
                return subprocess.run(['/usr/sbin/chroot', str(root), '/bin/sh', '-c', code],
                                      env=env, capture_output=True, text=True, check=True).stdout

            before = sh('/sbin/uci-real show')
            sh('. /boot-caller')
            after = sh('/sbin/uci-real show')
            calls = (root / 'calls').read_text().splitlines()
            exists = (scripts / AURORA).exists()
            self.assertEqual(sh('/sbin/uci-real changes'), '')
            self.assertEqual(list((root / 'tmp').glob('w1700k-aurora.*')), [])
            if fault:
                faults = root / 'faults'
                self.assertTrue(faults.exists(), f'fault not reached: {fault}')
                self.assertEqual(faults.read_text().splitlines(), [fault])
            if not exists:
                # An already applied script must not run again on later boots.
                sh('. /boot-caller')
                self.assertEqual(sh('/sbin/uci-real show'), after)
                self.assertEqual((root / 'calls').read_text().splitlines(), calls)
            return before, after, calls, exists

    def test_after_package_initialization_only_two_defaults_change(self):
        self.assertGreater(AURORA, '80_aurora')
        before, after, _, exists = self.run_boot()
        self.assertEqual(after, before.replace("nav_type='mega-menu'", "nav_type='sidebar'")
                         .replace("struct_radius_base='0.5rem'", "struct_radius_base='0.125rem'"))
        self.assertIn("aurora.theme.toolbar_enabled='0'", after)
        self.assertIn("system.main.description='earlier-default'", after)
        self.assertFalse(exists)

    def test_retained_upgrade_is_untouched_before_any_uci_access(self):
        for marker in ('/sysupgrade.tgz', '/tmp/sysupgrade.tar'):
            with self.subTest(marker=marker):
                before, after, calls, exists = self.run_boot(retained=marker, main=True)
                self.assertEqual(after, before)
                self.assertEqual(calls, ['commit'])
                self.assertFalse(exists)

    def test_missing_or_unknown_section_is_not_created_or_overwritten(self):
        for section in ('', 'unknown'):
            with self.subTest(section=section):
                before, after, calls, exists = self.run_boot(section=section)
                self.assertEqual(after, before)
                self.assertTrue(exists)
                self.assertFalse(any(' set ' in call for call in calls))

    def test_failed_writes_are_not_committed_and_script_is_retained(self):
        for key in (NAV, RADIUS):
            with self.subTest(key=key):
                before, after, _, exists = self.run_boot(fault=key)
                self.assertEqual(after, before)
                self.assertTrue(exists)

    def test_main_defaults_preserve_aurora_publication_or_failed_transaction(self):
        for fault in ('', RADIUS):
            with self.subTest(fault=fault):
                _, after, _, exists = self.run_boot(fault=fault, main=True)
                self.assertIn("system.main.hostname='W1700K'", after)
                self.assertIn("network.lan.ipaddr='192.168.8.1/24'", after)
                self.assertIn("aurora.theme.toolbar_enabled='0'", after)
                self.assertIn("system.main.description='earlier-default'", after)
                self.assertIn(f"{NAV}='{'mega-menu' if fault else 'sidebar'}'", after)
                self.assertIn(f"{RADIUS}='{'0.5rem' if fault else '0.125rem'}'", after)
                self.assertEqual(exists, bool(fault))

    def test_failed_publication_keeps_earlier_deltas_and_script(self):
        for fault in ('publish', 'missing-source', 'before-HUP', 'before-INT', 'before-TERM'):
            with self.subTest(fault=fault):
                before, after, _, exists = self.run_boot(fault=fault)
                self.assertEqual(after, before)
                self.assertTrue(exists)

    def test_report_success_if_publication_happened_before_signal_or_mv_error(self):
        for fault in ('after-HUP', 'after-INT', 'after-TERM', 'nonzero-after'):
            with self.subTest(fault=fault):
                _, after, _, exists = self.run_boot(fault=fault)
                self.assertIn(f"{NAV}='sidebar'", after)
                self.assertIn(f"{RADIUS}='0.125rem'", after)
                self.assertIn("aurora.theme.toolbar_enabled='0'", after)
                self.assertFalse(exists)

    def test_already_correct_settings_do_not_require_a_delta_file(self):
        before, after, _, exists = self.run_boot(already=True)
        self.assertEqual(after, before)
        self.assertFalse(exists)


if __name__ == '__main__':
    unittest.main()
