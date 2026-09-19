# ARM64 Debian builder

The workflow builds this small context, inspects the local image ID and runs that
exact ID with explicit `sleep infinity`. The image default is also sleep infinity.
There are no preseeded source, staging or compiler caches. Root execution and all
existing cache/profile/artifact mounts are preserved.

Base: official Debian trixie-slim linux/arm64 platform manifest pinned in Dockerfile.
Go: official go.dev ARM64 1.26.8 archive, SHA-256 verified before extraction to
`/usr/lib/go`; this is the external bootstrap, not a replacement for feed-built Go.
Apt packages deliberately receive official trixie security updates; see
`tests/CACHE_KEY_REVIEW.md` for package/content identity rather than Docker build ID.

## LLVM boundary

Official OpenWrt/ImmortalWrt `toolchain/Config.in` selects host LLVM only for
`BPF_TOOLCHAIN_HOST`; the default is prebuilt where available, otherwise
`BPF_TOOLCHAIN_BUILD_LLVM` (selects USE_LLVM_BUILD when NEED_BPF_TOOLCHAIN).
`include/bpf.mk` host mode requires clang >=12 plus llc, llvm-dis, opt and
llvm-strip, optionally under BPF_TOOLCHAIN_HOST_PATH. Installing clang alone
would not satisfy it. This lean image does not install any of them.

The local profile has no host-LLVM override. An existing prepared official
ARM64 profile selected BPF_TOOLCHAIN_BUILD_LLVM, not host LLVM; that historical
configuration is not proof of today's rolling feeds. The production workflow
checks the actual final `.config` immediately after defconfig and stops before
download if USE_LLVM_HOST=y. It does not silently change firmware configuration.
If future input selects host LLVM, review the recipe and install/test the complete
LLVM tool set before removing that gate. Full current configuration/compilation
has deliberately not been run under the local no-compilation authorization.

## Non-compiling smoke

`bash /builder-context/smoke.sh` inside the image verifies empty source, commands,
headers, Python/Perl modules, Go version/environment/tool versions, Git and archive
primitives. It compiles no code and proves neither final compiler compatibility
nor firmware/device correctness. `tests/test_builder_image.py` covers workflow
failure boundaries and fingerprint invalidation; real-container evidence is kept
outside the repository under `/root/cleanup-preserved/`; temporary project-tests
directories and task-specific images are removed after validation.
