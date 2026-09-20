"""Native ucode regression; set TXPOWER_SOURCE to an unpatched official tree.
No radio/ubus/host filesystem IO: execute real functions with boundary doubles.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAC = 'package/network/config/wifi-scripts/files-ucode/lib/netifd/wireless/mac80211.sh'
GEN = 'package/network/config/wifi-scripts/files-ucode/usr/share/ucode/wifi/hostapd.uc'
HOST = 'package/network/services/hostapd/files/hostapd.uc'
PATCH = ROOT / 'user/default/patches/920-wifi-non-mlo-ap-txpower.patch'


def function(source, name):
    start = source.index('function ' + name + '(')
    end = source.index('\n}', start) + 2
    return source[start:end]


@unittest.skipUnless(os.environ.get('TXPOWER_SOURCE') and shutil.which('ucode'),
                     'set TXPOWER_SOURCE and install native ucode for lifecycle tests')
class TxpowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.tree = Path(cls.tmp.name)
        for name in (MAC, GEN, HOST):
            dest = cls.tree / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(os.environ['TXPOWER_SOURCE']) / name, dest)
        if not os.environ.get('TXPOWER_BASELINE'):
            custom = (ROOT / 'user/default/custom.sh').read_text()
            line = next(line for line in custom.splitlines() if 'patch -p1 --fuzz=0' in line and PATCH.name in line)
            subprocess.run(['bash', '-ec', line], cwd=cls.tree,
                           env=dict(os.environ, DK_PROFILE=str(ROOT/'user/default')),
                           check=True, capture_output=True)
        cls.mac, cls.gen, cls.host = [(cls.tree / n).read_text() for n in (MAC, GEN, HOST)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_ucode(self, code):
        path = self.tree / 'test.uc'
        path.write_text(code)
        proc = subprocess.run(['ucode', str(path)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def setup_case(self, power=23, radio=0, interfaces=None):
        interfaces = interfaces if interfaces is not None else {'a': {'config': {'mode': 'ap'}, 'stas': {}}}
        data = {'config': {'radio': radio, 'band': '2g', 'channel': 6, 'txpower': power},
                'data': {'txantenna': 4294967295, 'rxantenna': 4294967295}, 'interfaces': interfaces}
        body = '\n'.join(line for line in self.mac.splitlines()[1:] if not line.startswith('import '))
        body = body[:body.index('let ret = 1;')]
        return self.run_ucode('''let commands=[]; let passed;
global.system=(cmd)=>{push(commands,cmd);return 0;};
function log(s) {} function validate(t,c) {} function find_phy(c,x){return 'phy0';}
function set_default(o,k,v){o[k]??=v;}
let netifd={set_data:()=>{},set_vif:()=>{},set_up:()=>{},set_retry:()=>{}};
let fs={access:(p,m)=>p=='/usr/sbin/hostapd'};
let iface={prepare:()=>{}}; let supplicant={};
let hostapd={setup:(data)=>{passed=data.config;}};
let nl80211={}; global.ubus={call:()=>{}};
''' + body + '\nARGV[3]=' + json.dumps(json.dumps(data)) + ''';
setup(); printf('%J',{commands,config:passed});''')

    def test_non_mlo_ap_does_not_write_shared_phy(self):
        result = self.setup_case()
        self.assertFalse(any(' set txpower ' in c for c in result['commands']), result)
        self.assertTrue(result['config']['per_interface_txpower'])

    def test_zero_and_auto(self):
        self.assertEqual(self.setup_case(0)['config']['txpower'], 'fixed 000')
        self.assertEqual(self.setup_case(None)['config']['txpower'], 'auto')

    def test_mlo_and_non_ap_keep_upstream_path(self):
        for cfg in ({'mode': 'ap', 'mlo': True}, {'mode': 'monitor'}):
            result = self.setup_case(interfaces={'a': {'config': cfg, 'stas': {}}})
            self.assertIn('iw phy phy0 set txpower fixed 2300', result['commands'])
        self.assertIn('iw phy phy0 set txpower fixed 2300', self.setup_case(radio=-1)['commands'])

    def test_empty_does_not_write_shared_phy(self):
        result = self.setup_case(interfaces={})
        self.assertFalse(any(' set txpower ' in c for c in result['commands']))

    def host_code(self):
        # Execute actual exported callback object, without module initialization.
        start = self.host.index('\nreturn {\n\tshutdown:')
        callbacks = self.host[start:].replace('\nreturn {', '\nlet callbacks = {', 1)
        helper = function(self.host, 'bss_txpower') if 'function bss_txpower(' in self.host else ''
        return '''let commands=[];let logs=[];let events=[];let fail=false;
global.system=(cmd)=>{push(commands,cmd);return fail?1:0;};
let hostapd={data:{config:{},dpp_hooks:{},
 obj:{notify:(type,data)=>push(events,{type,data})},
 ubus:{call:(object,method,data)=>push(events,{object,method,data})}},printf:(s)=>push(logs,s)};
function wdev_set_radio_mask(n,m){}
''' + function(self.host, 'bss_event') + helper + callbacks

    def test_async_callbacks_reload_cancel_failure_mlo(self):
        result = self.run_ucode(self.host_code() + '''
let cfg={radio_idx:0,txpower:'fixed 2300',bss:[{ifname:'ap0'},{ifname:'owe0'},{ifname:'mld0',mld_ap:1}]};
hostapd.data.config['phy0.0']=cfg;
// No callback during deferred supplicant/ACS/CAC: no premature iw.
let before=length(commands);
callbacks.bss_create('phy0.0','ap0',{});
callbacks.bss_add('phy0.0','ap0',{});
callbacks.bss_create('phy0.0','owe0',{});
callbacks.bss_add('phy0.0','owe0',{});
callbacks.bss_add('phy0.0','mld0',{});
// A new config replaces the old one; no captured timeout can replay 23.
cfg.txpower='fixed 2500';
callbacks.bss_create('phy0.0','ap0',{});
callbacks.bss_add('phy0.0','ap0',{});
// Reused names not in the current BSS list are ignored.
callbacks.bss_add('phy0.0','removed0',{});
fail=true; callbacks.bss_add('phy0.0','owe0',{});
delete hostapd.data.config['phy0.0'];
callbacks.bss_add('phy0.0','ap0',{});
printf('%J',{before,commands,logs});
''')
        self.assertEqual(result['before'], 0)
        self.assertEqual(result['commands'], [
            ['iw', 'dev', name, 'set', 'txpower', 'fixed', power]
            for name, power in [('ap0','2300'),('owe0','2300'),('ap0','2500'),('owe0','2500')]])
        self.assertTrue(any('Failed to set txpower' in log for log in result['logs']))

    def test_real_pending_state_machine_aborts_old_setup(self):
        names = ('__iface_pending_next', 'iface_pending_next', 'iface_pending_abort',
                 'iface_pending_ubus_call', 'iface_pending_init')
        code = self.host_code() + '''
let deferred=[]; let created=[];
hostapd.data.pending_config={};
hostapd.data.ubus.defer=(obj,method,arg,cb)=>{
 let d={aborted:false,callback:cb}; d.abort=()=>{d.aborted=true;};
 push(deferred,d); return d;
};
function iface_update_supplicant_macaddr(p){}
function iface_add(phy,config,status){
 for(let b in config.bss){callbacks.bss_create(phy,b.ifname,{}); callbacks.bss_add(phy,b.ifname,{});}
 return true;
}
''' + '\n'.join(function(self.host, n) for n in names[:-1]) + '''
const iface_pending_proto={next:iface_pending_next,call:iface_pending_ubus_call,abort:iface_pending_abort};
''' + function(self.host, 'iface_pending_init') + '''
let phydev={name:'phy0.0',phy:'phy0',radio:0,wdev_add:(n,c)=>{push(created,n);return null;}};
let old={txpower:'fixed 2300',bss:[{ifname:'ap0'}]};
hostapd.data.config['phy0.0']=old;
iface_pending_init(phydev,old);
let pending=hostapd.data.pending_config['phy0.0'];
let before=length(commands);
pending.abort();
let aborted=deferred[0].aborted;
let removed=hostapd.data.pending_config['phy0.0']==null;
let fresh={txpower:'fixed 2500',bss:[{ifname:'ap0'},{ifname:'ap1'}]};
hostapd.data.config['phy0.0']=fresh;
iface_pending_init(phydev,fresh);
// Complete the fresh supplicant status request. The aborted request is not delivered.
deferred[1].callback(0,{state:'COMPLETED'});
printf('%J',{before,aborted,removed,commands});
'''
        result = self.run_ucode(code)
        self.assertEqual(result['before'], 0)
        self.assertTrue(result['aborted'])
        self.assertTrue(result['removed'])
        self.assertEqual(len(result['commands']), 2)
        self.assertTrue(all(cmd[-1] == '2500' for cmd in result['commands']))

    def test_real_uloop_delayed_bss_events(self):
        runtime = os.environ.get('TXPOWER_RUNTIME_ROOT')
        if not runtime:
            self.skipTest('set TXPOWER_RUNTIME_ROOT to extracted rootfs with native uloop')
        root = Path(runtime)
        code = "import * as uloop from 'uloop';\n" + self.host_code() + '''
// Event delivery uses actual timers; driver and hostapd C boundaries remain mocked.
let first={txpower:'fixed 2300',bss:[{ifname:'ap0'}]};
hostapd.data.config['phy0.0']=first;
let before=length(commands);
let timers=[];
push(timers,uloop.timer(10,()=>{
 callbacks.bss_create('phy0.0','ap0',{});
 callbacks.bss_add('phy0.0','ap0',{});
}));
push(timers,uloop.timer(20,()=>{
 // Power-only reload restarts via the tested reload classifier.
 hostapd.data.config['phy0.0']={txpower:'auto',bss:[{ifname:'ap0'},{ifname:'owe0'}]};
}));
push(timers,uloop.timer(40,()=>{
 callbacks.bss_create('phy0.0','owe0',{});
 callbacks.bss_add('phy0.0','owe0',{});
}));
push(timers,uloop.timer(50,()=>{delete hostapd.data.config['phy0.0'];}));
push(timers,uloop.timer(60,()=>{callbacks.bss_add('phy0.0','ap0',{});}));
push(timers,uloop.timer(80,()=>uloop.end()));
uloop.run();printf('%J',{before,commands});
'''
        path = self.tree / 'uloop.uc'
        path.write_text(code)
        command = [str(root/'lib/libc.so'), '--library-path', f'{root}/lib:{root}/usr/lib',
                   str(root/'usr/bin/ucode'), '-L', f'{root}/usr/lib/ucode/*.so', str(path)]
        proc = subprocess.run(command, text=True, capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['before'], 0)
        self.assertEqual([cmd[-1] for cmd in result['commands']], ['2300','auto'])

    def test_two_radios_and_reversed_indices(self):
        for indices in ((0, 1), (1, 0)):
            with self.subTest(indices=indices):
                configs = {}
                expected = []
                callbacks = []
                for index, power in zip(indices, (23, 25)):
                    setup = self.setup_case(power, index)
                    self.assertFalse(any(' set txpower ' in cmd for cmd in setup['commands']))
                    phy, name = f'phy0.{index}', f'phy0.{index}-ap0'
                    configs[phy] = {'radio_idx': index, 'txpower': setup['config']['txpower'],
                                    'bss': [{'ifname': name}]}
                    callbacks.append(f'callbacks.bss_add({json.dumps(phy)},{json.dumps(name)},{{}});')
                    expected.append(['iw', 'dev', name, 'set', 'txpower', 'fixed', str(power * 100)])
                # Both radios coexist; revisit the first after the second callback.
                result = self.run_ucode(self.host_code() + '\nhostapd.data.config=' +
                                        json.dumps(configs) + ';' + ''.join(callbacks + callbacks[:1]) +
                                        "printf('%J',commands);")
                self.assertEqual(result, expected + expected[:1])

    def test_failure_notifies_through_real_bss_event(self):
        result = self.run_ucode(self.host_code() + '''
 hostapd.data.config['phy0.1']={txpower:'fixed 2500',bss:[{ifname:'ap1'}]};
 callbacks.bss_add('phy0.1','ap1',{});
 let success_events=events;
 events=[]; fail=true;
 callbacks.bss_add('phy0.1','ap1',{});
 printf('%J',{success_events,events});
''')
        added = [
            {'type': 'bss.add', 'data': {'name': 'ap1'}},
            {'object': 'service', 'method': 'event',
             'data': {'type': 'hostapd.ap1.add', 'data': {}}},
        ]
        self.assertEqual(result['success_events'], added)
        self.assertEqual(result['events'], [
            {'type': 'bss.txpower_failed', 'data': {'phy': 'phy0.1', 'status': 1, 'name': 'ap1'}},
            {'object': 'service', 'method': 'event',
             'data': {'type': 'hostapd.ap1.txpower_failed', 'data': {}}},
        ] + added)

    def test_config_power_change_bypasses_csa_and_early_reload(self):
        code = '''let restarted=0;let csa=0;let removed=0;
let hostapd={data:{config:{},pending_config:{}},printf:()=>{}};
function phy_open(p,r){return {name:'phy0.0'};}
function iface_check_mld(){} function iface_update_supplicant_macaddr(){}
function iface_restart(){restarted++;return 0;}
function iface_config_remove(){removed++;}
function is_equal(a,b){return sprintf('%J',a)==sprintf('%J',b);}
function radio_reload_class(){return 'channel';}
function iface_channel_switch(){csa++;return true;}
''' + function(self.host, 'iface_reload_config') + function(self.host, 'iface_set_config') + '''
let old={phy:'phy0',radio_idx:0,txpower:'fixed 2300',bss:[{ifname:'ap0'}]};
hostapd.data.config['phy0.0']=old;
iface_set_config('phy0.0',{phy:'phy0',radio_idx:0,txpower:'fixed 2500',bss:[{ifname:'ap0'}]});
let power_change={restarted,csa};
iface_set_config('phy0.0',{phy:'phy0',radio_idx:0,txpower:'fixed 2500',bss:[{ifname:'ap0'}]});
printf('%J',{power_change,restarted,csa});
'''
        result = self.run_ucode(code)
        self.assertEqual(result['power_change'], {'restarted': 1, 'csa': 0})
        self.assertEqual(result['restarted'], 1)
        self.assertEqual(result['csa'], 1)

    def test_teardown_cancels_pending_setup(self):
        result = self.run_ucode('''let aborted=false;
let hostapd={data:{apsta_freq:{},pending_config:{'phy0.0':{abort:()=>{aborted=true;}}}},remove_iface:()=>{}};
function iface_remove(c){}
''' + function(self.host, 'iface_config_remove') + '''
iface_config_remove('phy0.0',{}); printf('%J',aborted);
''')
        self.assertTrue(result)

    def test_power_change_forces_existing_restart_path(self):
        result = self.run_ucode('''let hostapd={data:{pending_config:{}}};
function radio_reload_class(a,b){return 'same';} function is_equal(a,b){return true;}
''' + function(self.host, 'iface_reload_config') + '''
let old={txpower:'fixed 2300',bss:[]};
let changed={txpower:'fixed 2500',bss:[]};
printf('%J',iface_reload_config('phy0.0',{name:'phy0'},changed,old));
''')
        self.assertFalse(result)

    def test_generator_and_parser_carry_power(self):
        for label, power, scoped, expected in (
                ('fixed', 23, True, 'fixed 2300'),
                ('zero', 0, True, 'fixed 000'),
                ('auto', None, True, 'auto'),
                ('absent', 23, False, None)):
            with self.subTest(case=label):
                config = self.setup_case(power)['config']
                config['per_interface_txpower'] = scoped
                data = {'phy': 'phy0', 'vif_phy_suffix': '.0', 'config': config,
                        'interfaces': {'a': {'config': {'mode': 'ap'}}}}
                # Only unrelated config generation and IO are doubles. Feed the
                # actual setup-produced metadata straight to the actual parser.
                code = r'''let lines=[]; let input; let payload;
function append(k,v){push(lines,k+'='+v);}
let fs={stat:()=>false}; function flush_config(){} function generate(c){append('driver','nl80211');}
function dump_config(n){input=split(join('\n',lines),'\n');return join('\n',lines);}
function setup_interface(){append('interface','ap0');append('bssid','00:11:22:33:44:55');}
let phy_features={};
let netifd={add_process:()=>{},setup_failed:()=>{}};
global.ubus={list:()=>true,call:(a,b,c)=>{payload=c;return {pid:1};}};
function open(p,m){return {read:()=>shift(input),close:()=>{}};}
let hostapd={data:{file_fields:{}}};
''' + function(self.gen, 'setup') + function(self.host, 'config_add_bss') + function(self.host, 'iface_load_config')
                code += '\nsetup(' + json.dumps(data) + ''');
printf('%J',{lines,parsed:iface_load_config(payload.phy,payload.radio,payload.config)});
'''
                result = self.run_ucode(code)
                metadata = [line for line in result['lines'] if line.startswith('\n#txpower=')]
                self.assertEqual(metadata, [] if expected is None else ['\n#txpower=' + expected])
                parsed = result['parsed']
                self.assertEqual(parsed.get('txpower'), expected)
                if expected is None:
                    self.assertNotIn('txpower', parsed)
                self.assertEqual(parsed['radio']['data'], ['driver=nl80211'])
                self.assertEqual(parsed['bss'][0]['ifname'], 'ap0')
