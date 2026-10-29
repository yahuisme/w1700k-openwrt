"""Per-step failure and cancellation replay of the actual publication tail."""
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_cache_workflow import STEPS, step, render, render_env
import test_release_safety as release
from test_cache_workflow import ROOT
from test_cache_helper import GH, entry
from record_fixture import prepare, READBACK

class PublishOrderTests(unittest.TestCase):
    fixture = release.ReleaseTests.fixture
    def run_block(self, base, name, **extra):
        env = dict(os.environ, DK_OPENWRT=str(base), RUNNER_TEMP=str(base),
                   GITHUB_SHA='a' * 40, GITHUB_REPOSITORY='fixture/repo',
                   LOG=str(base / 'calls'), PATH=str(base / 'bin') + ':' + os.environ['PATH'])
        env.update(extra)
        block = render(step(name)['run'], {})
        return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c',
                               'sudo() { :; }; docker_exec() { shift; "$@"; };\n' + block],
                              cwd=base, env=env, capture_output=True, text=True)

    def test_publication_after_cache_tail_and_failure_isolation(self):
        stage = step('Validate and stage firmware')
        publish = step('Publish firmware and prune releases')
        cache_tail = STEPS[STEPS.index(step('Prepare build caches')):
                           STEPS.index(step('Prune old download caches')) + 1]
        self.assertEqual(stage.get('id'), 'stage')
        self.assertEqual(publish.get('if'), "${{ !cancelled() && steps.stage.outcome == 'success' }}")
        self.assertLess(STEPS.index(stage), STEPS.index(cache_tail[0]))
        self.assertLess(STEPS.index(cache_tail[-1]), STEPS.index(publish))
        self.assertEqual(publish['env'], {'GH_TOKEN': '${{ secrets.RELEASE_TOKEN }}'})
        cases = ['', 'Download sources', 'Compile firmware', stage['name'], publish['name'], 'cancel_before_compile',
                 'cancel_after_stage', 'Collect build record', 'Upload build record'] + [s['name'] for s in cache_tail]
        for fault in cases:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                target, data = self.fixture(base)
                (target / 'profiles.json').write_text(json.dumps(data))
                if fault == stage['name']:
                    (base / '.config').write_text('invalid target\n')
                (base / 'bin').mkdir()
                gh = base / 'bin/gh'
                gh.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$LOG"
case "$1 $2" in
  'api --paginate') printf '[[]]\\n' ;;
  'api '*) printf '%s\\n' "$GITHUB_SHA" ;;
  'release create') [ "$FAULT" != 'Publish firmware and prune releases' ] ;;
  *) exit 99 ;;
esac
''')
                gh.chmod(0o755)
                cc = base / 'staging_dir/host/bin/ccache'
                cc.parent.mkdir(parents=True)
                cc.write_text('#!/bin/bash\nexit 0\n')
                cc.chmod(0o755)
                # Execute actual YAML shell blocks, mocking only external build,
                # cache, sudo and GitHub commands. Never invoke a host compiler.
                stubs = '''
sudo() { if [ "$1" = python3 ]; then "$@"; fi; }
nproc() { printf '1\\n'; }
make() { if [ "$1" = download ]; then [ "$FAULT" != 'Download sources' ]; else [ "$FAULT" != 'Compile firmware' ]; fi; }
git() { [ "$*" = 'config --global tar.umask 0022' ]; }
python3() {
  [ "$STEP_NAME" != "$FAULT" ] || return 23
  if [ "$2" = admit ]; then printf 'save=true\\n' >> "$GITHUB_OUTPUT"; else printf 'save=true\\n'; fi
}
docker_exec() {
  shift
  [ "$STEP_NAME" != 'Prepare build caches' ] || [ "$FAULT" != "$STEP_NAME" ] || return 23
  "$@"
}
export -f sudo nproc make python3 docker_exec git
'''
                env = dict(os.environ, DK_OPENWRT=tmp, RUNNER_TEMP=tmp,
                           GITHUB_OUTPUT=str(base / 'output'), GITHUB_SHA='a' * 40,
                           GITHUB_REPOSITORY='fixture/repo', LOG=str(base / 'calls'),
                           IMAGE_ID='sha256:'+'a'*64, BUILDER_FINGERPRINT='b'*64,
                           BOOTSTRAP_KEY='tb-v1-ubi2-new',
                           PATH=str(base / 'bin') + ':' + os.environ['PATH'], FAULT=fault)
                values = {'secrets.RELEASE_TOKEN': 'fixture-token',
                          'steps.tc.outputs.cache-hit': 'false',
                          'steps.tb.outputs.cache-hit': 'false',
                          'steps.tb_inputs.outputs.key': 'tb-v1-ubi2-new'}
                successful = True
                cancelled = fault == 'cancel_before_compile'
                executed, saved, outcomes = [], [], {}
                for current in STEPS[STEPS.index(step('Download sources')):]:
                    # Evaluate the real if expression, including GitHub's implicit
                    # success() when no status function appears. No copied gate.
                    expr = current.get('if', 'True').removeprefix('${{').removesuffix('}}').strip()
                    has_status = re.search(r'\b(success|failure|cancelled|always)\(', expr)
                    for name, value in {'success()': successful and not cancelled,
                                        'failure()': not successful, 'cancelled()': cancelled,
                                        'always()': True}.items():
                        expr = expr.replace(name, repr(value))
                    expr = re.sub(r"hashFiles\('[^']+'\)", "'fixture-archive'", expr)
                    expr = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), expr)
                    expr = re.sub(r'!(?!=)', 'not ', expr).replace('&&', ' and ').replace('||', ' or ')
                    # Trusted local YAML and repr-quoted fixture values only;
                    # no event/network input or builtins reach this evaluator.
                    eligible = (bool(has_status) or (successful and not cancelled)) and eval(
                        expr, {'__builtins__': {}})
                    name = current['name']
                    outcome = 'skipped'
                    if eligible:
                        executed.append(name)
                        if 'run' in current:
                            result = subprocess.run(['bash', '-eo', 'pipefail', '-c',
                                                     stubs + render(current['run'], values)],
                                                    cwd=base, env=dict(env, STEP_NAME=name, **render_env(current, values)),
                                                    text=True, capture_output=True)
                            outcome = 'success' if result.returncode == 0 else 'failure'
                            if current.get('id') and (base / 'output').exists():
                                for line in (base / 'output').read_text().splitlines():
                                    key, value = line.split('=', 1)
                                    values[f"steps.{current['id']}.outputs.{key}"] = value
                                (base / 'output').unlink()
                        else:
                            self.assertIn(current['uses'], ('actions/cache/save@v6', 'actions/upload-artifact@v7'))
                            outcome = 'failure' if name == fault else 'success'
                            if outcome == 'success' and current['uses'] == 'actions/cache/save@v6':
                                saved.append(current['with']['path'])
                        conclusion = 'success' if outcome == 'failure' and current.get('continue-on-error') else outcome
                        successful = successful and conclusion == 'success'
                    outcomes[name] = outcome
                    if current.get('id'):
                        values[f"steps.{current['id']}.outcome"] = outcome
                        values[f"steps.{current['id']}.conclusion"] = (
                            'success' if outcome == 'failure' and current.get('continue-on-error') else outcome)
                    if name == stage['name'] and fault == 'cancel_after_stage':
                        cancelled = True
                should_publish = fault not in ('Download sources', 'Compile firmware', stage['name'],
                                               'cancel_before_compile', 'cancel_after_stage')
                self.assertEqual(publish['name'] in executed, should_publish, (fault, outcomes))
                calls = (base / 'calls').read_text() if (base / 'calls').exists() else ''
                self.assertEqual('release create' in calls, should_publish)
                if fault in ('', publish['name'], 'Collect build record', 'Upload build record'):
                    self.assertEqual(saved, ['ccarchive', 'tcarchive', 'tbarchive', 'dlarchive'])
                if fault in [s['name'] for s in cache_tail]:
                    self.assertEqual(outcomes[fault], 'failure')
                    self.assertEqual(outcomes[publish['name']], 'success')
                    after = cache_tail.index(step(fault)) + 1
                    self.assertTrue(all(outcomes[s['name']] == 'skipped' for s in cache_tail[after:]))
                self.assertEqual(successful, fault in ('', 'Collect build record', 'Upload build record') or fault.startswith('cancel_'))


class CachePublicationIntegrationTests(unittest.TestCase):
    def test_stage_status_gate_after_complete_cache_tail(self):
        publish = step('Publish firmware and prune releases')
        self.assertEqual(step('Validate and stage firmware').get('id'), 'stage')
        self.assertEqual(publish.get('if'), "${{ !cancelled() && steps.stage.outcome == 'success' }}")
        self.assertEqual(publish['env'], {'GH_TOKEN': '${{ secrets.RELEASE_TOKEN }}'})
        self.assertEqual(STEPS[-1], publish)
        self.assertLess(STEPS.index(step('Prune old download caches')), STEPS.index(publish))
        for item in STEPS[STEPS.index(step('Prepare build caches')):STEPS.index(step('Prune old download caches')) + 1]:
            self.assertNotRegex(item.get('if', ''), r'\b(always|failure|cancelled)\(')
            self.assertFalse(item.get('continue-on-error', False))

    def replay(self, fault, tc_hit='false', tb_hit='true'):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            release.ReleaseTests().fixture(base)
            prepare(base)
            if fault == 'metadata-feed':
                (base / 'feeds.conf').write_text(
                    'src-git packages https://example.invalid/packages\n'
                    'src-git-full luci https://example.invalid/luci\n')
            if fault == 'metadata':
                (base / '.custom-revisions.tsv').unlink()
            if fault == 'metadata-external':
                (base / '.external-packages/provenance.json').unlink()
            if fault == 'metadata-external-invalid':
                (base / '.external-packages/provenance.json').write_text('{')
            if fault == 'validation':
                (base / '.config').write_text('CONFIG_TARGET_wrong=y\n')
            cc = base / 'staging_dir/host/bin/ccache'
            cc.parent.mkdir(parents=True)
            cc.write_text('#!/bin/sh\nexit 0\n')
            cc.chmod(0o755)
            for directory in ('ccarchive', 'tcarchive', 'dlarchive', 'dlcache'):
                (base / directory).mkdir()
            state = base / 'state.json'
            old = [entry(1, 'cc-v3-ubi2.old'), entry(2, 'tc-v3-ubi2-old'), entry(3, 'dl-v3.old')]
            state.write_text(json.dumps(dict(entries=old, calls=[], reads=0,
                                             fail_reads=[2] if fault == 'readback' else [])))
            gh = GH.replace("if a == ['api', '--paginate'", """if a[:2] == ['api', 'repos/fixture/repo/git/ref/heads/main']:
    p.write_text(json.dumps(s)); print(os.environ['GITHUB_SHA']); sys.exit(0)
elif a[0] == 'api' and '/releases/tags/' in a[1]:
    p.write_text(json.dumps(s))
""" + READBACK + """
    sys.exit(0)
elif a[0] == 'api' and '/git/ref/tags/' in a[1]:
    p.write_text(json.dumps(s))
    print(json.dumps(dict(object=dict(type='commit',sha=os.environ['GITHUB_SHA'])))); sys.exit(0)
elif a[:2] == ['release', 'create']:
    p.write_text(json.dumps(s)); sys.exit(19 if os.environ['FAULT']=='publish' else 0)
elif a == ['api', '--paginate', '--slurp', 'repos/fixture/repo/releases?per_page=100']:
    p.write_text(json.dumps(s))
    current = Path('firmware/version.txt').read_text().strip()
    old = current.rsplit('-r', 1)[0] + '-r1-old'
    print(json.dumps([[dict(tag_name=tag, id=i, draft=False, prerelease=False, published_at=str(i))
                       for i,tag in enumerate([old,current],1)]])); sys.exit(0)
elif a[:2] == ['release', 'delete']:
    p.write_text(json.dumps(s)); sys.exit(0)
elif a == ['api', '--paginate'""")
            (base / 'gh').write_text(gh)
            (base / 'gh').chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       MOCK_STATE=str(state), GITHUB_REF='refs/heads/main',
                       GITHUB_SHA='a'*40, GITHUB_REPOSITORY='fixture/repo',
                       GITHUB_OUTPUT=str(base / 'output'), RUNNER_TEMP=tmp,
                       DK_OPENWRT=tmp, FAULT=fault, IMAGE_ID='sha256:'+'a'*64, BUILDER_FINGERPRINT='b'*64)
            # Real nested compile shell and stage; compiler, Docker and archive
            # compressor are external boundaries. No firmware build/network occurs.
            prefix = '''
make() { if [ "$1" = download ]; then [ "$FAULT" != download ]; else [ "$FAULT" != compile ]; fi; }
git() { [ "$*" = 'config --global tar.umask 0022' ]; }
docker_exec() {
    shift
    if [ "$1" = python3 ] && [ "$2" = /cache-scripts/build_record.py ]; then
        python3 scripts/build_record.py "$DK_OPENWRT" build-record
    elif [ "$1" = python3 ] && [ "$2" = /cache-scripts/cache.py ]; then
        [ "$FAULT" != package ] || return 17
        mkdir -p "${5#/}"
        truncate -s 100 "${5#/}/$3.tar.gz"
    else
        "$@"
    fi
}
sudo() { "$@"; }
export -f make docker_exec sudo git
'''
            subprocess.run(['python3', str(ROOT/'scripts/dlcache.py'), 'snapshot',
                            str(base/'dlcache'), str(base/'dlcache-before.json')], check=True,
                           capture_output=True)
            (base/'dlcache/new-download').write_bytes(b'fixture download')
            values = {'secrets.RELEASE_TOKEN': 'fixture-token',
                      'steps.tc.outputs.cache-hit': tc_hit,
                      'steps.tb.outputs.cache-hit': tb_hit,
                      'steps.tb_inputs.outputs.key': 'tb-v1-ubi2-new',
                      'steps.inputs.outputs.key': 'tc-v3-ubi2-new',
                      'steps.gh.outputs.cache-primary-key': 'cc-v3-ubi2.new',
                      'steps.dl.outputs.cache-primary-key': 'dl-v3.new',
                      'steps.dl.outputs.cache-matched-key': '',
                      'steps.stage.outcome': 'skipped'}
            successful, cancelled = True, False
            outcomes, executed, logs = {}, [], []
            self.conclusions = {}
            def condition(expr):
                expression = expr.removeprefix('${{').removesuffix('}}').strip()
                status = re.search(r'\b(success|failure|cancelled|always)\(', expression)
                if not status and (not successful or cancelled):
                    return False  # Actions implicit success(), not just expression truth.
                for token, value in [('!cancelled()', not cancelled), ('cancelled()', cancelled),
                                     ('success()', successful), ('failure()', not successful), ('always()', True)]:
                    expression = expression.replace(token, repr(value))
                expression = re.sub(r"hashFiles\('([^']+)'\)",
                                    lambda m: repr('present' if (base/m[1]).exists() else ''), expression)
                expression = re.sub(r'steps\.[\w.-]+', lambda m: repr(values.get(m[0], '')), expression)
                # Only trusted repository comparisons and repr-quoted local
                # fixture values are evaluated, never external/event input.
                return eval(expression.replace('&&', ' and '), {'__builtins__': {}})
            for item in STEPS[STEPS.index(step('Download sources')):]:
                name = item['name']
                if fault == 'cancel' and name == 'Prepare build caches':
                    cancelled = True
                if not condition(item.get('if', 'True')):
                    outcomes[name] = 'skipped'
                    continue
                executed.append(name)
                if 'run' in item:
                    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', prefix + render(item['run'], values)],
                                            cwd=base, env=dict(env, **render_env(item, values)), text=True, capture_output=True)
                    rc = result.returncode
                    logs.append(name + '\n' + result.stdout + result.stderr)
                else:
                    self.assertIn(item['uses'], ('actions/cache/save@v6', 'actions/upload-artifact@v7'))
                    rc = 23 if ((fault == 'save' and item['uses'] == 'actions/cache/save@v6') or
                                   (fault == 'upload' and item['uses'] == 'actions/upload-artifact@v7')) else 0
                    if not rc and item['uses'] == 'actions/cache/save@v6':
                        inventory = json.loads(state.read_text())
                        inventory['entries'].append(entry(100+len(executed), render(item['with']['key'], values)))
                        state.write_text(json.dumps(inventory))
                outcome = 'success' if rc == 0 else 'failure'
                outcomes[name] = outcome
                if item.get('id'):
                    values[f"steps.{item['id']}.outcome"] = outcome
                    output = base/'output'
                    if output.exists():
                        for line in output.read_text().splitlines():
                            k, v = line.split('=', 1)
                            values[f"steps.{item['id']}.outputs.{k}"] = v
                        output.unlink()
                conclusion = 'success' if outcome == 'failure' and item.get('continue-on-error') else outcome
                self.conclusions[name] = conclusion
                if item.get('id'):
                    values[f"steps.{item['id']}.conclusion"] = conclusion
                logs.append(f'{name}: outcome={outcome} conclusion={conclusion}')
                successful = successful and conclusion == 'success'
            return outcomes, executed, json.loads(state.read_text()), '\n'.join(logs)

    def test_download_failure_never_compiles_stages_or_publishes(self):
        for tc, tb in (('true', ''), ('false', 'true'), ('false', 'false')):
            with self.subTest(tc=tc, tb=tb):
                outcomes, _, inventory, log = self.replay('download', tc_hit=tc, tb_hit=tb)
                self.assertEqual(outcomes['Download sources'], 'failure', log)
                for name in ('Compile firmware', 'Validate and stage firmware',
                             'Publish firmware and prune releases'):
                    self.assertEqual(outcomes[name], 'skipped', log)
                self.assertFalse(any(call[:2] == ['release', 'create']
                                     for call in inventory['calls']), log)

    def test_full_compile_stage_cache_publish_failure_matrix(self):
        for fault in ('none', 'download', 'compile', 'validation', 'cancel', 'package', 'save', 'readback', 'publish', 'metadata', 'metadata-feed', 'metadata-external', 'metadata-external-invalid', 'upload'):
            with self.subTest(fault=fault):
                outcomes, executed, inventory, log = self.replay(fault)
                published = fault not in ('download', 'compile', 'validation', 'cancel')
                if fault == 'download':
                    self.assertEqual(outcomes['Download sources'], 'failure', log)
                    self.assertEqual(outcomes['Compile firmware'], 'skipped', log)
                    self.assertEqual(outcomes['Validate and stage firmware'], 'skipped', log)
                creates = [call for call in inventory['calls'] if call[:2] == ['release', 'create']]
                self.assertEqual(bool(creates), published, log)
                deletes = [call[2] for call in inventory['calls'] if call[:2] == ['release', 'delete']]
                current = creates[0][2] if creates else ''
                self.assertEqual(deletes, [current.rsplit('-r', 1)[0] + '-r1-old']
                                 if published and fault != 'publish' else [], log)
                self.assertEqual(outcomes['Publish firmware and prune releases'],
                                 'failure' if fault == 'publish' else 'success' if published else 'skipped', log)
                if fault in ('metadata', 'metadata-feed', 'metadata-external', 'metadata-external-invalid'):
                    self.assertEqual(outcomes['Collect build record'], 'failure', log)
                    self.assertEqual(outcomes['Upload build record'], 'success', log)
                    self.assertEqual(self.conclusions['Collect build record'], 'success', log)
                if fault == 'upload':
                    self.assertEqual(outcomes['Upload build record'], 'failure', log)
                    self.assertEqual(self.conclusions['Upload build record'], 'success', log)
                if fault in ('none', 'publish', 'metadata', 'metadata-feed', 'metadata-external', 'metadata-external-invalid', 'upload'):
                    self.assertEqual({item['key'] for item in inventory['entries']},
                                     {'cc-v3-ubi2.new', 'tc-v3-ubi2-new', 'dl-v3.new'}, log)
                    self.assertLess(executed.index('Prune old download caches'),
                                    executed.index('Publish firmware and prune releases'))
                else:
                    self.assertTrue({1, 2, 3} <= {item['id'] for item in inventory['entries']}, log)
                if fault in ('save', 'readback'):
                    self.assertEqual(outcomes['Check toolchain cache budget'], 'skipped', log)
