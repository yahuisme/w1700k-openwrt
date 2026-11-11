# W1700K OpenWrt

基于 [OpenWrt 官方 snapshot](https://github.com/openwrt/openwrt)。

适用于 Quantum Fiber / Gemtek W1700K，提供首次安装与日常升级固件。

## 固件下载

前往 [Releases](https://github.com/yahuisme/w1700k-openwrt/releases) 下载。同一次发布包含：

| 文件 | 用途 |
| --- | --- |
| `openwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb` | 原厂 U-Boot 首次写入 Chainloader |
| `openwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb` | 初始化或重建 UBI2，并安装完整系统 |
| `openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb` | 已有兼容 UBI2 系统的日常升级 |

**首次安装或重建 UBI2 布局：[W1700K 刷机教程](w1700k-first-flash.md)。**

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
| 网络唤醒 | 唤醒局域网设备 |
| 网页终端 | 浏览器终端访问 |

## Aurora 更新

Aurora 主题、配置应用及中文包通过官方签名 APK 软件源预装，可在 **系统 → 软件包** 刷新列表并更新。默认使用侧边栏和小圆角，保留配置升级不覆盖已有设置。

## 默认设置

以下设置在首次启动或不保留配置升级时生效。

- 管理地址：`192.168.8.1`
- 用户名：`root`
- 管理密码：无
- Wi-Fi 密码：`12345678`

区域为 US，2.4/5 GHz 使用 WPA2-PSK，6 GHz 使用 WPA3-SAE。

| 项目 | 2.4 GHz | 5 GHz | 6 GHz |
| --- | --- | --- | --- |
| 状态 | 开启 | 开启 | 关闭 |
| SSID | `W1700K` | `W1700K` | `W1700K-6G` |
| 信道 | 1 | 36 | 37 |
| 模式 | EHT20 | EHT160 | EHT320 |
| 配置功率 | 23 dBm | 25 dBm | 25 dBm |

## 日常升级

1. 进入 **系统 → 备份 / 升级**。
2. 上传下载表中的日常升级固件，取消勾选“保留配置”。
3. 校验通过后升级，等待重启，期间不要断电。

无需重新运行 UBI2 Installer。

## 构建与发布

每隔3天自动构建；也可手动运行 [Actions](https://github.com/yahuisme/w1700k-openwrt/actions/workflows/W1700K.yaml)。每次拉取官方最新源码构建，保留最新一版。

[补丁说明与来源](https://github.com/yahuisme/packages/tree/main/w1700k-patches/SOURCES.md)
