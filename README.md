# W1700K OpenWrt

基于 [OpenWrt 官方 snapshot](https://github.com/openwrt/openwrt)，仅构建标准版。

适用于已完成 UBI2 安装的 Quantum Fiber / Gemtek W1700K。升级镜像见 [Releases](https://github.com/yahuisme/w1700k-openwrt/releases)。

首次安装或需要重建 UBI2 布局，请参阅 [W1700K UBI2 Installer](https://github.com/yahuisme/w1700k-ubi2-installer)，按教程拆机连接 USB-TTL，刷入 U-Boot Chainloader 并运行安装器。已完成 UBI2 安装的设备无需重复操作。

## 特性

- 中文 LuCI、Aurora 主题
- 首页温度与风扇状态
- 官方 NPU/PPE 硬件加速
- 30 dBm 功率配置支持

## 预装应用

| 应用 | 功能 |
| --- | --- |
| [Airoha SoC](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-npu) | SoC 与 NPU 状态 |
| [风扇控制](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-fancontrol) | 温控曲线与风扇调速 |
| [FlowSense](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-flowsense) | 流量与加速管理 |
| [WiFi7](https://github.com/yahuisme/packages/tree/main/luci-app-wifi7) | 无线射频与 MLO 管理 |
| 网络唤醒 | Wake-on-LAN |
| 终端 | 网页终端 |

## 默认访问

- 管理地址：`192.168.8.1`
- 管理密码：无
- Wi-Fi 密码：`12345678`

## 默认无线

区域为 US，2.4/5 GHz 使用 WPA2-PSK，6 GHz 使用 WPA3-SAE。

| 项目 | 2.4 GHz | 5 GHz | 6 GHz |
| --- | --- | --- | --- |
| 状态 | 开启 | 开启 | 关闭 |
| SSID | `W1700K` | `W1700K` | `W1700K-6G` |
| 信道 | 1 | 36 | 37 |
| 模式 | EHT20 | EHT160 | EHT320 |
| 功率 | 23 dBm | 25 dBm | 25 dBm |

## 构建

每日香港时间 12:00 自动构建，也可手动运行 Actions。仅发布 `sysupgrade.itb`。

[补丁来源](SOURCES.md)
