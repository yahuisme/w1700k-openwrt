#!/usr/bin/env python3
"""Execute defaults with isolated UCI fixtures; never touch host configuration."""
import itertools
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'user/default/files/etc/uci-defaults/99-w1700k-defaults'
MOCK = r'''
uci() {
    [ "$1" != -q ] || shift
    case "$1" in
        show) printf '%s\n' "$RADIOS" "$IFACES"; return;;
        get) case "$2" in
            wireless.radio2.band) echo 2g;;
            wireless.radio5.band) echo 5g;;
            wireless.radio6.band) echo 6g;;
        esac; return;;
    esac
    printf '%s\n' "$*"
}
'''


def state_after(output, initial):
    state = dict(initial)
    for line in output.splitlines():
        op, value = line.split(' ', 1)
        if op == 'delete':
            state = {k: v for k, v in state.items()
                     if k != value and not k.startswith(value + '.')}
        else:
            key, val = value.split('=', 1)
            if op == 'add_list':
                state[key] = state.get(key, []) + [val]
            else:
                assert op == 'set', op
                state[key] = val
    return state


class DefaultsCleanup(unittest.TestCase):
    def test_equivalence(self):
        current = SCRIPT.read_text()
        # Reintroduce only the removed commands, independently of git history.
        previous = current
        for band in '256':
            line = f'    IFACE_{band}G="wifinet{band}g"\n'
            self.assertEqual(previous.count(line), 1)
            previous = previous.replace(line, line + f'    uci -q delete wireless.${{IFACE_{band}G}}\n')
        with tempfile.TemporaryDirectory() as tmp:
            def run(script, env):
                script = script.replace('/sysupgrade.tgz', tmp + '/sysupgrade.tgz')
                script = script.replace('/tmp/sysupgrade.tar', tmp + '/sysupgrade.tar')
                result = subprocess.run(['busybox', 'ash', '-c', MOCK + script],
                                        env=dict(os.environ, **env), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            for bands in itertools.product((False, True), repeat=3):
                for existing in (False, True):
                    with self.subTest(bands=bands, existing=existing):
                        initial: dict[str, str | list[str]] = {'network.lan.ipaddr': ['old-address']}
                        if existing:
                            for name in ('wifinet2g', 'wifinet5g', 'wifinet6g'):
                                initial[f'wireless.{name}'] = 'wifi-iface'
                                initial[f'wireless.{name}.obsolete'] = 'old'
                        env = dict(RADIOS='\n'.join(f'wireless.radio{b}=wifi-device'
                                                   for b, enabled in zip('256', bands) if enabled),
                                   IFACES='\n'.join(f'{k}={v}' for k, v in initial.items() if v == 'wifi-iface'))
                        old, new = run(previous, env), run(current, env)
                        self.assertEqual(state_after(old, initial), state_after(new, initial))
                        self.assertEqual(len(old.splitlines()) - len(new.splitlines()), sum(bands))
                        if all(bands) and existing:
                            self.assertEqual((len(old.splitlines()), len(new.splitlines())), (53, 50))
            for marker in ('sysupgrade.tgz', 'sysupgrade.tar'):
                path = Path(tmp) / marker
                path.touch()
                for script in (previous, current):
                    self.assertEqual(run(script, dict(RADIOS='', IFACES='')),
                                     'Keeping existing configuration restored by sysupgrade.\n')
                path.unlink()


if __name__ == '__main__':
    unittest.main()
