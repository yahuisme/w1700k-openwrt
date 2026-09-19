#!/usr/bin/env python3
"""Controlled Docker recipe + installed packages, never OCI creation timestamps.

Run inside the exact builder used for compilation, with its docker context mounted
read-only. This assumes only the reviewed recipe installs non-dpkg tools (Go's
pinned checksum is in Dockerfile); it is not an arbitrary-image equivalence test.
"""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys


def fingerprint(context):
    files = []
    # No COPY/ADD: Dockerfile is currently the only consumed build input.
    for name in ('Dockerfile',):
        path = context / name
        if path.is_symlink():
            raise ValueError('linked Docker input: ' + str(path))
        if path.is_file():
            files.append([str(path.relative_to(context)), hashlib.sha256(path.read_bytes()).hexdigest()])
    if not (context / 'Dockerfile').is_file():
        raise ValueError('missing Dockerfile')
    packages = subprocess.check_output(
        ['dpkg-query', '-W', '-f=${Package}\t${Architecture}\t${Version}\n'],
        text=True).splitlines()
    if not packages:
        raise ValueError('empty installed package inventory')
    payload = ['builder-v1', platform.machine(), sorted(packages), files,
               hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


if __name__ == '__main__':
    print(fingerprint(Path(sys.argv[1])))
