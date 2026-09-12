# Exact host-artifact cache

## Contract

The key hashes the complete final `.config`, source contents and modes under
`INPUTS`, builder image ID, host architecture, build path and fingerprint policy.
There is no CONFIG projection, audited-source lock or historical commit dependency.
This policy change deliberately starts a new exact-key generation; no old-key
fallback is allowed. Package/version settings and literal DEFAULT_PACKAGES changes
remain invalidators. External mutable compiler/kernel/source trees are rejected.

Only the three explicit generic/Airoha runtime `base-files` overlays and ignored
`scripts/config` generated outputs are excluded. Kernel files/patches and target
recipes remain inputs. Input mtimes are normalized to `EPOCH`; completion stamps
are never touched. PAX archives preserve nanoseconds and restore matching
`build_dir/host`, `build_dir/toolchain-*`, `staging_dir/host` and
`staging_dir/toolchain-*` together after clearing old build/staging trees.

## Reproduce

```sh
python3 -m unittest discover -s tests -p 'test_cache_key.py' -v
# Disposable, configured Airoha/an7581 source with native host build prerequisites:
python3 tests/check_cache_upstream.py "$PREPARED_BUILDROOT"
```

The opt-in check reads dependency rules from the supplied current source, checks
full-config invalidation, expands real kernel-header stamp variables, compiles
`tools/flock`, then compresses/deletes/restores artifacts and runs warm make.
It requires unchanged nanosecond `.built` and no flock compiler command after
restore; a source-content mutation must miss and compile on the cold path.
It modifies the supplied disposable tree. Empty toolchain layout fixtures are
**not GCC validation**. These checks do not establish full firmware build speed.

## Compression choice

Packing uses `pigz -1` when already installed, otherwise `gzip -1`; extraction
continues to use gzip-compatible tar. No installation is performed by this helper.
The inspected local `ghcr.io/w1700k/fastbuild_base:base-builder` image
(`8563dec89b4c`, aarch64) has gzip but **no pigz**, so its actual path is gzip -1.

A PAX sample of real source plus native flock build/staging files gave these
three-run median compression-only measurements (not a production-size cache):

| Environment | Compressor | Seconds | Bytes |
| --- | --- | ---: | ---: |
| builder, root | gzip default | 0.1234 | 1096478 |
| builder, root | gzip -1 | 0.0613 | 1279603 |
| host, existing executable | pigz -1 | 0.0164 | 1274209 |

Level 1 trades a larger archive for lower local compression time. Existing
compressed-size caps still apply; this sample does not prove full-cache capacity
or CI wall-time improvement. Pigz's host result does not imply builder availability.
Reproduce on the same sample, checking executables in the actual builder first:

```sh
tar --format=posix -cf sample.tar -C "$PREPARED_BUILDROOT" \
  tools toolchain include scripts build_dir/host staging_dir/host
/usr/bin/time gzip -c sample.tar > default.gz
/usr/bin/time gzip -1 -c sample.tar > fast.gz
# Only where command -v pigz succeeds:
/usr/bin/time pigz -1 -c sample.tar > parallel.gz
wc -c default.gz fast.gz parallel.gz
```
