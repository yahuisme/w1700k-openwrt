#!/usr/bin/env python3
"""Real BusyBox boot caller + native UCI in a disposable chroot, no host config.

Run with DEFAULTS_BOOT_SOURCE=<official etc/init.d/boot> to replay its exact
uci_apply_defaults body; the built-in caller preserves the same && semantics.
Source /opt/test-tools/env.sh before running. No builds or device access.
"""
import itertools
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'user/default/files/etc/uci-defaults/99-w1700k-defaults'
CALLER = '''uci_apply_defaults() {
 . /lib/functions/system.sh
 cd /etc/uci-defaults || return 0
 files="$(ls)"
 [ -z "$files" ] && return 0
 applied=""
 for file in $files; do
  ( . "./$(basename $file)" ) && applied="$applied $file"
 done
 uci commit
 sync
 rm -f $applied
}
'''


class DefaultsCleanup(unittest.TestCase):
    def run_boot(self, bands=('2g', '5g', '6g'), fault='', marker=None, anonymous=False,
                 reapply=False, operator_reboot=False):
        self.assertEqual(os.geteuid(), 0, 'isolated chroot requires root')
        uci = os.environ.get('DEFAULTS_UCI') or shutil.which('uci')
        self.assertTrue(uci, 'source /opt/test-tools/env.sh (native UCI required)')
        assert uci is not None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('bin', 'sbin', 'lib/functions', 'etc/config', 'etc/uci-defaults',
                         'tmp/.uci', 'var/run/uci', 'dev'):
                (root / name).mkdir(parents=True)
            (root / 'tmp').chmod(0o1777)
            for binary, destination in (('/usr/bin/busybox', 'bin/busybox'), (uci, 'sbin/uci-real')):
                shutil.copy2(binary, root / destination)
                result = subprocess.check_output(['ldd', binary], text=True)
                for token in result.split():
                    if token.startswith('/') and Path(token).is_file():
                        dest = root / token.lstrip('/')
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(token, dest)
            for applet in ('sh', 'ash', 'ls', 'basename', 'sync', 'rm', 'sed', 'mktemp',
                           'mkdir', 'cp', 'mv', 'cat', 'chmod'):
                (root / 'bin' / applet).symlink_to('busybox')
            (root / 'dev/null').touch()
            (root / 'lib/functions/system.sh').touch()
            (root / 'sbin/uci').write_text('''#!/bin/sh
printf '%s\\n' "$*" >> /calls
run_uci() {
op=''; key=''
while [ "$#" -gt 0 ]; do
 case "$1" in -c|-C|-t|-p|-P|-f) shift 2;; -*) shift;; *) op="$1"; key="$2"; break;; esac
done
case "$op" in
 set|delete|add_list)
  count=0; [ ! -f /write-count ] || read -r count < /write-count
  count=$((count + 1)); echo "$count" > /write-count
  [ "$FAULT" != "write-$count" ] || return 1;;
esac
case "$FAULT:$op:$key" in
 show:show:wireless|read:get:wireless.radio5.band|ipaddr:add_list:network.lan.ipaddr=*|ssid:set:wireless.wifinet2g.ssid=*) return 1;;
esac
return 0
}
run_uci "$@" || exit $?
exec /sbin/uci-real "$@"
''')
            (root / 'sbin/uci').chmod(0o755)
            for command in ('cp', 'cat', 'mv'):
                target = root / 'bin' / command
                target.unlink()
                target.write_text('#!/bin/sh\n' + {
                    'cp': '[ "$FAULT" != copy ] || exit 1\n',
                    'cat': '[ "$FAULT" != append ] || exit 1\n',
                    'mv': '''case "$FAULT:$1" in
 signal-before-publish-*:*/next)
  echo "$FAULT" >> /fault-events
  kill -"${FAULT##*-}" "$PPID"
  exit 1;;
 publish-missing-source:*/next)
  # Real BusyBox rename fails with ENOENT, not merely an injected status.
  /bin/busybox rm -rf "$1"
  exec /bin/busybox mv "$@";;
 signal-after-publish-*:*/next|nonzero-after-publish:*/next)
  /bin/busybox mv "$@" || exit $?
  echo "$FAULT" >> /fault-events
  case "$FAULT" in
   signal-after-publish-*) kill -"${FAULT##*-}" "$PPID"; exit 0;;
   *) exit 1;;
  esac;;
 signal-after-backup-*:/tmp/.uci)
  /bin/busybox mv "$@" || exit $?
  # PPID is the actual shell sourcing production defaults, not the boot shell.
  if [ "$FAULT" = signal-after-backup-child-TERM ]; then
   kill -TERM $$
  else
   kill -"${FAULT##*-}" "$PPID"
  fi
  exit 1;;
esac
[ "$FAULT:$2" != publish-and-restore-fail:/tmp/.uci ] || exit 1
[ "$FAULT:$2" != publish:/tmp/.uci ] || [ "$1" != "${1%/next}/next" ] || exit 1
''',
                }[command] + f'exec /bin/busybox {command} "$@"\n')
                target.chmod(0o755)
            # Earlier successful defaults may already have uncommitted changes.
            configs = {
                'system': "config system 'main'\n option hostname 'operator'\n",
                'network': "config interface 'lan'\n option ipaddr '192.168.99.1'\n",
                'wireless': ''.join(f"config wifi-device 'radio{b[0]}'\n option band '{b}'\n" for b in bands)
                            + "config wifi-iface 'operator'\n option ssid 'private'\n",
                'dhcp': "config dhcp 'lan'\n", 'luci': "config core 'main'\n",
                'firewall': "config defaults\n option flow_offloading_hw '0'\n",
            }
            if anonymous:
                configs['wireless'] += "config wifi-iface\n option ssid 'anonymous-a'\nconfig wifi-iface\n option ssid 'anonymous-b'\n"
            for name, text in configs.items():
                (root / 'etc/config' / name).write_text(text)
            (root / 'tmp/.uci/system').write_text("system.main.description='earlier-default'\n")
            script = root / 'etc/uci-defaults' / SCRIPT.name
            shutil.copy2(SCRIPT, root / 'production-defaults')
            script.write_text('( . /production-defaults )\nstatus=$?\necho "$status" > /defaults-status\nexit "$status"\n')
            if marker:
                (root / marker).touch()
            caller = CALLER
            if os.environ.get('DEFAULTS_BOOT_SOURCE'):
                source = Path(os.environ['DEFAULTS_BOOT_SOURCE']).read_text()
                caller = source[source.index('uci_apply_defaults() {'):source.index('\nboot() {')]
            (root / 'boot-caller').write_text(caller + '\nuci_apply_defaults\n')
            env = dict(os.environ, PATH='/sbin:/bin', FAULT=fault)
            def sh(code):
                return subprocess.run(['/usr/sbin/chroot', str(root), '/bin/sh', '-c', code],
                                      env=env, capture_output=True, text=True)
            before = sh('uci export').stdout
            (root / 'calls').write_text('')
            result = sh('. /boot-caller')
            fault_events = (root / 'fault-events').read_text().splitlines() if (root / 'fault-events').exists() else []
            if fault.startswith(('signal-before-publish-', 'signal-after-publish-')) or fault == 'nonzero-after-publish':
                self.assertEqual(fault_events, [fault], 'the actual rename boundary must be reached')
            calls = (root / 'calls').read_text().splitlines()
            after = sh('uci export').stdout
            retained = script.exists()
            status = int((root / 'defaults-status').read_text())
            self.assertEqual(status != 0, retained, (status, calls))
            leftovers = list((root / 'tmp').glob('w1700k-defaults.*'))
            backups = {str(p.relative_to(root)): (p / 'previous/system').read_text()
                       for p in leftovers if (p / 'previous/system').is_file()}
            pending = sh('uci changes').stdout
            operator_after = None
            if operator_reboot:
                changed = sh("uci set network.lan.ipaddr='192.168.55.1'; "
                             "uci set system.main.hostname='operator-after-boot'; uci commit")
                self.assertEqual(changed.returncode, 0, changed.stderr)
                operator_after = sh('uci export').stdout
                self.assertIn("option ipaddr '192.168.55.1'", operator_after)
                self.assertIn("option hostname 'operator-after-boot'", operator_after)
                # Fault delivery is one-shot; the next boot must not reapply defaults.
                env['FAULT'] = ''
                again = sh('. /boot-caller')
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertEqual(sh('uci export').stdout, operator_after,
                                 'published defaults must not overwrite later operator changes')
                self.assertFalse(script.exists())
            if fault == 'publish-and-restore-fail':
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(retained, calls)
                self.assertEqual(len(leftovers), 1, result.stderr)
                previous = leftovers[0] / 'previous'
                self.assertEqual((previous / 'system').read_text(),
                                 "system.main.description='earlier-default'\n")
                self.assertIn(f'/{previous.relative_to(root)}', result.stderr)
                self.assertIn('restore failed', result.stderr)
                self.assertNotIn("option description 'earlier-default'", after)
                # Prove the preserved backup is usable, not merely a directory.
                recovery = sh(f'/bin/busybox mv /{previous.relative_to(root)} /tmp/.uci; uci commit')
                self.assertEqual(recovery.returncode, 0, recovery.stderr)
                self.assertEqual(sh('uci export').stdout, before)
                self.assertEqual(sh('uci changes').stdout, '')
            else:
                self.assertEqual(leftovers, [])
            # Replaying a successful boot cannot reapply removed defaults.
            if not retained and not operator_reboot:
                if reapply:
                    script.write_text('( . /production-defaults )\nstatus=$?\necho "$status" > /defaults-status\nexit "$status"\n')
                again = sh('. /boot-caller')
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertEqual(sh('uci export').stdout, after)
                self.assertFalse(script.exists())
                self.assertEqual(list((root / 'tmp').glob('w1700k-defaults.*')), [])
            if os.environ.get('DEFAULTS_EVIDENCE'):
                import json
                with Path(os.environ['DEFAULTS_EVIDENCE']).open('a') as evidence:
                    evidence.write(json.dumps(dict(bands=bands, fault=fault, marker=marker,
                        anonymous=anonymous, defaults_status=status, boot_status=result.returncode,
                        script_retained=retained, before=before, after=after, calls=calls,
                        pending=pending, stderr=result.stderr, backups=backups,
                        operator_after=operator_after, fault_events=fault_events), ensure_ascii=False) + '\n')
            return result, before, after, calls, retained, pending

    def test_failed_required_write_is_not_committed_by_boot(self):
        for fault in ('ipaddr', 'ssid', 'copy', 'append', 'publish', 'publish-missing-source'):
            with self.subTest(fault=fault):
                result, before, after, calls, retained, pending = self.run_boot(fault=fault)
                if fault == 'publish-missing-source':
                    self.assertIn('No such file or directory', result.stderr)
                self.assertTrue(retained, (result.stderr, calls))
                self.assertEqual(after, before, calls)
                self.assertEqual(pending, '')

    def test_signal_after_publish_is_success_and_preserves_operator_changes(self):
        for signal in ('TERM', 'INT', 'HUP'):
            with self.subTest(signal=signal):
                result, _, after, calls, retained, pending = self.run_boot(
                    fault=f'signal-after-publish-{signal}', operator_reboot=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(retained, calls)
                self.assertIn("option hostname 'W1700K'", after)
                self.assertIn("list ipaddr '192.168.8.1/24'", after)
                self.assertEqual(pending, '')

    def test_nonzero_after_publish_is_success_and_preserves_operator_changes(self):
        result, _, after, calls, retained, pending = self.run_boot(
            fault='nonzero-after-publish', operator_reboot=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(retained, calls)
        self.assertIn("option description 'earlier-default'", after)
        self.assertIn("list ipaddr '192.168.8.1/24'", after)
        self.assertEqual(pending, '')

    def test_signal_before_publish_restores_earlier_defaults(self):
        for signal in ('TERM', 'INT', 'HUP'):
            with self.subTest(signal=signal):
                result, before, after, calls, retained, pending = self.run_boot(
                    fault=f'signal-before-publish-{signal}')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(retained, calls)
                self.assertEqual(after, before, calls)
                self.assertEqual(pending, '')

    def test_signal_after_backup_restores_earlier_defaults(self):
        for signal in ('TERM', 'INT', 'HUP', 'child-TERM'):
            with self.subTest(signal=signal):
                result, before, after, calls, retained, pending = self.run_boot(
                    fault=f'signal-after-backup-{signal}')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(retained, calls)
                self.assertIn("option description 'earlier-default'", before)
                self.assertEqual(after, before, calls)
                self.assertEqual(pending, '')

    def test_failed_restore_keeps_recoverable_previous_defaults(self):
        result, _, _, calls, retained, pending = self.run_boot(fault='publish-and-restore-fail')
        self.assertTrue(retained, calls)
        self.assertEqual(pending, '')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_required_uci_write_fails_closed(self):
        _, _, _, calls, retained, _ = self.run_boot()
        self.assertFalse(retained)
        writes = [c for c in calls if any(f' {op} ' in f' {c} ' for op in ('set', 'delete', 'add_list'))]
        self.assertGreater(len(writes), 40)
        for index in range(1, len(writes) + 1):
            with self.subTest(index=index, command=writes[index - 1]):
                result, before, after, actual, retained, pending = self.run_boot(fault=f'write-{index}')
                self.assertTrue(retained, (result.stderr, actual))
                self.assertEqual(after, before, actual)
                self.assertEqual(pending, '')
                self.assertEqual(sum(any(f' {op} ' in f' {c} ' for op in ('set', 'delete', 'add_list')) for c in actual), index)

    def test_anonymous_interfaces_are_all_replaced(self):
        result, _, after, calls, retained, _ = self.run_boot(anonymous=True)
        self.assertFalse(retained, (result.stderr, calls))
        self.assertNotIn('anonymous-', after)
        self.assertEqual(after.count('config wifi-iface'), 3)

    def test_reapplying_complete_defaults_is_idempotent(self):
        self.run_boot(reapply=True)

    def test_complete_defaults_and_retained_guards(self):
        result, before, after, calls, retained, pending = self.run_boot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(retained, (result.stderr, calls))
        for expected in ("option hostname 'W1700K'", "list ipaddr '192.168.8.1/24'",
                         "option description 'earlier-default'", "option flow_offloading_hw '1'",
                         "option txpower '23'", "option txpower '25'", "option ssid 'W1700K-6G'",
                         "option encryption 'sae+ccmp'", "option htmode 'EHT320'"):
            self.assertIn(expected, after)
        self.assertNotIn("config wifi-iface 'operator'", after)
        self.assertEqual(pending, '')
        for marker in ('sysupgrade.tgz', 'tmp/sysupgrade.tar'):
            with self.subTest(marker=marker):
                result, before, after, calls, retained, _ = self.run_boot(marker=marker)
                self.assertEqual(after, before)
                self.assertFalse(retained)
                self.assertEqual(calls, ['commit'])

    def test_incomplete_or_unreadable_radios_do_not_write(self):
        for enabled in itertools.product((False, True), repeat=3):
            if all(enabled):
                continue
            bands = tuple(b for b, present in zip(('2g', '5g', '6g'), enabled) if present)
            with self.subTest(bands=bands):
                result, before, after, calls, retained, _ = self.run_boot(bands=bands)
                self.assertTrue(retained, (result.stderr, calls))
                self.assertEqual(after, before)
                self.assertFalse(any((' set ' in f' {c} ' or ' delete ' in f' {c} ' or ' add_list ' in f' {c} ') for c in calls), calls)
        for fault in ('show', 'read'):
            with self.subTest(fault=fault):
                result, before, after, calls, retained, _ = self.run_boot(fault=fault)
                self.assertTrue(retained, (result.stderr, calls))
                self.assertEqual(after, before)
                self.assertFalse(any(' set ' in f' {c} ' for c in calls), calls)


if __name__ == '__main__':
    unittest.main()
