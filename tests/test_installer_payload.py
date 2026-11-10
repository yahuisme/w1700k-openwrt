"""Imported payload integrity regressions; no Release downloader dependency."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import zlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import libfdt
from installer_fit_fixture import make_fit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import installer_payload as payload
from installer_payload import verify_fit

class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
            with tempfile.TemporaryDirectory() as directory:
                cls.fit = make_fit(Path(directory))
                cls.inline = make_fit(Path(directory), external=False)

    def check_fit(self, data):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'image.itb'
                path.write_bytes(data)
                verify_fit(path)

    def test_all_component_bytes_are_hashed(self):
            tree = libfdt.Fdt(self.fit)
            for name in ['kernel-1', 'fdt-1', 'rootfs-1']:
                with self.subTest(image=name):
                    node = tree.path_offset('/images/' + name)
                    start = (tree.totalsize() + 3) & ~3
                    start += tree.getprop(node, 'data-offset').as_uint32()
                    data = bytearray(self.fit)
                    data[start] ^= 1
                    with self.assertRaisesRegex(ValueError, 'hash'):
                        self.check_fit(data)

    def test_supports_runner_libfdt_without_hasprop(self):
            class RunnerFdt(libfdt.Fdt):
                def __getattribute__(self, name):
                    if name == 'hasprop':
                        raise AttributeError('libfdt 1.6.1 does not provide hasprop')
                    return super().__getattribute__(name)

            with patch.object(payload.libfdt, 'Fdt', RunnerFdt):
                self.check_fit(self.fit)
                self.check_fit(self.inline)

    def test_supported_fit_storage_formats(self):
            for options in [{}, {'external': False}, {'position': 4096}]:
                with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                    self.check_fit(make_fit(Path(directory), **options))

    def mutate_fit(self, change):
            tree = libfdt.Fdt(self.inline)
            tree.resize(len(self.inline) + 2048)
            change(tree)
            return tree.as_bytearray()

    def test_hashes_are_required_and_only_supported_algorithms_are_accepted(self):
            def no_hashes(tree):
                for name in ['hash-3', 'hash-2', 'hash-1']:
                    tree.del_node(tree.path_offset('/images/kernel-1/' + name))

            def md5_hash(tree):
                node = tree.path_offset('/images/kernel-1/hash-1')
                tree.setprop_str(node, 'algo', 'md5')
                component = tree.getprop(tree.path_offset('/images/kernel-1'), 'data')
                tree.setprop(node, 'value', hashlib.md5(component).digest())

            for change in [
                no_hashes,
                md5_hash,
                lambda tree: tree.setprop(tree.path_offset('/images/kernel-1/hash-1'), 'value', b'bad'),
            ]:
                with self.subTest(change=change):
                    data = self.mutate_fit(change)
                    with self.assertRaisesRegex(ValueError, 'hash'):
                        self.check_fit(data)

    def test_configurations_require_default_and_typed_resolved_components(self):
            cases = [
                ('/configurations', 'default', None),
                ('/configurations', 'default', b'absent\0'),
                ('/configurations', 'default', b'config-1'),
                ('/configurations/config-1', 'kernel', None),
                ('/configurations/config-1', 'fdt', b'absent\0'),
                ('/configurations/config-1', 'kernel', b'rootfs-1\0'),
                ('/configurations/config-1', 'loadables', None),
                ('/configurations/config-1', 'loadables', b'fdt-1\0'),
                ('/configurations/config-1', 'loadables', b'rootfs-1\0absent\0'),
            ]
            for path, name, value in cases:
                with self.subTest(path=path, name=name, value=value):
                    def change(tree):
                        node = tree.path_offset(path)
                        if value is None:
                            tree.delprop(node, name)
                        else:
                            tree.setprop(node, name, value)
                    with self.assertRaisesRegex(ValueError, 'FIT'):
                        self.check_fit(self.mutate_fit(change))

    def test_component_ranges_are_nonempty_unambiguous_and_inside_payload(self):
            def external(tree, start, size):
                node = tree.path_offset('/images/kernel-1')
                tree.delprop(node, 'data')
                tree.setprop_u32(node, 'data-position', start)
                tree.setprop_u32(node, 'data-size', size)
                component = b'' if size == 0 else b'trailer bytes'
                for name, algorithm in [('hash-1', 'crc32'), ('hash-2', 'sha1'), ('hash-3', 'sha256')]:
                    digest = struct.pack('>I', zlib.crc32(component)) if algorithm == 'crc32' else hashlib.new(algorithm, component).digest()
                    tree.setprop(tree.path_offset('/images/kernel-1/' + name), 'value', digest)

            for start, size in [(0xffffffff, 0), (0xffffffff, 20), (0, 0)]:
                with self.subTest(start=start, size=size):
                    with self.assertRaisesRegex(ValueError, 'FIT.*(range|data)'):
                        self.check_fit(self.mutate_fit(lambda tree: external(tree, start, size)))
            for prop in ['data-offset', 'data-position', 'data-size']:
                with self.subTest(ambiguous=prop):
                    with self.assertRaisesRegex(ValueError, 'FIT.*data'):
                        self.check_fit(self.mutate_fit(lambda tree: tree.setprop_u32(tree.path_offset('/images/kernel-1'), prop, 1)))

            # Even matching hashes must not let firmware data point into fwtool metadata.
            length = len(self.inline) + 2048
            data = self.mutate_fit(lambda tree: external(tree, length, len(b'trailer bytes')))
            trailer_data = b'trailer bytes'
            data += trailer_data + struct.pack('>IIB3xI', 0x46577830, 0, 1, len(trailer_data) + 16)
            with self.assertRaisesRegex(ValueError, 'FIT.*range'):
                self.check_fit(data)

    def metadata(self):
            return {'compat_version': '2.0',
                    'new_supported_devices': ['gemtek,w1700k-ubi'],
                    'supported_devices': ['legacy compatibility message'],
                    'version': {'target': 'airoha/an7581', 'board': 'gemtek_w1700k-ubi'}}

    def test_metadata_rejects_wrong_container_types_and_near_device_names(self):
            verifier = getattr(payload, 'verify_metadata', None)
            self.assertTrue(callable(verifier), 'Missing shared metadata validator')
            verifier(self.metadata())
            for key in ['new_supported_devices', 'supported_devices']:
                for value in ['gemtek,w1700k-ubi', {'gemtek,w1700k-ubi': True}, None, [None],
                              ['prefix-gemtek,w1700k-ubi'], ['gemtek,w1700k-ubi-extra']]:
                    with self.subTest(key=key, value=value):
                        metadata = self.metadata()
                        metadata.pop('new_supported_devices', None)
                        metadata[key] = value
                        with self.assertRaisesRegex(ValueError, 'device'):
                            verifier(metadata)
            for value in [None, [], 'metadata']:
                with self.subTest(metadata=value), self.assertRaises(ValueError):
                    verifier(value)
            for value in [None, [], 'version']:
                metadata = self.metadata(); metadata['version'] = value
                with self.subTest(version=value), self.assertRaises(ValueError):
                    verifier(metadata)
            for path, values in [('compat_version', [2.0, None, '2.0-extra']),
                                 ('target', ['airoha/an7581-extra', None, []]),
                                 ('board', ['gemtek_w1700k-ubi-extra', None, {}])]:
                for value in values:
                    metadata = self.metadata()
                    destination = metadata if path == 'compat_version' else metadata['version']
                    destination[path] = value
                    with self.subTest(path=path, value=value), self.assertRaisesRegex(ValueError, path):
                        verifier(metadata)
            metadata = self.metadata(); metadata.pop('new_supported_devices')
            metadata['supported_devices'] = ['gemtek,w1700k-ubi']
            verifier(metadata)

    def test_cli_validates_both_inputs_even_with_python_optimization(self):
            with tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / 'image.itb'; image.write_bytes(self.fit)
                metadata_path = Path(directory) / 'metadata.json'
                for optimize in ['0', '1']:
                    for mutation, expected in [(None, None), ('devices', 'device'), ('board', 'board'), ('fit', 'FIT'), ('json', 'metadata')]:
                        with self.subTest(optimize=optimize, mutation=mutation):
                            metadata = self.metadata()
                            image.write_bytes(self.fit)
                            if mutation == 'devices':
                                metadata['new_supported_devices'] = 'gemtek,w1700k-ubi'
                            elif mutation == 'board':
                                metadata['version']['board'] = 'another-board'
                            elif mutation == 'fit':
                                image.write_bytes(bytes.fromhex('d00dfeed') + b'fixture')
                            metadata_path.write_text('{' if mutation == 'json' else json.dumps(metadata))
                            result = subprocess.run([sys.executable, str(Path(payload.__file__)), str(image), str(metadata_path)],
                                                    env={**os.environ, 'PYTHONOPTIMIZE': optimize}, text=True, capture_output=True)
                            if expected is None:
                                self.assertEqual(result.returncode, 0, result.stderr)
                                self.assertIn('Verified', result.stdout)
                            else:
                                self.assertNotEqual(result.returncode, 0)
                                self.assertIn(expected, result.stderr)
                                self.assertNotIn('Traceback', result.stderr)

    def test_external_geometry_rejects_truncation_with_matching_sliced_hash(self):
            tree = libfdt.Fdt(self.fit)
            node = tree.path_offset('/images/rootfs-1')
            start = ((tree.totalsize() + 3) & ~3) + tree.getprop(node, 'data-offset').as_uint32()
            size = tree.getprop(node, 'data-size').as_uint32()
            truncated = bytearray(self.fit[:start + size - 1])
            tree = libfdt.Fdt(truncated)
            tree.setprop(tree.path_offset('/images/rootfs-1/hash-1'), 'value',
                         hashlib.sha256(truncated[start:]).digest())
            with self.assertRaisesRegex(ValueError, 'FIT.*range'):
                self.check_fit(tree.as_bytearray())

    def test_malformed_fdt_headers_and_property_encodings_are_refused(self):
            for field in [4, 8, 12, 16, 20, 24, 32, 36]:
                with self.subTest(header_field=field):
                    data = bytearray(self.fit)
                    struct.pack_into('>I', data, field, 0xffffffff)
                    with self.assertRaisesRegex(ValueError, 'FIT'):
                        self.check_fit(data)
            for length in [0, 4, 39, 40, len(self.fit) - 100]:
                with self.subTest(truncated=length), self.assertRaisesRegex(ValueError, 'FIT'):
                    self.check_fit(self.fit[:length])
            for value in [b'', b'\0', b'\0' * 8]:
                with self.subTest(size_encoding=value):
                    def change(tree):
                        node = tree.path_offset('/images/kernel-1')
                        tree.delprop(node, 'data')
                        tree.setprop_u32(node, 'data-position', 0)
                        tree.setprop(node, 'data-size', value)
                    with self.assertRaises(ValueError):
                        self.check_fit(self.mutate_fit(change))
            for path, name, value in [
                ('/images/kernel-1', 'data', b''),
                ('/images/kernel-1/hash-1', 'algo', b''),
                ('/images/kernel-1/hash-1', 'algo', b'sha256'),
                ('/images/kernel-1/hash-1', 'algo', b'sha256\0crc32\0'),
                ('/configurations', 'default', b'config-1\0other\0'),
            ]:
                with self.subTest(path=path, name=name), self.assertRaises(ValueError):
                    self.check_fit(self.mutate_fit(lambda tree: tree.setprop(tree.path_offset(path), name, value)))

    def test_each_declared_component_hash_is_checked(self):
            for image, names in [('kernel-1', ['hash-1', 'hash-2', 'hash-3']),
                                 ('fdt-1', ['hash-1']), ('rootfs-1', ['hash-1'])]:
                for name in names:
                    with self.subTest(image=image, hash=name):
                        def change(tree):
                            node = tree.path_offset('/images/' + image + '/' + name)
                            value = bytearray(tree.getprop(node, 'value')); value[0] ^= 1
                            tree.setprop(node, 'value', bytes(value))
                        with self.assertRaisesRegex(ValueError, 'hash'):
                            self.check_fit(self.mutate_fit(change))

    def test_unreferenced_images_and_nondefault_configurations_are_checked(self):
            def extra_image(tree):
                node = tree.add_subnode(tree.path_offset('/images'), 'unused')
                tree.setprop(node, 'data', b'extra')
                node = tree.add_subnode(tree.path_offset('/images/unused'), 'hash-1')
                tree.setprop_str(node, 'algo', 'sha256')
                tree.setprop(node, 'value', b'wrong')
            with self.assertRaisesRegex(ValueError, 'hash'):
                self.check_fit(self.mutate_fit(extra_image))
            with self.assertRaisesRegex(ValueError, 'FIT'):
                self.check_fit(self.mutate_fit(lambda tree: tree.add_subnode(tree.path_offset('/configurations'), 'invalid')))
