"""Keep profile intent without obsolete symbols or inert negative records."""
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'user/default/config.diff'
USTEER = ('usteer', 'luci-app-usteer', 'luci-i18n-usteer-zh-cn')


class ProfileConfigurationTests(unittest.TestCase):
    def test_nft_tproxy_is_builtin_for_both_distributions(self):
        for profile in ('default', 'immortalwrt'):
            with self.subTest(profile=profile):
                lines = (ROOT / 'user' / profile / 'config.diff').read_text().splitlines()
                self.assertEqual(lines.count('CONFIG_PACKAGE_kmod-nft-tproxy=y'), 1)

    def test_no_obsolete_or_ineffective_profile_entries(self):
        symbols = set(re.findall(r'^(?:# )?CONFIG_([^= ]+)', PROFILE.read_text(), re.M))
        # NO_SMB has no definition or recipe reader; GDB's prompt is hidden
        # without TOOLCHAINOPTS, so '=n' is discarded by official Kconfig.
        self.assertNotIn('LIBCURL_NO_SMB', symbols)
        self.assertNotIn('GDB', symbols)
        for package in USTEER:
            self.assertNotIn('PACKAGE_' + package, symbols)

    def test_keep_requested_crypto_and_wireless_features(self):
        lines = set(PROFILE.read_text().splitlines())
        for symbol in ('LIBCURL_MBEDTLS', 'OPENSSL_ENGINE', 'OPENSSL_WITH_DEPRECATED',
                       'OPENSSL_WITH_IDEA', 'OPENSSL_WITH_MDC2', 'OPENSSL_WITH_SEED',
                       'OPENSSL_WITH_WHIRLPOOL', 'PACKAGE_libopenssl-legacy',
                       'PACKAGE_apk-openssl', 'PACKAGE_wpad-openssl'):
            self.assertIn('CONFIG_' + symbol + '=y', lines)
        # OpenWrt's defaults can otherwise select apk-mbedtls=m and replace
        # full wpad-openssl=y with wpad-basic-mbedtls=y. Keep these exclusions.
        system = json.loads((ROOT / 'user/default/build.json').read_text())['system']
        if system == 'openwrt':
            for package in ('apk-mbedtls', 'wpad-basic-mbedtls'):
                self.assertIn(f'# CONFIG_PACKAGE_{package} is not set', lines)
        self.assertIn('# CONFIG_SIGN_EACH_PACKAGE is not set', lines)
        self.assertIn('CONFIG_TARGET_ROOTFS_INITRAMFS=y', lines)

    @unittest.skipUnless(os.environ.get('PROFILE_KCONFIG_SOURCE') and
                         os.environ.get('PROFILE_KCONFIG_OLD_FRAGMENT'),
                         'set official prepared source and pre-cleanup fragment')
    def test_real_kconfig_final_config_is_byte_identical(self):
        source = Path(os.environ['PROFILE_KCONFIG_SOURCE'])
        old = Path(os.environ['PROFILE_KCONFIG_OLD_FRAGMENT'])
        with tempfile.TemporaryDirectory() as directory:
            results = []
            for name, fragment in (('old', old), ('new', PROFILE)):
                requested = Path(directory) / (name + '.diff')
                requested.write_text(fragment.read_text() + '\nCONFIG_CCACHE_DIR="/ghcache"\n')
                output = Path(directory) / (name + '.config')
                # Kconfig's hostcxx capability probe normally compiles a
                # test. Point it at an empty staging path: no compiler runs.
                env = dict(os.environ, KCONFIG_CONFIG=str(output),
                           STAGING_DIR_HOST=str(Path(directory) / 'no-build-host'))
                result = subprocess.run([str(source / 'scripts/config/conf'),
                                         '--defconfig=' + str(requested), 'Config.in'],
                                        cwd=source, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                results.append(output.read_bytes())
            self.assertEqual(results[0], results[1])
            text = results[1].decode()
            for package in USTEER:
                self.assertNotRegex(text, rf'(?m)^CONFIG_PACKAGE_{package}=[ym]$')
