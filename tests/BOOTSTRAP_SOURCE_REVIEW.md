# Reviewed early bootstrap sources

These locks authorize only the paired `build_dir/host` / `staging_dir/host`
snapshot immediately after `make tools/ccache/compile`, before world. They do
not authorize a world-complete host tree or a cross-toolchain restore.

| Source | Post-customization inventory SHA256 |
| --- | --- |
| OpenWrt `795f369b181cd128962fa8f60a03eaf0ac8afac6` | `04fe4b66fa7d80b01fab7f3a608ce169799c5e107c4c14bd9d21c92c7932acf7` |
| ImmortalWrt `16f34d329992d73900c2fd3d4b3d41b87e8cd234` | `1bef18e2273cc6ba0f0d2f8306a9df8b3fa0d31979ef0e9d8b059ee92ddf5ce3` |

The published ImmortalWrt source `13376a7112809b19d3413a1689a4244c45165003`
has the same complete inventory. Records cover every file under tools/scripts
and all `FIXED_INPUTS`, plus the present `.external-packages.mk`, including
permissions and missing fixed files. Materialize
Git regular/executable modes as 0644/0755: codeload tar headers can carry group
write bits that a Git checkout does not retain. Do not weaken the production
mode hash to accept tar permissions.

## Delta and producer review

The former reviewed OpenWrt `6db25ee835eb55af521125c84b12ffd0495f671b`
and ImmortalWrt `2f97ee0c9fad256d6ffea841f9bfe0415ece3ca9` inventories were
reconstructed and matched their existing hashes. Complete current records differ
at six OpenWrt paths and four ImmortalWrt paths, plus the newly inventoried
`.external-packages.mk`:

- Both: `rules.mk` adds a GCC version fallback in the normal internal-toolchain
  branch. It changes target compiler-version metadata, not host flags/recipes;
  early host producers do not use GCC_VERSION. External/native toolchains remain rejected. `tools/mold/Makefile`
  advances its version and source hash; mold is outside the early ccache closure.
- Both: production `external_packages.prepare()` changes `include/rootfs.mk`
  and `package/Makefile`. The added external make fragment contains only package
  and repository assignments. Its consumers are APK install/cache/snapshot and
  rootfs verification recipes, not early host producers. Because GNU make parses
  this fragment, its content/mode/presence are now explicitly inventoried; an
  injected include or changed assignment cannot inherit the reviewed lock.
  A linked or nonregular fragment is rejected. The snapshot target is
  a prerequisite of package/install, not tools/ccache/compile. The rootfs macros
  and ROOTFS_KEY shell expression are deferred. The actual changed framework
  bytes remain hashed; arbitrary later edits revert to full-toolchain binding.
- ImmortalWrt also drops an obsolete uClibc loader glob inside the deferred
  mklibs rootfs macro.
- OpenWrt: `include/subdir.mk` adds dtbs_check only for target/linux goals;
  `scripts/mkits-qsdk-ipq-image.sh` changes image description basename formatting.
  Neither changes the early host producer closure.

Native GNU make `-rR -qp` evaluation of the actual tools/Makefile, with recipe
expansion/recursive execution disabled, gives the same 16 producers for both:
ccache, cmake, expat, flock, libdeflate, libressl, meson, ninja, patch, pkgconf,
sed, tar, xxhash, xz, zlib and zstd. This includes implicit core/patch dependencies,
not merely tools-y. Its Makefiles, patches, source hashes and scripts are covered
by the inventory. The queried tools file has no parse-time `$(shell ...)`.

The recursive framework was reviewed through rules, toplevel/subdir/prereq,
host-build, depends, download/unpack/quilt, autotools, CMake and Meson. Their
host site inputs are site/cache and site/darwin; helper scripts and tool headers
are locked. Prepared/configured/built/installed stamps still use native rules.
Package/feed recipes can write host staging later, which is why the snapshot
must precede world. Other W1700K customization writes apps, target/package/feed
patches and runtime files, outside this producer inventory. No customization
adds a host producer or edits tools/scripts.

MX4200 retains its existing `5e09e8d00cbee466260d9391bab5d5f38a41ed7a439e553a9ee49a517deb435f`
lock: ImmortalWrt `4fc16f2985a358bd43bb522e43f05395fcbd6ed5` with its production
scripts/projectsmirrors.json filtering reproduces that hash. Its 16 early
producers also match; its helper and cache namespaces remain separate.

## Current rolling-source re-review

The previous reviewed inventories above were reconstructed from immutable
archives with Git modes and matched their recorded hashes before comparison.
The complete production custom script was then executed against both current
source/feed trees with the actual local packages checkout; only `/cache-scripts`
was relocated to the canonical helper. No compiler or defconfig ran. The copied
final configs are the successful runs' artifacts, not locally generated output.

| Source | Post-customization inventory SHA256 |
| --- | --- |
| OpenWrt `382a2109c849a45873aa908b4912fab667f603a0` | `1feb9eb4d0f1e047b36869dcf13343b31c5d58bc8a6aa6698b626316b571db5d` |
| ImmortalWrt `89f1ef18c888f841633f19f92655ee4b7f7716a4` | `d1626e1990166f86d6b16ba56574ea845f9c576a6b01f99d147fac03fcb6b2b6` |

Both post-custom trees differ from pristine inventoried source only in the
reviewed Aurora `include/rootfs.mk`, `package/Makefile` and generated external
fragment. Full path/mode/content comparisons find 18 changed OpenWrt inputs and
three ImmortalWrt inputs relative to the preceding locks:

- Both gain the host-autotools post-install hook removing `.la` files from
  host staging. This is a real host producer change, retained in the new lock;
  old host snapshots are not made compatible or reused across this change.
- OpenWrt adds Rust tools, Cargo vendoring/download methods, wrapper scripts,
  CMake/Meson Rust variables and Meson template fields. Native query-only make
  evaluation of the actual old/new tools rules under the captured final config
  yields the same 16-producer early closure listed above. Rust tools are not
  selected, but all their inventoried bytes remain locked. None of those early
  recipes includes Rust values; the conditional Rust additions are inactive.
  Selecting Rust host tools or BUILD_ALL_HOST_TOOLS forces full TC binding,
  since include/rust-*.mk is outside this early closure. Meson installs its
  changed native/cross templates during this closure, so
  those bytes are a genuine new artifact input, not excluded noise.
- ImmortalWrt additionally changes target-only dtbs checks in subdir.mk and the
  QSDK image-description helper. Neither adds an early producer.

The complete recursive host-build/download/unpack/depends/quilt/autotools/
CMake/Meson paths, install hooks, tools headers and site inputs remain covered.
The native make probe expands dependency variables without executing recipes,
recursive make, include remaking or parse-time shell commands. Unknown complete
inventories still fall back to TC_KEY. The source lock update changes the
bootstrap helper self-hash and starts a cold bootstrap generation, but leaves
TC/CC/DL policies and namespaces unchanged. No claim of measured speed or actual
compiled stamp reuse follows from this source/archive acceptance.

## Acceptance and limits

Run `BOOTSTRAP_SOURCE=/absolute/private/prepared/tree python3 -m unittest
discover -s tests -p test_bootstrap_cache.py -v`. The opt-in tests require the
real reviewed inventory, prove independence from TC_KEY, preserve later kernel,
runtime and external APK index-only changes, and test source/mode/config/builder/
environment invalidation plus unknown-inventory fallback. Full effective config
fingerprinting remains intact; BUILD_ALL_HOST_TOOLS stays toolchain-bound.
The helper self-hash makes this lock update cold for bootstrap only; it does not
change the toolchain key algorithm or inputs.

The OpenWrt config used for dependency parsing is the failed run's requested
config, not a newly generated final defconfig. Complete tools rule/config branch
review and full-config binding are retained; no local conf was run. ImmortalWrt
and MX4200 parsing use retained final configs. All checks are source/make-parse,
key and native archive fixture evidence. No compiler, configuration generator,
real bootstrap stamp reuse, firmware build, hardware or speed acceptance is
claimed. Rolling unknown inventories continue to bind to TC_KEY until reviewed.
