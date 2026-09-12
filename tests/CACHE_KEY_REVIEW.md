# W1700K v5 exact toolchain input projection

## Result and scope

The exact upstream trees e36bf95f68 and 8bf1c9253c now share a key with
bridge-flow-offload -> bridge-hw-offload selections, runtime VERSION_NUMBER,
and audited rootfs overlay changes. This is a deliberate cold schema change;
no old toolchain archive fallback was introduced. Other final configuration
symbols are retained, not a fragile GCC-only allowlist.

## Safety boundary (important)

Projection is enabled ONLY for the audited, normalized complete source-content
inventory in PROJECTION_SOURCE_LOCKS. This is an input lock, not a commit SHA:
the two trees share it because only literal DEFAULT_PACKAGES assignments and
the three runtime overlays differ. An unfamiliar source/recipe/helper/patch
change falls back to hashing FULL configuration and unprojected source. This
is a stricter key calculation, NOT a broad cache restore. It still detects all
compile changes, but future upstream changes or custom.sh edits inside this
inventory require another audited lock before runtime-only reuse is enabled.
Do not call it a general arbitrary-Makefile dependency analyzer. GNU make eval,
computed include paths, shell config readers and downstream configure programs
cannot safely be proved complete by CONFIG-token regex alone.

## Dependency evidence

- tools/Makefile selects b43-tools from CONFIG_PACKAGE_kmod-b43 and firmware
  options; compression, sparse, LLVM, mold, graphite and SDK also select tools.
  All these final symbols survive the projection. The complete tools tree,
  including recipes, patches, source files and header installation inputs, stays
  hashed. toolchain/Makefile selects libc, gcc stages, headers and optional tools.
- Every non-PACKAGE/non-VERSION final symbol stays hashed. ABI, CPU, libc,
  GCC/binutils versions, compiler/hardening flags and Kconfig side effects from
  package selection therefore invalidate the key even if not directly scanned.
- Direct CONFIG_PACKAGE_/CONFIG_VERSION_ references in the inventory survive;
  dynamic CONFIG_PREFIX_$(...) conservatively retains the entire prefix.
  Unprefixed CONFIG_$(...) retains everything unless the exact consumer was
  audited and content locked. Unknown consumers get the full key.
- Audited package-bin/package-pack functions produce target package artifacts;
  version.mk labels rootfs/images; package-metadata generates package/Kconfig
  metadata. Their effects on resolved compile options remain in final .config.
  ext-toolchain is not eligible: external toolchains, source overrides and
  external kernel trees are rejected because mutable external content is not
  locked. kernel.mk KernelPackage registration is target-package-only, whereas
  its direct compiler/kernel settings are retained as non-PACKAGE symbols.
- include/target.mk DEFAULT_PACKAGES consumption is DUMP metadata. Only literal
  Airoha DEFAULT_PACKAGES += lists are normalized; functions, substitutions,
  unknown consumers or changed audited files disable projection. The rest of
  target.mk, platform Makefiles and all kernel content remain locked.
- kernel-headers includes kernel.mk -> target.mk, toolchain-build/host-build,
  kernel-defaults and quilt. Host/Prepare invokes Kernel/Prepare/Default and
  headers_install; generic/platform files and patches remain inputs. Rootfs
  overlays are copied by package/base-files installation, not header recipes.
- host-build prepared hashes depend on recipe path+mtime; input mtimes are
  normalized, never completion stamps. POSIX/PAX archives preserve nanoseconds.

## Local verification

Both repositories: 33 unittest tests, actionlint, git diff --check pass.
check_cache_upstream.py uses git archive of BOTH actual upstream trees and
asserts equal keys despite distinct runtime package and version config values.
It asserts misses for b43 tool selection, GCC version, host flags, kernel flags,
ABI, initramfs tool selection, direct and dynamic CONFIG consumers.
Real Airoha/an7581-configured source: tools/flock compiles successfully, runtime
changes keep .built unchanged, PAX compression/delete/restore keeps nanosecond
stamp and performs no compiler command, source mutation produces a key miss
and actual cold recompilation. Real kernel-headers make expands stamp paths,
Linux version, architecture and files paths unchanged by runtime overlay edits.
This is real host-tool validation, NOT a full GCC/firmware build. Dummy toolchain
layout directories satisfy archive layout tests only. CI timing/GCC warm reuse
still require separately authorized builds. No push, dispatch or remote writes.

Evidence logs outside repositories:
/root/w1700k-cache-review/v5-host-validation.log
/root/w1700k-cache-review/v5-immortal-host-validation.log
