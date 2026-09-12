#!/usr/bin/env python3
"""Opt-in local upstream checks (no GitHub calls).

Run: python3 tests/check_cache_upstream.py OBJECT_REPO PREPARED_BUILDROOT
OBJECT_REPO must contain e36bf95f68 and 8bf1c9253c.
PREPARED_BUILDROOT must be a disposable configured OpenWrt tree with host gcc.
This exercises real tools/flock and real upstream dependency/stamp rules,
NOT a complete GCC toolchain build. Toolchain-test directories are layout only.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cache.py'
spec = importlib.util.spec_from_file_location('cache', SCRIPT)
assert spec and spec.loader
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


def run(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT)


def main(objects, build):
    report = {}
    def show(rev, name):
        return run(['git', '-C', str(objects), 'show', f'{rev}:{name}'])
    for rev in ('e36bf95f68', '8bf1c9253c'):
        headers = show(rev, 'toolchain/kernel-headers/Makefile')
        quilt = show(rev, 'include/quilt.mk')
        target = show(rev, 'include/target.mk')
        base = show(rev, 'package/base-files/Makefile')
        assert '$(call Kernel/Prepare/Default)' in headers
        assert 'headers_install' in headers
        assert '$(GENERIC_FILES_DIR) $(FILES_DIR)' in quilt
        assert 'include $(PLATFORM_SUBDIR)/target.mk' in target
        for var in ('GENERIC_PLATFORM_DIR', 'PLATFORM_DIR', 'PLATFORM_SUBDIR'):
            assert f'$(CP) $({var})/base-files/* $(1)/' in base
        report[rev + '_dependency_rules'] = 'verified'
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / 'source'
        keys = []
        for rev in ('e36bf95f68', '8bf1c9253c'):
            if root.exists():
                shutil.rmtree(root)
            root.mkdir()
            archive = Path(tmp) / 'source.tar'
            subprocess.run(['git', '-C', str(objects), 'archive', '--output', str(archive),
                            rev, *[n for n in cache.INPUTS if n != '.config']], check=True)
            with tarfile.open(archive) as tar:
                tar.extractall(root, filter='data')
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            # Same controlled config/path/image isolates the two tree changes.
            (root / '.config').write_text('CONFIG_TARGET_airoha=y\nCONFIG_TARGET_airoha_an7581=y\n')
            cfg = root / '.config'
            cfg.write_text(cfg.read_text() + ('CONFIG_PACKAGE_bridge-flow-offload=y\n' if rev == 'e36bf95f68' else 'CONFIG_PACKAGE_bridge-hw-offload=y\n') + 'CONFIG_VERSION_NUMBER="runtime-' + rev + '"\n')
            keys.append(cache.key(root, 'controlled-image'))
            original = cfg.read_text()
            for symbol in ('CONFIG_PACKAGE_kmod-b43', 'CONFIG_GCC_VERSION', 'CONFIG_HOST_EXTRA_CFLAGS', 'CONFIG_KERNEL_CFLAGS', 'CONFIG_SOFT_FLOAT', 'CONFIG_TARGET_INITRAMFS_COMPRESSION_LZ4'):
                cfg.write_text(original + symbol + '=y\n')
                assert cache.key(root, 'controlled-image') != keys[-1], symbol
            cfg.write_text(original)
            recipe = root / 'tools/flock/Makefile'
            saved = recipe.read_text()
            for reference in ('$(CONFIG_PACKAGE_bridge-hw-offload)', '$(CONFIG_PACKAGE_$(name))', '$(CONFIG_$(name))'):
                recipe.write_text(saved + '\nTEST=' + reference + '\n')
                one = cache.key(root, 'controlled-image')
                cfg.write_text(original + 'CONFIG_PACKAGE_bridge-hw-offload=m\n')
                assert cache.key(root, 'controlled-image') != one, reference
                cfg.write_text(original)
            recipe.write_text(saved)
            report[rev + '_config_projection'] = 'runtime package/version hit; tools/ABI/flags/direct/dynamic references miss'
        assert keys[0] == keys[1], keys
        report['two_exact_trees_same_config'] = {'keys': keys, 'hit': True}
    # Production key normalizes source inputs; never completion stamps.
    key = cache.key(build, 'local-host-test')
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / 'probe.mk'
        probe.write_text('probe-cache-stamps:\n\t@printf "%s\\n" "$(HOST_STAMP_PREPARED)" "$(HOST_STAMP_CONFIGURED)" "$(LINUX_VERSION)" "$(LINUX_KARCH)" "$(GENERIC_FILES_DIR)" "$(FILES_DIR)"\n')
        command = ['make', '-s', '-C', str(build / 'toolchain/kernel-headers'),
                   '-f', 'Makefile', '-f', str(probe), 'TOPDIR=' + str(build),
                   'probe-cache-stamps']
        initial = run(command)
        runtime = build / 'target/linux/airoha/an7581/base-files/cache-stamp-probe'
        assert not runtime.exists()
        runtime.parent.mkdir(parents=True, exist_ok=True)
        try:
            runtime.write_text('runtime payload')
            assert run(command) == initial
            assert cache.key(build, 'local-host-test') == key
        finally:
            runtime.unlink()
        report['real_kernel_headers_make_stamps_runtime_stable'] = initial.splitlines()
    run(['make', 'tools/flock/compile', 'V=s'], build)
    stamp = build / 'build_dir/host/flock-2.18/.built'
    before = stamp.stat().st_mtime_ns
    overlay = build / 'target/linux/airoha/an7581/base-files/etc/cache-key-test'
    assert not overlay.exists()
    overlay.parent.mkdir(parents=True, exist_ok=True)
    try:
        overlay.write_text('runtime-only test\n')
        assert cache.key(build, 'local-host-test') == key
        out = run(['make', 'tools/flock/compile', 'V=s'], build)
        assert stamp.stat().st_mtime_ns == before
        assert 'flock src/flock.c' not in out
        report['real_flock_runtime_change'] = 'warm; built stamp unchanged; no compiler'
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('build_dir/toolchain-cache-test', 'staging_dir/toolchain-cache-test'):
                (build / name).mkdir(exist_ok=True)
            cache.pack(build, Path(tmp), 'toolchain', key)
            cache.restore(build, Path(tmp), key)
            out = run(['make', 'tools/flock/compile', 'V=s'], build)
            assert stamp.stat().st_mtime_ns == before
            assert 'flock src/flock.c' not in out
            report['real_flock_pax_roundtrip'] = 'warm; nanosecond stamp unchanged; no compiler'
        src = build / 'tools/flock/src/flock.c'
        original = src.read_bytes()
        try:
            src.write_bytes(original + b'\n/* cache-key compile-input regression */\n')
            assert cache.key(build, 'local-host-test') != key
            # Exact-key miss means the old artifact is not eligible for restore.
            cache.restore(build, Path(tmp) / 'absent', 'different-key')
            out = run(['make', 'tools/flock/compile', 'V=s'], build)
            assert 'flock src/flock.c' in out
            report['real_flock_changed_source'] = 'key miss; cold path really recompiles'
        finally:
            src.write_bytes(original)
    finally:
        overlay.unlink(missing_ok=True)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
