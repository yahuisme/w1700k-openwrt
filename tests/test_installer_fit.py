"""Private FIT probes; dtc/mkimage create test containers, not firmware."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent / 'installer'))


class InstallerFit(unittest.TestCase):
    def test_temporary_and_chainloader_fit_roles(self):
        import installer_payload as helper
        import libfdt
        from installer_fit_fixture import make_fit
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'image.itb'
            data = make_fit(Path(tmp), external=False)
            tree = libfdt.Fdt(data)
            tree.resize(len(data) + 1024)
            config = tree.path_offset('/configurations/config-1')
            tree.delprop(config, 'loadables')
            tree.setprop_str(config, 'ramdisk', 'rootfs-1')
            tree.setprop_str(tree.path_offset('/images/rootfs-1'), 'type', 'ramdisk')
            image.write_bytes(tree.as_bytearray())
            helper.verify_fit(image, kind='recovery')
            with self.assertRaises(ValueError):
                helper.verify_fit(image)
            tree.delprop(tree.path_offset('/configurations/config-1'), 'ramdisk')
            tree.del_node(tree.path_offset('/images/rootfs-1'))
            image.write_bytes(tree.as_bytearray())
            helper.verify_fit(image, kind='chainloader')
            helper.verify_fit(image, kind='recovery')

    def test_existing_payload_validator_is_locally_owned(self):
        self.assertTrue((ROOT / 'scripts/installer_payload.py').is_file())
        spec = importlib.util.spec_from_file_location('installer_payload', ROOT / 'scripts/installer_payload.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        from installer_fit_fixture import make_fit
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'image.itb'
            image.write_bytes(make_fit(Path(tmp)))
            helper.verify_fit(image)
            bad = bytearray(image.read_bytes()); bad[-1] ^= 1
            image.write_bytes(bad)
            with self.assertRaises(ValueError):
                helper.verify_fit(image)
