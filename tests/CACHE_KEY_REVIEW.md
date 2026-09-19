# Exact host-artifact cache

## Contract

The key hashes the complete final `.config`, source contents and modes under
`INPUTS`, builder fingerprint, host architecture, build path and fingerprint policy.
`tc-inputs-v7` replaces image-ID compatibility; the workflow still inspects and
runs the exact local `IMAGE_ID`, but never hashes OCI creation timestamps.

`scripts/builder_fingerprint.py` runs inside that container before source prep.
Policy `builder-v1` hashes the names and per-file SHA256 of actual recipe inputs
(currently **only Dockerfile**, because it has no COPY/ADD), the SHA256 of its own
implementation, `platform.machine()`, and the complete sorted `dpkg-query`
package/architecture/version inventory. Empty or failing inventory, a missing
Dockerfile or a symlinked Dockerfile is rejected. The pinned official Debian base
and official Go archive checksum are covered by Dockerfile bytes. Adding COPY/ADD
requires extending the explicit input list and reviewing this contract.

README, smoke script and .dockerignore edits do not invalidate the toolchain key:
none currently contributes bytes to the built environment. File mtimes, inventory
order, image IDs and container IDs also do not invalidate it. Rolling apt package
updates do. This controlled-recipe contract is not arbitrary-image equivalence
or a claim of bit-reproducible apt/image contents. Do not introduce mutable
non-dpkg downloads, build-arg overrides or ad-hoc container mutations without
verified identities in this contract. Implementation changes invalidate identity.

Only toolchain restore is exact (no prefix fallback). Existing compiler/download
cache prefixes, sizes, repository admission budget and scheduling are unchanged.
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

## Official Debian builder validation

`docker build --platform linux/arm64 -t w1700k-builder:local docker` uses only the
small reviewed Docker context. Both Dockerfile CMD and workflow run explicitly
use `sleep infinity`; no interactive TTY is required. Run `docker/smoke.sh` in a
fresh container before fetching source; it performs no compilation, including Go.
The Go archive is the official 1.26.8 linux-arm64 release and SHA256-verified.
The feed still builds its own final Go compiler.

Local validation reused candidate apt/Go layers and exercised the actual repository
Dockerfile, inspected image identity, default process, workflow-equivalent mounts,
223 real dpkg records and no-network smoke. Two fingerprints of the same container
were equal; a controlled Dockerfile change invalidated them. Unit tests separately
cover inventory ordering, package version/architecture, host architecture, content,
mtime stability, build/inspect/run/fingerprint failures and exact restore wiring.
This is not a firmware build or a measured CI speedup.

LLVM audit: official OpenWrt `d9fcbfc5850f1faafd266b81af2ffeb17faf91dd`
`toolchain/Config.in` selects `USE_LLVM_HOST` only via `BPF_TOOLCHAIN_HOST`;
normal choice defaults to prebuilt LLVM when present, otherwise build LLVM.
`include/bpf.mk` requires clang >=12, llc, llvm-dis, opt and llvm-strip for host
mode. The retained historical prepared OpenWrt config selected
`BPF_TOOLCHAIN_BUILD_LLVM=y`, not host mode, and current config.diff does not
force host mode. Thus clang alone would not suffice, but adding a host LLVM
stack is not justified by current inputs. Debian recipe intentionally omits it.
Rolling source/feed configuration can change: a new final defconfig/firmware build
is **not** verified locally. A future host-mode change must supply the whole LLVM
suite and validate BPF support. Never infer final configuration from the fragment.

The full non-compilation regression is run with unittest discovery. Prepared-tree
checks require an actual retained final `.config`; do not manufacture one or
compile Kconfig under the no-compilation gate. `check_cache_upstream.py` compiles
host tools and is deliberately outside this validation. Both workflows fail
before download/cache restore if final defconfig selects `USE_LLVM_HOST=y`.
Shell tests cover host rejection and build/disabled acceptance.

## Single-standard upload capacity

One writer has a **10,000,000,000-byte total** budget. Every admission counts
all generations/refs, retired/unknown namespaces, the candidate and at least
64 MiB wrapper margin. Save and confirm the exact nonempty current-ref
replacement before pruning its old keys; never pre-delete a known-good seed.
Compiler, exact toolchain and download save/cleanup sequencing is retained.
Retired OC entries are charged but not treated as standard generations.
Per-entry caps and exact-key matching are unchanged. Denial preserves old data;
accumulated old caches may need separately authorized maintenance.

Run `test_cache_helper.py` and `test_cache_order.py` through unittest discovery
for complete YAML-tail sequencing, 10GB boundaries, legacy accounting,
cold/warm, failed upload and readback coverage. The migration removes a second
firmware build, but no new CI timings establish a specific speedup or optimum.

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
