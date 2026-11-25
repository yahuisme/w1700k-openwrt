# W1700K OpenWrt / ImmortalWrt

适用于 Quantum Fiber / Gemtek W1700K 的 OpenWrt 和 ImmortalWrt 固件。

- [OpenWrt 官方 main](https://github.com/openwrt/openwrt/tree/main)
- [ImmortalWrt 官方 master](https://github.com/immortalwrt/immortalwrt/tree/master)

## 固件下载

先选发行版，再从对应 Release 下载。不要混用不同发行版或不同 Release 的镜像。

| 发行版 | Release 标签前缀 | 下载 |
| --- | --- | --- |
| OpenWrt | `W1700K-OpenWrt-r<revision>-YY.MM.DD_HH.MM.SS` | [OpenWrt Releases](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-OpenWrt-) |
| ImmortalWrt | `W1700K-ImmortalWrt-r<revision>-YY.MM.DD_HH.MM.SS` | [ImmortalWrt Releases](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-ImmortalWrt-) |

每个 Release 提供三个镜像，按文件名后缀区分用途：

| 文件后缀 | 用途 |
| --- | --- |
| `chainload-uboot.itb` | 从原厂 U-Boot 写入 Chainloader |
| `initramfs-installer.itb` | 由 Chainloader 启动，初始化或重建 UBI2 并安装完整系统 |
| `squashfs-sysupgrade.itb` | 同发行版日常升级 |

## 首次刷机 / 完整重装

首次刷机，或因救砖、旧版迁移需要完整重装时，从原厂 AXON U-Boot 写入 Chainloader，再启动 Installer 安装系统。两个镜像须来自同一 Release。

**此流程会清除原有系统与配置。无法进入原厂 AXON U-Boot 时，不适用以下教程。**

- [OpenWrt 刷机教程](w1700k-openwrt-first-flash.md)
- [ImmortalWrt 刷机教程](w1700k-immortalwrt-first-flash.md)

## 日常升级

仅适用于已安装修正版 Chainloader、兼容版本为 2.0 的同发行版 UBI2 系统，无需重刷 Chainloader。旧版或布局不明时，按对应教程完整重装。

1. 备份当前配置，下载同发行版的 `squashfs-sysupgrade.itb`。
2. 在 **系统 → 备份 / 升级** 上传镜像。建议取消勾选「保留配置」，这会清除现有设置。
3. 校验通过后再升级，等待设备重启，期间不要断电。校验失败时不要强制刷写。

## 特性

- 中文 LuCI、Aurora 主题
- 首页温度与风扇状态
- 官方 NPU/PPE 硬件加速
- 发射功率最高可配置为 30 dBm，不代表实测输出

## 预装应用

| 应用 | 功能 |
| --- | --- |
| [Airoha SoC](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-npu) | SoC 与 NPU 状态 |
| [风扇控制](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-fancontrol) | 温控曲线与风扇调速 |
| [FlowSense](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-flowsense) | 流量与加速管理 |
| [WiFi 7](https://github.com/yahuisme/packages/tree/main/luci-app-wifi7) | 无线射频与 MLO 管理 |
| 网络唤醒 | 唤醒局域网设备 |
| 网页终端 | 浏览器终端访问 |

## Aurora 更新

Aurora 主题、配置应用和中文包可通过作者的签名 APK 源更新，在 **系统 → 软件包** 刷新列表即可。默认使用侧边栏和小圆角，保留配置升级时不会覆盖已有设置。

## 默认设置

两个发行版使用相同默认值，首次启动或不保留配置升级后生效。

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

## 构建与发布

每天香港时间 00:00 自动构建，也可手动运行 [Actions](https://github.com/yahuisme/w1700k-openwrt/actions/workflows/W1700K.yaml)。两个发行版各自构建和发布，只保留各自最新一版正式固件。

[补丁说明与来源](user/w1700k-patches/SOURCES.md)
