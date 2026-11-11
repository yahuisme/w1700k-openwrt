# W1700K OpenWrt / ImmortalWrt

适用于 Quantum Fiber / Gemtek W1700K，提供 OpenWrt 与 ImmortalWrt 两种系统的首次安装和日常升级固件。

- [OpenWrt 官方 main](https://github.com/openwrt/openwrt)
- [ImmortalWrt 官方 master](https://github.com/immortalwrt/immortalwrt)

## 固件下载

请先选定发行版，再在对应标签前缀下下载；不要把两个发行版或不同 Release 的文件混用。

| 发行版 | Release 标签前缀 | 下载 |
| --- | --- | --- |
| OpenWrt | `W1700K-OpenWrt-r<revision>-YY.MM.DD_HH.MM.SS` | [OpenWrt Releases](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-OpenWrt-) |
| ImmortalWrt | `W1700K-ImmortalWrt-r<revision>-YY.MM.DD_HH.MM.SS` | [ImmortalWrt Releases](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-ImmortalWrt-) |

每个发行版的 Release 都包含以下三个后缀；完整文件名中的发行版前缀必须与所选 Release 一致：

| 文件后缀 | 用途 |
| --- | --- |
| `chainload-uboot.itb` | 原厂 U-Boot 首次写入 Chainloader |
| `initramfs-installer.itb` | 初始化或重建 UBI2，并安装同次构建的完整系统 |
| `squashfs-sysupgrade.itb` | 已有兼容 UBI2 系统的日常升级 |

**首次安装或重建 UBI2 布局：**

- [OpenWrt 刷机教程](w1700k-openwrt-first-flash.md)
- [ImmortalWrt 刷机教程](w1700k-immortalwrt-first-flash.md)

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

以下设置在首次启动或不保留配置升级时生效，两个发行版的默认值相同。

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

1. 从所选发行版的对应标签下载 `squashfs-sysupgrade.itb`。
2. 进入 **系统 → 备份 / 升级**，上传该发行版的日常升级固件，取消勾选“保留配置”。
3. 校验通过后升级，等待重启，期间不要断电。

已有兼容 UBI2 系统时，不要运行 `initramfs-installer.itb`，也无需重新初始化 UBI2。

## 构建与发布

每隔3天自动构建；也可手动运行 [Actions](https://github.com/yahuisme/w1700k-openwrt/actions/workflows/W1700K.yaml)。每次分别拉取 OpenWrt 官方 main 和 ImmortalWrt 官方 master 构建，一次生成两个独立 Release，并各自只保留最新一版。

[补丁说明与来源](https://github.com/yahuisme/packages/tree/main/w1700k-patches/SOURCES.md)
