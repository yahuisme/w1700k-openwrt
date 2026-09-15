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

## Parallel upload capacity

Standard/OC writers have disjoint **6.15/3.85 decimal GB** budgets, totaling
10,000,000,000 bytes. Every admission counts all generations/refs in its group,
unknown namespaces, the candidate and at least 64 MiB wrapper margin. Save and
confirm the exact nonempty current-ref replacement before pruning its old keys;
never pre-delete a known-good seed to make room. Matrix jobs remain parallel.

The 2026-09-15 inventory and run 34922925962 compressed sizes require
6,066,612,571 bytes for standard download replacement and 3,762,191,409 for OC
toolchain replacement. The former fails under 6 GB. A 6.2/3.8 split leaves OC
only 37,808,591 bytes; 6.15/3.85 balances spare capacity at 83,387,429 and
87,808,591 bytes. These are measured-snapshot margins, **not permanent growth
guarantees**: simultaneous growth, additional generations/refs and unknown caches
consume the same space. Cold population at all per-entry caps fits, but warm
replacement at every per-entry maximum need not fit. Denial preserves old data;
accumulated generations may require separately reviewed maintenance, not an
automatic destructive fallback. Per-entry caps and exact keys are unchanged.

Run `test_cache_helper.py` and `test_cache_order.py` via unittest discovery for
measured replacement, full YAML-tail sequencing, capacity boundaries, unknown
namespace accounting, parallel isolation, cold/warm and failed-save coverage.

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
