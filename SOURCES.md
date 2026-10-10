# 补丁来源

基于 [OpenWrt 官方 main](https://github.com/openwrt/openwrt) 及官方 feeds，使用本仓库的 Debian Dockerfile 构建。Realtek PHY 驱动与配套固件沿用官方实现。

## 补丁清单

路径相对于 `user/default/`。`tree/` 按源码目录结构注入并保留目标目录所有权；内核与软件包补丁按各自构建顺序应用。

| 文件 | 用途与来源 |
| --- | --- |
| `tree/target/linux/airoha/patches-6.18/745-*` | E2 PCS RX 校准，来源 [A] |
| `tree/target/linux/airoha/patches-6.18/746-*` | MDIO 扫描前解除 PHY 复位，来源 [A] |
| `tree/target/linux/airoha/patches-6.18/940-*`、`patches/002-w1700k-cpufreq-resources.patch` | CPUFreq 兼容与设备树资源，来源 [B]；保留官方 attach_list、0–14 状态、500–1200 MHz 及调频策略 |
| `tree/package/kernel/mt76/patches/911-*` | 功率变更时刷新固件限制，适配 OpenW1700k 的 `0011-refresh-power-limits-on-txpower-changes`；SKU 启用沿用官方实现 |
| `patches/610-w1700k-power-30.patch` | CN/US 功率及频段定制，合并本项目配置与 [A] 的 US 高频段、6 GHz 设置；在官方 regdb 500 后应用 |
| `tree/package/network/utils/iwinfo/patches/999-*` | 按当前频率展示功率列表，来源 [A] |
| `patches/920-wifi-non-mlo-ap-txpower.patch` | 本项目实现：非 MLO AP 按 BSS 设置功率，适用范围见下文 |
| `patches/998-single-wiphy.patch` | single-wiphy 多射频设备的 LuCI 信道分析适配，作者 Gilly1970 |

来源提交：

- [A] [OpenWRT-fanboy/OpenW1700k `bce05fa86b22`](https://github.com/OpenWRT-fanboy/OpenW1700k/commit/bce05fa86b222741d8afcef2e5468a9481679041)
- [B] [OpenWRT-fanboy/OpenW1700k `972634e64d19`](https://github.com/OpenWRT-fanboy/OpenW1700k/commit/972634e64d19cba0095b662a0bfd9561ebef635c)

## 非 MLO AP 功率

`920` 由 `custom.sh` 在源码根目录应用，通过私有 hostapd 元数据在 `bss_add` 后设置功率。功率变更沿用重启路径；失败记录日志并通知，不等同于 netifd 确认成功。

适用于共享 PHY 上所有活动 radio 均为非 MLO AP 的配置。混用 MLO 或非 AP 模式时，其他 radio 的 PHY 全局设置仍可能覆盖功率；不提供 MLO 按链路控制。接口初始化取消沿用官方实现。

## 维护原则

- 官方为主，只保留必要兼容修复和既定参数定制，不批量导入 fork 补丁。
- 新补丁先核对来源、适用范围及官方实现；官方吸收后验证并移除重复内容。必要补丁应用失败即停止构建。
- 保留中文 LuCI、Aurora、专属应用、WOL、ttyd、访问与无线设置，以及启动绿灯、故障红灯、运行白灯。
- NAND、网络栈与卸载机制沿用官方；旧网桥脚本仅清理遗留配置，不恢复额外驱动增强或 vermagic 覆盖。
- 源码与隔离测试不代替实机射频验证；滚动更新继续检查补丁兼容性。
