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

## Current published-source lock refresh

| Source | Post-customization inventory SHA256 |
| --- | --- |
| OpenWrt `7edc67adadb1e2d21ca53b0377086f80224a6cba` | `2e582bd48d919973449f163be0cf428af13c3258480a7cf0d4019706d52a1a58` |
| ImmortalWrt `4765b657625ec5bbda74b44400465fe043802b30` | `8a2797e8f5f18c8445724784e756eb756825c9d1681a2634acfb3de347663a57` |

Reproduced the preceding `1feb9e…` / `d1626e…` locks before comparing every
path/mode/content record. Independently materialized both current immutable
source archives with Git modes and ran the complete production `custom.sh`,
using local `yahuisme/packages` `859695cd3ac52af28b507e9b11840b9d1d2a05bf`
at its clone boundary and real immutable LuCI flash/dictionary inputs. Only the
container `/cache-scripts` path was relocated; real `external_packages.prepare()`
ran, not a stub. Both resulting inventories exactly match the locks above.
Artifact-backed successful final configs were copied, not regenerated locally.

Complete locked-record differences are four OpenWrt and 18 ImmortalWrt paths;
no existing locked mode changes were found:

- OpenWrt updates ccache 4.13.3 to 4.14.2 and its source SHA256, with only an
  upstream line-offset refresh in `100-honour-copts.patch`; the actual COPTS
  behavior is retained. Both distributions update GNU patch 2.8 to 2.8.1 and
  its source SHA256. These are genuine early producer changes, not hash noise.
- OpenWrt adds `tools/fakeroot/patches/400-stat64-fix.patch` (NetBSD stat symbol
  detection/wrapping). Fakeroot is outside this early closure; its bytes are
  nevertheless locked.
- ImmortalWrt adds Rust/bindgen/cbindgen/corrosion/sccache tools and their
  dependency/stamp selectors, Cargo vendor-download methods and three wrapper/
  vendor scripts. CMake/Meson Rust values are conditional on rust-values being
  included; none of the 16 early producer recipes includes it. The toplevel
  environment unexports and distclean change do not add early producers.
  `include/scan.mk` adds Rust metadata dependencies during package scanning,
  not an early host recipe include; it is outside the locked producer set.
- ImmortalWrt's two Meson native/cross templates gain Rust placeholders.
  `tools/meson` installs these templates during this closure: these are real
  output changes and remain covered, along with `include/meson.mk` consumers.
- Both distributions' `config/Config-build.in` SECCOMP architecture expansion
  affects configuration generation, not this post-defconfig host recipe set.
  Full effective config binding is unchanged; no config generator was run.

Native query-only GNU make on each complete current `tools/Makefile` and its
successful final config again yields exactly the same 16 producers listed
above, including implicit core/patch dependencies. The tools file has no
parse-time shell or make includes; variable edges are fully expanded, recipes,
recursive make and include remaking are not executed, and both queries exit 0.
The existing recursive framework audit remains applicable to unchanged files;
the changed CMake/Meson/download/toplevel paths were re-reviewed, including
post-install hooks, tools headers/site inputs and generated external includes.
No new external input enters the enabled C/C++ closure. Existing Rust/all-host
selector fallback remains mandatory; this review does not approve Rust inputs.

Acceptance exercises the actual CLI and unmodified allowlist on both complete
post-custom trees. TC_KEY-only changes retain the bootstrap key; producer,
patch/template, framework, generated-include content/mode/presence and full
config changes invalidate. Unknown inventories bind TC_KEY; linked/nonregular
external includes reject. All Rust/all-host selectors remain TC-bound. Existing
native archive-link, nanosecond/stamp, quota and production YAML ordering tests
are reused/executed rather than duplicated; no restore prefix or budget changes.

Appending locks changes the helper self-hash, deliberately creating a cold
bootstrap generation. It does not change TC compatibility, namespaces or CC/DL
policy, admit old archives, or bypass the original `make tools/ccache/compile`
stamp checks. The observed previous bootstrap windows were 577 s / 619 s,
not promised savings. First-generation archive population, real warm stamp
reuse, compressed size and net restore/pack/job savings remain unmeasured and
require separately authorized CI; source queries and simulated native tar
artifacts are not firmware compilation or hardware acceptance.

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
