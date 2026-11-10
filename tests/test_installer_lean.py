"""Select native recovery seeds without a second dependency resolver."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_installer as helper


class LeanInstaller(unittest.TestCase):
    def test_formal_apps_are_not_recovery_seeds(self):
        select = getattr(helper, 'lean_packages', None)
        self.assertTrue(callable(select), 'missing lean native package selection')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / 'lib/apk/db/installed'
            database.parent.mkdir(parents=True)
            names = {'busybox', 'dropbear', 'dnsmasq-full', 'fitblk', 'ubi-utils',
                     'netifd', 'uci', 'ubus', 'ubusd', 'ubox', 'fstools', 'fwtool',
                     'jsonfilter', 'logd', 'mtd', 'procd', 'procd-seccomp', 'uboot-envtools',
                     'ucode', 'ucode-mod-digest', 'ucode-mod-fs', 'urandom-seed', 'urngd',
                     'usign', 'kmod-mt7996e', 'kmod-mt7996-firmware',
                     'airoha-en7581-npu-firmware', 'rtl8261c-firmware',
                     'luci', 'luci-theme-aurora', 'ttyd', 'curl', 'rpcd', 'nano'}
            database.write_text(''.join('P:' + n + '\nV:1\n\n' for n in sorted(names)))
            selected = select(root)
            self.assertTrue({'dropbear', 'dnsmasq-full', 'kmod-mt7996e', 'rtl8261c-firmware'} <= set(selected))
            self.assertFalse({'luci', 'luci-theme-aurora', 'ttyd', 'curl', 'rpcd', 'nano'} & set(selected))
            lean = {name for name in names if name not in {'luci', 'luci-theme-aurora', 'ttyd', 'curl', 'rpcd', 'nano'}}
            database.write_text(''.join('P:' + n + '\nV:1\n\n' for n in sorted(lean)))
            helper.validate_lean(root, selected)
            database.write_text(database.read_text() + 'P:luci-theme-aurora\nV:1\n\n')
            with self.assertRaises(ValueError): helper.validate_lean(root, selected)
            database.write_text(''.join('P:' + n + '\nV:1\n\n' for n in sorted(names)))
            database.write_text(database.read_text().replace('P:ubi-utils\nV:1\n\n', ''))
            with self.assertRaises(ValueError): select(root)
