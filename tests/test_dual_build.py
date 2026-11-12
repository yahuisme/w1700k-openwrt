"""Single-entry dual-distribution build and isolation contracts."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import yaml
from workflow_fixture import WORKFLOW, distribution_inputs

ROOT = Path(__file__).resolve().parents[1]


class DualBuildTests(unittest.TestCase):
    def test_explicit_distributions_run_serially_without_failure_cascade(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())
        self.assertEqual(list(workflow['jobs']), ['openwrt', 'immortalwrt'])
        first, second = workflow['jobs'].values()
        self.assertNotIn('needs', first)
        self.assertNotIn('if', first)
        self.assertEqual(second['needs'], 'openwrt')
        self.assertEqual(second['if'], "${{ !cancelled() && needs.openwrt.result != 'cancelled' }}")
        for system, job in workflow['jobs'].items():
            self.assertEqual(job['uses'], './.github/workflows/build-firmware.yaml')
            self.assertEqual(job['with']['system'], system)
            self.assertNotIn('strategy', job)
        self.assertEqual(workflow['concurrency'], {'group': 'w1700k-cache', 'cancel-in-progress': False})


    def test_workflow_names_distinguish_entry_and_template(self):
        entry = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())
        worker = yaml.safe_load(WORKFLOW.read_text())
        self.assertEqual(entry['name'], 'W1700K Firmware')
        self.assertEqual(worker['name'], 'W1700K Build Template')

    def test_reusable_workflow_has_only_the_call_trigger(self):
        entry = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())
        worker = yaml.safe_load(WORKFLOW.read_text())
        triggers = worker.get('on', worker.get(True))
        self.assertEqual(set(triggers), {'workflow_call'})
        call = triggers['workflow_call']
        self.assertEqual(set(call['inputs']), {'system', 'title', 'tc', 'cc', 'dl', 'tb'})
        self.assertEqual(call['secrets'], {'RELEASE_TOKEN': {'required': True}})
        self.assertEqual(worker['permissions'], entry['permissions'])
        self.assertNotIn('concurrency', worker, 'only the entry owns the cache lock')
        self.assertEqual(list(worker['jobs']), ['build'])
        build = worker['jobs']['build']
        self.assertEqual(build['runs-on'], 'ubuntu-24.04-arm')
        self.assertNotIn('strategy', build)
        for system, job in entry['jobs'].items():
            self.assertEqual(job['name'], {'openwrt': 'OpenWrt', 'immortalwrt': 'ImmortalWrt'}[system])
            self.assertEqual(set(job['with']), set(call['inputs']))
            self.assertEqual(job['secrets'], {'RELEASE_TOKEN': '${{ secrets.RELEASE_TOKEN }}'})
            for spec in call['inputs'].values():
                self.assertEqual(spec, {'required': True, 'type': 'string'})
        self.assertEqual(build['steps'][0]['uses'], 'actions/checkout@v7')
        self.assertNotIn('ref', build['steps'][0].get('with', {}))

    def test_failure_and_cancellation_conditions(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/W1700K.yaml').read_text())
        expression = workflow['jobs']['immortalwrt']['if']
        self.assertTrue(expression.startswith('${{ ') and expression.endswith(' }}'))
        expression = expression[4:-3]
        for cancelled in (False, True):
            for result in ('success', 'failure', 'cancelled', 'skipped'):
                with self.subTest(cancelled=cancelled, result=result):
                    condition = expression.replace('!cancelled()', str(not cancelled))
                    condition = condition.replace('needs.openwrt.result', repr(result)).replace('&&', ' and ')
                    # Evaluate only the checked-in condition with fixed local values.
                    actual = eval(condition, {'__builtins__': {}})
                    self.assertEqual(actual, not cancelled and result != 'cancelled')

    def test_immortal_profile_and_installer_are_selected_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('user', 'installer', 'scripts'):
                shutil.copytree(ROOT / name, root / name)
            before = (root / 'user/default/files').readlink() if (root / 'user/default/files').is_symlink() else None
            result = subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', 'immortalwrt'],
                                    cwd=root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            profile = json.loads((root / 'user/default/build.json').read_text())
            self.assertEqual(profile['system'], 'immortalwrt')
            self.assertTrue(all(name.startswith('immortalwrt-') for name in profile['images']))
            self.assertEqual((root / 'user/default/config.diff').read_bytes(),
                             (root / 'user/immortalwrt/config.diff').read_bytes())
            script = (root / 'installer/files/installer/install.sh').read_text()
            self.assertIn('/immortalwrt-airoha-an7581-', script)
            self.assertNotIn('/openwrt-airoha-an7581-', script)
            self.assertIn('REPO_BRANCH="master"', (root / 'user/default/settings.ini').read_text())
            self.assertTrue((root / 'user/default/files/etc/uci-defaults/99-w1700k-defaults').is_file())
            self.assertIsNone(before)


    def test_selected_cache_namespaces_match_inputs_and_protect_peer(self):
        rows = distribution_inputs()
        namespaces = []
        for row in rows:
            with self.subTest(system=row['system']), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ('user', 'installer', 'scripts'):
                    shutil.copytree(ROOT / name, root / name)
                subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', row['system']],
                               cwd=root, check=True)
                profile = json.loads((root / 'user/default/build.json').read_text())
                for tier in ('tc', 'cc', 'dl'):
                    self.assertEqual(profile['cache_prefix'][tier], row[tier])
                    namespaces.append(row[tier])
                program = "import scripts.cache_helper as h; import json; print(json.dumps(list(h.SLOTS)))"
                got = subprocess.check_output(['/usr/bin/python3', '-c', program], cwd=root, text=True)
                self.assertEqual(set(json.loads(got)), {row[tier] for tier in ('tc', 'cc', 'dl', 'tb')})
        self.assertEqual(len(namespaces), len(set(namespaces)))
        self.assertFalse(any(a.startswith(b) for a in namespaces for b in namespaces if a != b))


    def test_selection_preserves_migrated_runtime_payloads(self):
        # Frozen from the final standalone ImmortalWrt recipe, not a live sibling checkout.
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('user', 'installer', 'scripts'):
                shutil.copytree(ROOT / name, root / name)
            subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', 'immortalwrt'],
                           cwd=root, check=True)
            script = (root / 'user/default/custom.sh').read_text()
            script = script.replace('# Shared 610 replaces the upstream CN/US customization.',
                                    '# Shared 610 covers the CN/US customization previously provided by 600.')
            # Normalize only explicitly reviewed post-migration additions.
            for payload in (
                'tree/package/kernel/mt76/patches/914-mt76-mt7996-free-rro-drop-buffers.patch',
                'tree/package/network/utils/iwinfo/patches/998-fix-multi-radio-scan.patch',
                'tree/package/network/services/hostapd/patches/mtk-0015-hostapd-mtk-6G-band-does-not-require-DFS.patch',
                'tree/package/system/procd/patches/001-watchdog-clamp-default-to-device-limit.patch',
            ):
                # The last preflight member owns the shell loop delimiter.
                last = '    ' + payload + '; do\n'
                continued = '    ' + payload + ' \\\n'
                self.assertEqual(script.count(last) + script.count(continued), 1, payload)
                if last in script:
                    script = script.replace(' \\\n' + last, '; do\n', 1)
                else:
                    script = script.replace(continued, '', 1)
            watchdog = '''# Expose the native watchdog timeout limit to procd.
KERNEL_CONFIG=target/linux/airoha/an7581/config-6.18
[ -f "$KERNEL_CONFIG" ] || { echo "ERROR: Airoha kernel config not found" >&2; exit 1; }
sed -i '/^CONFIG_WATCHDOG_SYSFS=/d; /^# CONFIG_WATCHDOG_SYSFS is not set$/d' "$KERNEL_CONFIG"
printf 'CONFIG_WATCHDOG_SYSFS=y\\n' >> "$KERNEL_CONFIG"
# End watchdog timeout limit

'''
            self.assertEqual(script.count(watchdog), 1)
            script = script.replace(watchdog, '', 1)
            self.assertEqual(hashlib.sha256(script.encode()).hexdigest(), '91a1f09c268b6e0dfbb29c7cb8528a73dfdd9acc985ef82fce3f9776e1207247')
            installer = (root / 'installer/files/installer/install.sh').read_text()
            installer = installer.replace('  # No pipeline: preserve the digest tool failure even if it prints output.\n', '')
            self.assertEqual(hashlib.sha256(installer.encode()).hexdigest(), '053bd7f7079aae75bd35ea6e339724ccc10ba42645775a18eaf26142c9d280ff')

    def test_selection_is_idempotent_and_rejects_invalid_or_reverse_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('user', 'installer', 'scripts'):
                shutil.copytree(ROOT / name, root / name)
            command = ['/usr/bin/python3', 'scripts/select_distribution.py']
            def snapshot():
                return {str(path.relative_to(root)): path.read_bytes() for folder in ('user', 'installer')
                        for path in (root / folder).rglob('*') if path.is_file()}
            before = snapshot()
            result = subprocess.run(command + ['invalid'], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(snapshot(), before)
            subprocess.run(command + ['openwrt'], cwd=root, check=True)
            self.assertEqual(snapshot(), before)
            subprocess.run(command + ['immortalwrt'], cwd=root, check=True)
            selected = snapshot()
            subprocess.run(command + ['immortalwrt'], cwd=root, check=True)
            self.assertEqual(snapshot(), selected)
            result = subprocess.run(command + ['openwrt'], cwd=root, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(snapshot(), selected)


    def test_workflow_selects_profile_before_any_consumer(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        steps = workflow['jobs']['build']['steps']
        names = [step['name'] for step in steps]
        self.assertLess(names.index('Select distribution'), names.index('Restore compiler cache'))
        upload = next(step for step in steps if step.get('id') == 'record_upload')
        self.assertIn('inputs.system', upload['with']['name'])
        self.assertEqual(upload['with']['retention-days'], 30)
        for step in steps:
            if step.get('id') in ('formal', 'stage'):
                self.assertIn('openwrt_bin/targets "$SYSTEM"', step['run'])
        self.assertEqual(workflow['jobs']['build']['env']['DK_PROFILE'], '/bld/user/default')

    def test_missing_overlay_input_fails_before_profile_mutation(self):
        for missing in ('build.json', 'config.diff', 'settings.ini'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ('user', 'installer', 'scripts'):
                    shutil.copytree(ROOT / name, root / name)
                (root / 'user/immortalwrt' / missing).unlink()
                paths = [root / 'user/default' / name for name in ('build.json', 'config.diff', 'custom.sh', 'settings.ini')]
                paths.append(root / 'installer/files/installer/install.sh')
                before = {path: path.read_bytes() for path in paths}
                result = subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', 'immortalwrt'],
                                        cwd=root, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual({path: path.read_bytes() for path in paths}, before)


    def test_cache_cleanup_and_capacity_protect_the_other_distribution(self):
        from test_cache_helper import GH, entry
        for system, peer in (('openwrt', 'immortalwrt'), ('immortalwrt', 'openwrt')):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in ('user', 'installer', 'scripts'):
                    shutil.copytree(ROOT / name, root / name)
                subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', system], cwd=root, check=True)
                rows = distribution_inputs()
                own = next(row for row in rows if row['system'] == system)
                other = next(row for row in rows if row['system'] == peer)
                entries = [entry(1, own['cc'] + 'old', 300_000_000),
                           entry(2, own['cc'] + 'new', 320_000_000)]
                # Both sets of retained tiers share one real repository budget.
                entries += [entry(i + 10, other[tier] + 'peer', size) for i, (tier, size) in
                            enumerate((('tc', 1_570_000_000), ('cc', 330_000_000),
                                       ('dl', 1_350_000_000), ('tb', 220_000_000)))]
                state = root / 'state.json'
                state.write_text(json.dumps(dict(entries=entries, calls=[], reads=0)))
                gh = root / 'gh'
                gh.write_text(GH)
                gh.chmod(0o755)
                env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                           MOCK_STATE=str(state), GITHUB_REF='refs/heads/main', GITHUB_OUTPUT=str(root / 'output'))
                result = subprocess.run(['/usr/bin/python3', 'scripts/cache_helper.py', 'cleanup', own['cc'], own['cc'] + 'new'],
                                        cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                after = json.loads(state.read_text())
                self.assertEqual({row['id'] for row in after['entries']}, {2, 10, 11, 12, 13})
                # A full budget must deny new data, not evict the peer's tiers.
                after['entries'].append(entry(99, 'unowned', 10_000_000_000))
                state.write_text(json.dumps(after))
                archive = root / 'candidate.tar.gz'
                archive.write_bytes(b'candidate')
                result = subprocess.run(['/usr/bin/python3', 'scripts/cache_helper.py', 'admit', own['dl'],
                                         str(archive), own['dl'] + 'new', '--replace-download'],
                                        cwd=root, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / 'output').read_text(), 'save=false\n')
                self.assertEqual(json.loads(state.read_text())['entries'], after['entries'])


    def test_fixture_uses_selected_profile_without_extra_test_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('user', 'installer', 'scripts', 'tests', '.github'):
                shutil.copytree(ROOT / name, root / name)
            subprocess.run(['/usr/bin/python3', 'scripts/select_distribution.py', 'immortalwrt'], cwd=root, check=True)
            env = dict(os.environ, PYTHONPATH='tests', SYSTEM='immortalwrt', DISTRO_TITLE='ImmortalWrt')
            env.pop('TEST_SYSTEM', None)
            result = subprocess.check_output(['/usr/bin/python3', '-c',
                "import test_cache_workflow as fixture; print(fixture.MATRIX['system'])"],
                cwd=root, env=env, text=True)
            self.assertEqual(result.strip(), 'immortalwrt')


if __name__ == '__main__':
    unittest.main()
