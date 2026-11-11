#!/usr/bin/env python3
"""Shared structural and integrity checks for the W1700K payload."""
import hashlib
import json
import lzma
import stat
import sys
from pathlib import Path
import struct
import zlib

import libfdt


def verify_fit(path, *, kind='sysupgrade'):
    """Check all hashes and the references required by this image's role."""
    if kind not in ('sysupgrade', 'recovery', 'chainloader'):
        raise ValueError('Unsupported FIT role')
    data = bytearray(Path(path).read_bytes())
    if libfdt.fdt_check_full(data, len(data)) != 0:
        raise ValueError('Invalid FIT device tree layout')
    try:
        tree = libfdt.Fdt(data)
        if tree.version() != 17:
            raise ValueError('Unsupported FIT device tree version')
        payload_end = len(data)
        # fwtool appends size-delimited metadata/signature records. Exclude all
        # of them from component ranges; fwtool itself checks their CRC later.
        while payload_end >= 16 and data[payload_end - 16:payload_end - 12] == b'FWx0':
            trailer_size = struct.unpack_from('>I', data, payload_end - 4)[0]
            if trailer_size < 16 or trailer_size > payload_end:
                raise ValueError('Invalid FIT fwtool trailer range')
            payload_end -= trailer_size
        if tree.totalsize() > payload_end:
            raise ValueError('Invalid FIT device tree range')
        images = tree.path_offset('/images')
        image_nodes = {tree.get_name(node): node for node in _children(tree, images)}
        configurations = tree.path_offset('/configurations')
        default = _strings(tree, configurations, 'default', single=True)[0]
        configs = {tree.get_name(node): node for node in _children(tree, configurations)}
        if default not in configs:
            raise ValueError('Invalid FIT default configuration')
        for config in configs.values():
            for property_name, expected_type in [('kernel', 'kernel'), ('fdt', 'flat_dt')]:
                reference = _strings(tree, config, property_name, single=True)[0]
                if reference not in image_nodes or _strings(tree, image_nodes[reference], 'type', single=True)[0] != expected_type:
                    raise ValueError(f'Invalid FIT {property_name} reference')
            if kind == 'sysupgrade':
                loadables = _strings(tree, config, 'loadables')
                if any(reference not in image_nodes for reference in loadables):
                    raise ValueError('Invalid FIT loadables reference')
                if not any(_strings(tree, image_nodes[reference], 'type', single=True)[0] == 'filesystem' for reference in loadables):
                    raise ValueError('Missing FIT rootfs loadable')
            elif kind == 'recovery' and tree.getprop(config, 'ramdisk', quiet=(libfdt.NOTFOUND,)) != -libfdt.NOTFOUND:
                # Airoha's native recovery embeds initramfs into the kernel.
                # Separate-initramfs targets additionally carry a ramdisk node.
                ramdisk = _strings(tree, config, 'ramdisk', single=True)[0]
                if (ramdisk not in image_nodes or
                        _strings(tree, image_nodes[ramdisk], 'type', single=True)[0] != 'ramdisk'):
                    raise ValueError('Invalid FIT ramdisk reference')
        for image in image_nodes.values():
            # getprop's NOTFOUND sentinel also supports older runner libfdt versions.
            inline = tree.getprop(image, 'data', quiet=(libfdt.NOTFOUND,)) != -libfdt.NOTFOUND
            position = tree.getprop(image, 'data-position', quiet=(libfdt.NOTFOUND,)) != -libfdt.NOTFOUND
            offset = tree.getprop(image, 'data-offset', quiet=(libfdt.NOTFOUND,)) != -libfdt.NOTFOUND
            if inline:
                if position or offset or tree.getprop(image, 'data-size', quiet=(libfdt.NOTFOUND,)) != -libfdt.NOTFOUND:
                    raise ValueError('Ambiguous FIT component data')
                component = bytes(tree.getprop(image, 'data'))
                if not component:
                    raise ValueError('Empty FIT component data')
            else:
                if position == offset:
                    raise ValueError('Ambiguous or missing FIT component data location')
                size = tree.getprop(image, 'data-size').as_uint32()
                if position:
                    start = tree.getprop(image, 'data-position').as_uint32()
                else:
                    start = ((tree.totalsize() + 3) & ~3) + tree.getprop(image, 'data-offset').as_uint32()
                if size == 0 or start < tree.totalsize() or start + size > payload_end:
                    raise ValueError('Invalid FIT component data range')
                component = data[start:start + size]
            hashes = [node for node in _children(tree, image) if tree.get_name(node).startswith('hash')]
            if not hashes:
                raise ValueError('Missing FIT component hash')
            for node in hashes:
                algorithm = _strings(tree, node, 'algo', single=True)[0]
                if algorithm not in {'crc32', 'sha1', 'sha256'}:
                    raise ValueError('Unsupported FIT hash algorithm')
                if algorithm == 'crc32':
                    digest = struct.pack('>I', zlib.crc32(component))
                else:
                    digest = hashlib.new(algorithm, component).digest()
                if digest != tree.getprop(node, 'value'):
                    raise ValueError('FIT component hash mismatch')
    except (libfdt.FdtException, struct.error) as error:
        raise ValueError(f'Invalid FIT: {error}') from error


def verify_embedded(path, expected):
    """Hash frozen inputs from the native embedded-initramfs FIT itself."""
    tree = libfdt.Fdt(Path(path).read_bytes())
    config = tree.path_offset('/configurations')
    selected = _strings(tree, config, 'default', single=True)[0]
    kernel = _strings(tree, tree.path_offset('/configurations/' + selected), 'kernel', single=True)[0]
    compressed = bytes(tree.getprop(tree.path_offset('/images/' + kernel), 'data'))
    try:
        # Bound unexpected compression expansion; normal current images are <80 MiB.
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        data = decoder.decompress(compressed, max_length=256 * 1024 * 1024)
    except lzma.LZMAError as error:
        raise ValueError('Invalid installer kernel compression') from error
    if len(data) == 256 * 1024 * 1024:
        raise ValueError('Installer expanded kernel exceeds verification limit')
    if not decoder.eof:
        raise ValueError('Truncated installer kernel compression')
    def header_at(position):
        header = data[position + 6:position + 110]
        if (position % 4 or data[position:position + 6] != b'070701'
                or len(header) != 104 or any(c not in b'0123456789abcdefABCDEF' for c in header)):
            raise ValueError('Invalid newc header')
        fields = [int(header[i:i + 8], 16) for i in range(0, 104, 8)]
        namesize = fields[11]
        if not 0 < namesize <= 4096 or position + 110 + namesize > len(data):
            raise ValueError('Invalid newc filename range')
        name = data[position + 110:position + 110 + namesize]
        if name[-1:] != b'\0' or b'\0' in name[:-1]:
            raise ValueError('Invalid newc filename terminator')
        name = name[:-1].decode('utf-8').removeprefix('./')
        body = (position + 110 + namesize + 3) & ~3
        if body + fields[6] > len(data):
            raise ValueError('Invalid newc data range')
        return fields, name, body

    # Skip kernel string literals, then commit to the first valid native newc
    # header. Never search inside member data after recognizing an archive.
    start = data.find(b'070701')
    while start >= 0:
        try:
            header_at(start)
            break
        except (ValueError, UnicodeError):
            start = data.find(b'070701', start + 1)
    if start < 0:
        raise ValueError('Missing embedded installer archive')
    entries, position = {}, start
    while True:
        fields, name, position = header_at(position)
        mode, size = fields[1], fields[6]
        if name == 'TRAILER!!!':
            break
        # Validate after recognizing the archive: an unsafe first member must
        # not be skipped as a kernel string literal. Allow the native root
        # directory and one leading ./, but never filesystem path aliases.
        if name in ('', '.') and stat.S_ISDIR(mode):
            pass
        elif any(part in ('', '.', '..') for part in name.split('/')):
            raise ValueError('Invalid embedded newc path: ' + name)
        if name in expected:
            if name in entries or not stat.S_ISREG(mode):
                raise ValueError('Duplicate/nonregular embedded input: ' + name)
            if name in ('installer/install.sh', 'lib/preinit/00_installer') and not mode & 0o111:
                raise ValueError('Nonexecutable embedded installer: ' + name)
            entries[name] = 'sha256:' + hashlib.sha256(memoryview(data)[position:position + size]).hexdigest()
        position = (position + size + 3) & ~3
    if entries != expected:
        raise ValueError('Embedded installer input differs from frozen bytes')
    # The native producer uses one archive. Reject any additional valid archive
    # after its trailer rather than accepting later path replacements.
    later = data.find(b'070701', position)
    while later >= 0:
        try:
            header_at(later)
        except (ValueError, UnicodeError):
            later = data.find(b'070701', later + 1)
            continue
        raise ValueError('Unexpected additional initramfs archive')


def verify_metadata(metadata):
    """Require exact board identity and typed fwtool compatibility metadata."""
    if not isinstance(metadata, dict):
        raise ValueError('Invalid metadata object')
    for name in ['supported_devices', 'new_supported_devices']:
        if name in metadata:
            value = metadata[name]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f'Invalid metadata {name}: expected device list of strings')
    devices = metadata.get('new_supported_devices', metadata.get('supported_devices', []))
    if 'gemtek,w1700k-ubi' not in devices:
        raise ValueError('Metadata device mismatch')
    if metadata.get('compat_version') != '2.0':
        raise ValueError('Metadata compat_version mismatch')
    version = metadata.get('version')
    if not isinstance(version, dict):
        raise ValueError('Invalid metadata version object')
    for name, expected in [('target', 'airoha/an7581'), ('board', 'gemtek_w1700k-ubi')]:
        if version.get(name) != expected:
            raise ValueError(f'Metadata {name} mismatch')


def _strings(tree, node, name, *, single=False):
    value = bytes(tree.getprop(node, name))
    if not value.endswith(b'\0'):
        raise ValueError(f'Invalid FIT {name} string')
    strings = value[:-1].split(b'\0')
    if any(not item or b'/' in item for item in strings) or (single and len(strings) != 1):
        raise ValueError(f'Invalid FIT {name} string')
    try:
        return [item.decode('ascii') for item in strings]
    except UnicodeDecodeError as error:
        raise ValueError(f'Invalid FIT {name} string') from error


def _children(tree, parent):
    node = tree.first_subnode(parent, quiet=(libfdt.NOTFOUND,))
    while node >= 0:
        yield node
        node = tree.next_subnode(node, quiet=(libfdt.NOTFOUND,))


def main():
    if len(sys.argv) != 3:
        print(f'usage: {sys.argv[0]} IMAGE METADATA_JSON', file=sys.stderr)
        return 1
    try:
        verify_fit(sys.argv[1])
        try:
            metadata = json.loads(Path(sys.argv[2]).read_text())
        except (ValueError, UnicodeError) as error:
            raise ValueError(f'Invalid metadata JSON: {error}') from error
        verify_metadata(metadata)
    except (ValueError, OSError) as error:
        print(f'Payload verification failed: {error}', file=sys.stderr)
        return 1
    print('Verified FIT components and W1700K metadata')
    return 0


if __name__ == '__main__':
    sys.exit(main())
