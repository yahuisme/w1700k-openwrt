# Source and minimal local delta

Builds follow `https://github.com/openwrt/openwrt` **main**, including its official feeds and package source revisions. No fork distfeeds, kernel vermagic override, dynamic fork patch download, bridge-flowtable/GRO/NPU enhancement or OC extension is imported. The existing ARM builder image supplies host tools only: source preparation performs `git reset --hard` and `git clean -ffdx` before feeds/customization, removing preseeded tracked and untracked build inputs.

## Checked-in additions

Paths under `user/default/tree/` mirror their buildroot destination; `custom.sh` copies these before `make defconfig`. Kernel patches are applied by OpenWrt's normal generic backport → pending → hack → target chain, not directly against pristine Linux.

| Local input | Origin / purpose |
| --- | --- |
| `tree/target/linux/airoha/patches-6.18/745-*` | OpenWRT-fanboy/OpenW1700k `bce05fa86b222741d8afcef2e5468a9481679041`: include E2 in manual PCS RX calibration |
| `tree/target/linux/airoha/patches-6.18/746-*` | Same donor: deassert external PHY reset before MDIO identification |
| `tree/target/linux/generic/{hack-6.18/999-*,files/drivers/net/phy/rtl8261ce/*}` | Same donor: external RTL8261C/CE PHY model `0x001cc890`, including vendor register sequences and hwmon; retain source licenses |
| `tree/target/linux/airoha/patches-6.18/940-*`, `patches/002-w1700k-cpufreq-resources.patch` | Standard CPUFreq compatibility: original 940 C hunks from OpenW1700k `972634e64d19cba0095b662a0bfd9561ebef635c`, omitting only duplicate Kconfig; W1700K-only DT resources. Official attach_list, state 0–14, 500–1200 MHz and governor unchanged; no OC |
| `patches/001-w1700k-platform.patch` | Minimal local integration of RTL8261CE kmod recipe; package selection explicit in config.diff |
| `tree/package/kernel/mt76/patches/910-*`, `911-*` | Existing yahuisme/w1700k-immortalwrt local rebases of donor `0010-enable-firmware-txpower-limit` and `0011-refresh-power-limits-on-txpower-changes`; official mt76 package retained |
| `tree/package/firmware/wireless-regdb/patches/555-*` | Same donor: existing US upper-5GHz/6GHz regulatory settings, prerequisite of retained 610 patch |
| `patches/610-w1700k-cn-us-power-30.patch` | Existing user CN/US 30dBm delta, retained unchanged |
| `tree/package/network/utils/iwinfo/patches/999-*` | Same donor: split-wiphy, current-frequency power-list reporting |
| `patches/998-single-wiphy.patch` | Existing Gilly1970 LuCI channel-analysis netdev resolution fix, retained unchanged |

The CPUFreq port is a local candidate, not hardware-validated: initial genpd level-0 vote synchronization and PLL failure/readback remain review gates. Do not infer runtime correctness from patch applicability.

NAND remains at official 50 MHz: no reproduced failure justifies the inherited 33 MHz downclock. RTL8261CE supports the W1700K board variant; this physical unit’s PHY has not been identified. Existing boot green / failsafe red / running white LED aliases are retained.

30dBm configuration support is not measured radiated power or permission to exceed local regulations. Retaining cold-boot fixes is not proof the reported device outage is fixed.

## User features and dependency boundary

Chinese LuCI, Aurora, all previously selected packages, default access/Wi-Fi settings and the temperature/fan overview remain. Four `yahuisme/packages` apps are explicitly selected: WiFi7, Airoha NPU, FlowSense and fancontrol. Chinese language selection resolves all four translation packages. WOL, the ttyd web terminal and Usteer remain selected with their translations and runtime dependencies. Frequency menus/forms are hidden when official CPUFreq/Devfreq interfaces are unavailable; application retention does not require restoring fork kernel extensions. Kernel/firmware support comes from official device defaults plus the explicit RTL8261CE package, not from merely cloning those apps.

The prior image's nine overview includes are accounted for by the eight official LuCI includes plus the existing `15_temperature.js` overlay. No additional fork overview module was identified. Fancontrol runs S99fan after official S99airoha_fan; both write hardware curves at boot, with the user's fan service last. Device service ownership/reload behavior remains a hardware validation item. FlowSense's standard routing-offload controls remain; official fw4 does not imply donor native bridge flowtable/GRO feature equivalence.

`90-bridge-hw-offload` is only retained-config cleanup, not an offload feature injector. Static br_netfilter settings retain existing user defaults. Removed fork features are not silently reintroduced for UI capability parity.

## Local non-build verification

Migration baseline tested: official `b6ba4e9142b7e926dd3822beffdae26de34da98e`, Linux 6.18.52, mt76 `be5ce7910521492d4a2e4ce7ee3843680a46c047`, iwinfo `66bdd1a071895d91babc9b9228bb84626bbce226`, wireless-regdb 2026.05.30. Clean full official source + feeds + custom.sh were exercised, with an existing host Kconfig `conf` binary for real `make defconfig` (no compilation). All originally requested `CONFIG_PACKAGE_*=y` selections survived. Full kernel patch chain and package patches were applied to real source trees without compiling.

Full build, image installed-package verification, cold boot, PHY/link, DHCP/LAN and radio-power measurements are not covered by these checks. Snapshot package repositories move independently; no ABI override is shipped to mask incompatible later kmods.
