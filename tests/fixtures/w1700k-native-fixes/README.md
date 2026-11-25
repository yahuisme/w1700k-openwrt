# Exact native-fix source fixtures

Source-only archive, deterministic gzip/tar; every member and the archive itself are SHA256-bound in `manifest.json`. No compiled binaries or generated Kconfig are included.

- OpenWrt core `fb742de8e5126809fddf16fa2b5e82b016be0edb`, Linux `v6.18.64`.
- ImmortalWrt core `73bc086a62f951d96e5d7404f04c4d73e141cad2`, Linux `v6.18.60`.
- mt76 `0936617dc529ff9da0385221d3fa6de732231177`: complete files reached by every selected native and local mt76 patch. Other mt76 files are not reconstructed or compiled.
- Original native mt76 patches, full mt76 recipes, full crypto package definitions, full native reset patch, and all ordered native clock-file touching patch sections. The Linux clock base file is complete; unrelated files in multi-file native kernel patches are deliberately excluded.
- Unchanged official mt76 commit patches `a801adb009f70cde062de22976d4d6c7dc13daa8`, `1a519350810083fce4ae1ab00ff58f02b716f6e0`, `6145ff0b02f315f8e80af01345cb3bd6caa62b84`. Production payloads must match them byte-for-byte.

Five fixed-function hashes are derived from those exact official commit sources. For `mt76_rx_release_amsdu`, the selected tree lacks independent earlier station/WCID-lifetime commit `6a2f14547f724e6c4f882cfb44e81f04e6e82357`; the test normalizes only that exact prologue to compare the complete remaining function, without importing it or claiming that existing station-removal risk is fixed. Each was compared to later mt76 `acb7b1c85c22400e1b737ce6efc36d2519482ebd` and is identical there. Subsequent A-MSDU marking/replay and PN changes address independent existing issues; they are not prerequisites for these three backports and are not imported here.

`tests/test_native_fixes.py` executes the default production preflight/guards/native repairs/overlay-copy block, then replays every mt76 predecessor in order and rebuilds the full reached clock file using zero fuzz. Its Python dataflow models are admitted only after exact official function identity checks and include source mutation negatives. They do not execute kernel C, DMA, packet IO, or router hardware. Final-config and device-manifest acceptance tests use labeled non-firmware release fixtures and the real staging shell.

To refresh: resolve each selected recipe/core, check upstream absorption and successors, retrieve original blobs at exact refs, regenerate member/archive hashes and independently derive fixed-function hashes from formal upstream sources. Do not change hashes merely to make an incompatible replay pass; preserve historical fixtures when they remain valid controls.
