"""Execute real LuCI views with harmless boundaries; no reset/flash commands.

DEVICE_FLASH_JS: exact upstream or released full system/flash.js.
DEVICE_ROOTFS: verified extracted release rootfs (read-only).
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FLASH = 'feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js'


def node(code, *args):
    result = subprocess.run(['node', '-e', code, *map(str, args)], text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


FLASH_RUN = r"""
const assert = require('node:assert/strict');
const code = require('node:fs').readFileSync(process.argv[1], 'utf8');
const reconnect = [], commands = [];
const host = '192.168.99.1:8080';
// Execute trusted local upstream view bytes only, with inert fs/DOM/RPC boundaries.
const view = new Function('view','dom','form','rpc','fs','ui','L','E','_','confirm','window', code)(
 {extend: x => x}, {}, {}, {declare: () => () => Promise.resolve({})},
 {exec: (...args) => {commands.push(args); return Promise.resolve({code: 0});}},
 {showModal: () => {}, awaitReconnect: (...args) => reconnect.push(args)},
 {hasViewPermission: () => true, bind: (f, ctx, ...a) => f.bind(ctx, ...a)},
 () => ({}), x => x, () => true, {location: {host}});
const expected = process.argv[2];
view.handleFirstboot({});
assert.equal(reconnect[0][0], expected);
assert.deepEqual(commands.shift(), ['/sbin/firstboot', ['-r','-y']]);
const hostname = reconnect[0][1];
for (const keep of [true, false]) {
 view.handleSysupgradeConfirm({firstChild: {}}, {keep: [{checked: keep},false,'-n']}, {});
 assert.deepEqual(reconnect.at(-1), keep ? [host] : [host,expected,hostname]);
 assert.deepEqual(commands.shift(), ['/sbin/sysupgrade', keep ? ['/tmp/firmware.bin'] : ['-n','/tmp/firmware.bin']]);
}
(async () => {
 await view.handleRestoreConfirm({firstChild: {}}, {target: {firstChild: {}}});
 assert.deepEqual(reconnect.at(-1), [host,expected,hostname]);
 assert.deepEqual(commands, [['/sbin/sysupgrade',['--restore-backup','/tmp/backup.tar.gz']],['/sbin/reboot']]);
 console.log(JSON.stringify(reconnect));
})().catch(e => {console.error(e); process.exitCode=1;});
"""


@unittest.skipUnless(os.environ.get('DEVICE_FLASH_JS'), 'set DEVICE_FLASH_JS to real full LuCI view')
class FlashReconnect(unittest.TestCase):
    def customize(self, directory, content):
        work = Path(directory)
        for path, text in {
            'package/base-files/files/etc/banner': '%D %V, %C\n',
            'package/base-files/files/etc/openwrt_release': '%D %V %C\n',
            'package/base-files/files/usr/lib/os-release': 'PRETTY_NAME="%D %V"\n',
        }.items():
            dest = work / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
        target = work / FLASH
        if content is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        script = (ROOT / 'user/default/custom.sh').read_text()
        prefix = script[:script.index('# Fetch W1700K LuCI apps')]
        result = subprocess.run(['bash', '-ec', prefix + '\necho CONTINUED'], cwd=work,
                                text=True, capture_output=True)
        return result, target

    def test_reset_upgrade_restore_reconnect_and_idempotence(self):
        original = Path(os.environ['DEVICE_FLASH_JS']).read_text()
        with tempfile.TemporaryDirectory() as directory:
            result, target = self.customize(directory, original)
            self.assertEqual(result.returncode, 0, result.stderr)
            node(FLASH_RUN, target, '192.168.8.1')
            patched = target.read_text()
            self.assertEqual(patched.replace('192.168.8.1', '192.168.1.1'), original)
            result, target = self.customize(directory, patched)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(), patched)

    def test_unknown_upstream_or_missing_view_fails_closed(self):
        original = Path(os.environ['DEVICE_FLASH_JS']).read_text()
        self.assertIn('192.168.1.1', original)
        for content in (None, original.replace('192.168.1.1', '192.168.2.1'),
                        original.replace('192.168.1.1', '192.168.2.1', 1)):
            with self.subTest(missing=content is None), tempfile.TemporaryDirectory() as directory:
                result, _ = self.customize(directory, content)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('CONTINUED', result.stdout)


class FanWidget(unittest.TestCase):
    def test_real_render_stopped_invalid_and_running(self):
        widget = ROOT / 'user/default/files/www/luci-static/resources/view/status/include/15_temperature.js'
        node(r"""
const assert = require('node:assert/strict');
// Trusted local view bytes only; fs/RPC/DOM are inert and never execute commands.
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
function E(tag, attrs, children) {
 const n = {attrs, children: [], appendChild(x) { this.children.push(x); }};
 if (children != null) n.children = Array.isArray(children) ? children : [children];
 return n;
}
const widget = new Function('baseclass','rpc','L','E','_',source)(
 {extend:x=>x}, {declare:()=>()=>Promise.resolve({})}, {}, E, x=>x);
function text(n) {return typeof n === 'object' ? n.children.map(text).join('|') : String(n);}
for (const [rpm, pct, expected] of [
 [0,0,'0 RPM · 0%'], [1000,30,'1000 RPM · 30%'], [1000,0,'1000 RPM · 0%'],
 [1000,null,'1000 RPM'], [null,0,'--'], [undefined,0,'--'], [-1,0,'--'],
 [NaN,0,'--'], [Infinity,0,'--'], [-Infinity,0,'--'], ['invalid',0,'--']]) {
 const tree = widget.render({temp_cpu:42, fan_rpm:rpm, fan_percentage:pct});
 assert.equal(text(tree.children.at(-1)), 'Fan|' + expected, String(rpm));
 assert.equal(text(tree.children[0]), 'CPU|42 °C');
}
for (const [value, expected] of [[0,'0 °C'],[-12,'-12 °C'],[42,'42 °C'],[null,'--'],[undefined,'--'],[NaN,'--'],[Infinity,'--']]) {
 const tree = widget.render({temp_board:value});
 assert.equal(text(tree.children[1]), 'Motherboard|' + expected, String(value));
 const style = tree.children[1].children[1].attrs.style;
 assert.equal(style.includes('color:'), expected !== '--', String(value));
}
assert.equal(text(widget.render(null).children.at(-1)), 'Fan|--');
""", widget)


class SysctlDefaults(unittest.TestCase):
    def test_acceleration_defaults_and_retention(self):
        files = ROOT / 'user/default/files'
        keep = (files / 'lib/upgrade/keep.d/w1700k-offload').read_text().splitlines()
        self.assertEqual(keep, ['/etc/sysctl.d/12-apmode-offload.conf',
                                '/etc/sysctl.d/14-vlan-offload.conf',
                                '/etc/sysctl.d/15-pppoe-offload.conf'])
        for name, key in (('14-vlan-offload.conf', 'vlan'), ('15-pppoe-offload.conf', 'pppoe')):
            self.assertEqual((files / 'etc/sysctl.d' / name).read_text(),
                             f'net.bridge.bridge-nf-filter-{key}-tagged=1\n')
        self.assertEqual((files / 'etc/sysctl.d/12-apmode-offload.conf').read_text().splitlines(), [
            'net.bridge.bridge-nf-call-iptables=0',
            'net.bridge.bridge-nf-call-ip6tables=0',
            'net.bridge.bridge-nf-call-arptables=0',
            'net.bridge.bridge-nf-pass-vlan-input-dev=1'])
        self.assertIn('CONFIG_PACKAGE_kmod-br-netfilter=y', (ROOT / 'user/default/config.diff').read_text())
        defaults = (files / 'etc/uci-defaults/99-w1700k-defaults').read_text()
        for option in ('flow_offloading', 'flow_offloading_hw'):
            self.assertIn(f"firewall.@defaults[0].{option}='1'", defaults)
        self.assertTrue((files / 'etc/uci-defaults/90-bridge-hw-offload').is_file())


@unittest.skipUnless(os.environ.get('DEVICE_ROOTFS'), 'set DEVICE_ROOTFS to verified release rootfs')
class NativeDefaults(unittest.TestCase):
    def test_native_sysctl_enables_vlan_and_pppoe(self):
        import shutil
        release = Path(os.environ['DEVICE_ROOTFS'])
        for initial in ('0', '1'):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(release / 'bin', root / 'bin', symlinks=True)
                (root / 'lib').mkdir()
                for lib in release.glob('lib/*.so*'):
                    shutil.copy2(lib, root / 'lib' / lib.name, follow_symlinks=True)
                bridge = root / 'proc/sys/net/bridge'
                bridge.mkdir(parents=True)
                filters = ('bridge-nf-filter-vlan-tagged', 'bridge-nf-filter-pppoe-tagged')
                calls = ('bridge-nf-call-iptables', 'bridge-nf-call-ip6tables', 'bridge-nf-call-arptables')
                for key in (*filters, *calls, 'bridge-nf-pass-vlan-input-dev'):
                    (bridge / key).write_text(initial if key in filters else '9')
                for config in sorted((ROOT / 'user/default/files/etc/sysctl.d').glob('*.conf')):
                    shutil.copy2(config, root / config.name)
                    subprocess.run(['chroot', str(root), '/bin/busybox', 'sysctl', '-p', '/' + config.name],
                                   check=True, capture_output=True, text=True)
                for key in filters:
                    self.assertEqual((bridge / key).read_text().strip(), '1')
                for key in calls:
                    self.assertEqual((bridge / key).read_text().strip(), '0')
                self.assertEqual((bridge / 'bridge-nf-pass-vlan-input-dev').read_text().strip(), '1')

    def test_fresh_and_retained_native_uci(self):
        import shutil
        release = Path(os.environ['DEVICE_ROOTFS'])
        for marker in (None, 'sysupgrade.tgz', 'tmp/sysupgrade.tar'):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in ('bin', 'lib/functions', 'lib/config'):
                    shutil.copytree(release / name, root / name, symlinks=True)
                for name in ('etc/config', 'tmp/.uci', 'dev', 'sbin'):
                    (root / name).mkdir(parents=True, exist_ok=True)
                for lib in release.glob('lib/*.so*'):
                    shutil.copy2(lib, root / 'lib' / lib.name, follow_symlinks=True)
                for name in ('sbin/uci', 'lib/functions.sh'):
                    shutil.copy2(release / name, root / name)
                (root / 'dev/null').touch()
                for name, text in {
                    'system': "config system 'main'\n option hostname 'operator'\n",
                    'network': "config interface 'lan'\n option ipaddr '192.168.99.1'\n",
                    'wireless': "config wifi-device 'radio0'\n option band '2g'\nconfig wifi-iface 'operator'\n option ssid 'private'\n",
                    'dhcp': "config dhcp 'lan'\n", 'luci': "config core 'main'\n",
                    'firewall': "config defaults\n option flow_offloading_hw '0'\n",
                }.items():
                    (root / 'etc/config' / name).write_text(text)
                if marker:
                    (root / marker).touch()
                shutil.copy2(ROOT / 'user/default/files/etc/uci-defaults/99-w1700k-defaults', root / 'defaults')
                def sh(command):
                    return subprocess.check_output(['chroot', str(root), '/bin/sh', '-c', command], text=True)
                before = sh('uci export')
                sh('/bin/sh /defaults; uci commit')
                if marker:
                    self.assertEqual(sh('uci export'), before)
                else:
                    self.assertEqual(sh('uci get network.lan.ipaddr').strip(), '192.168.8.1/24')
                    self.assertEqual(sh('uci get system.main.hostname').strip(), 'W1700K')
                    self.assertEqual(sh('uci get firewall.@defaults[0].flow_offloading_hw').strip(), '1')


if __name__ == '__main__':
    unittest.main()
