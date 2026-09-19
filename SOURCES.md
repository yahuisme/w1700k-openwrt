# 补丁来源

基于 [OpenWrt 官方 main](https://github.com/openwrt/openwrt) 及官方 feeds。构建环境使用本仓库维护的官方 Debian Dockerfile，不预置固件源码或工具链。

## 本地补丁

以下路径相对于 `user/default/`。`tree/` 按构建目录结构注入，内核补丁沿用官方补丁应用顺序。

| 文件 | 用途与来源 |
| --- | --- |
| `tree/target/linux/airoha/patches-6.18/745-*` | 扩展 E2 PCS RX 校准，来源 OpenWRT-fanboy/OpenW1700k `bce05fa86b222741d8afcef2e5468a9481679041` |
| `tree/target/linux/airoha/patches-6.18/746-*` | 在 MDIO 识别前解除外部 PHY 复位，来源同上 |
| `tree/target/linux/generic/hack-6.18/999-*`、`tree/target/linux/generic/files/drivers/net/phy/rtl8261ce/` | RTL8261C/CE 驱动及内核接入，支持 PHY ID `0x001cc890` 的硬件变体，来源同上，保留原许可证 |
| `patches/001-w1700k-platform.patch` | RTL8261CE 内核模块包定义，包选择统一放在 `config.diff` |
| `tree/target/linux/airoha/patches-6.18/940-*`、`patches/002-w1700k-cpufreq-resources.patch` | 标准 CPUFreq 兼容，来源 OpenW1700k `972634e64d19cba0095b662a0bfd9561ebef635c` 的 940 C 代码及 W1700K 设备树资源；不重复引入 Kconfig，保留官方 attach_list、0–14 状态、500–1200 MHz 与调频策略，不超频 |
| `tree/package/kernel/mt76/patches/910-*`、`911-*` | 无线固件功率限制启用与刷新，沿用本项目 ImmortalWrt 侧对 OpenW1700k `0010-enable-firmware-txpower-limit`、`0011-refresh-power-limits-on-txpower-changes` 的适配；mt76 本体保持官方版本 |
| `tree/package/firmware/wireless-regdb/patches/555-*` | US 高频段及 6 GHz 区域配置，来源上述 `bce05fa...`，作为 610 补丁前置 |
| `patches/610-w1700k-cn-us-power-30.patch` | 本项目 CN/US 30 dBm 功率定制 |
| `tree/package/network/utils/iwinfo/patches/999-*` | 分离 wiphy 与当前频率的功率列表展示，来源上述 `bce05fa...` |
| `patches/998-single-wiphy.patch` | single-wiphy 无线设备的 LuCI 信道分析适配，源自 Gilly1970 |

## 维护原则

- 非必要不加补丁；官方已有功能和特性以官方实现为准。
- 不在构建时整批拉取 fork 补丁；新修复先核对来源、适用性及官方是否已包含。
- 官方吸收后验证并移除本地重复补丁；必要补丁应用失败必须停止构建。
- NAND 保持官方 50 MHz，不恢复 OC、额外网桥 flowtable、GRO/NPU 扩展或 vermagic 覆盖。
- 保留中文 LuCI、Aurora、专属应用、WOL、ttyd、Usteer、既定访问与无线设置，以及启动绿灯、故障红灯、运行白灯。
- `90-bridge-hw-offload` 仅清理旧配置遗留，不注入网桥卸载功能；运行行为由官方 fw4 与网络栈负责。

当前方案已通过用户实机测试，原失联问题已解决。该反馈不等于逐项硬件机制或射频功率测量；后续滚动更新仍需核对补丁兼容性。
