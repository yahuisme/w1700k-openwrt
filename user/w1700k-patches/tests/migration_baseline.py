"""Load the exact pre-migration inputs without a packages checkout."""
import hashlib
import io
from pathlib import Path
import tarfile

MIGRATION = Path(__file__).parent / 'fixtures/migration-baseline.tar.gz'
# yahuisme/packages@14cc379984cc45cf10c6ce228fb44944bfa4f6af
SHA256 = '2c4f2c94622560a7f635dd5c41ee7630c2e9c2f88cf21ff3afae40b1cb09ecc0'


def migration_files():
    data = MIGRATION.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise AssertionError('historical migration archive checksum mismatch')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                files[member.name.removeprefix('w1700k-patches/')] = stream.read()
    return files
