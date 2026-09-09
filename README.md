# AI 协力构建的 Quantum Fiber / Gemtek W1700K OpenWrt 固件

适用于 **Quantum Fiber / Gemtek W1700K** 路由器的定制 OpenWrt 固件构建项目。

基于 [W1700K OpenWrt Builds](https://github.com/w1700k/builds) 构建框架，源码基线为 [OpenW1700k](https://github.com/OpenWRT-fanboy/OpenW1700k)（ubi2 / ubi2-oc 分支）。

> ⚠️ **仅适用于 Quantum Fiber / Gemtek W1700K，请勿刷入其他型号设备。**

---

## ✨ 主要特性

- 🌐 默认中文 LuCI 界面
- 🎨 默认 Aurora 主题
- 📦 内置定制专属全中文汉化应用
- 🌡️ LuCI 首页增加温度及风扇转速显示
- 🚀 集成 NPU 硬件加速
- ⚡ 底层网络优化
- 🛡️ 纯净系统 + 集成最新优化补丁
- 📡 WiFi 稳定性修复 + 解除功率限制

---

## 🧩 预装应用

精简纯净原则，仅内置硬件深度适配与基础网络管理应用，源码由专属源 [yahuisme/packages](https://github.com/yahuisme/packages) 定制维护并全中文支持：

| 插件 | 功能说明 |
| :--- | :--- |
| [`luci-app-airoha-npu`](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-npu) | Airoha NPU 状态监控与 SoC 频率控制 |
| [`luci-app-airoha-fancontrol`](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-fancontrol) | 动态温控曲线与四线 PWM 风扇调速 |
| [`luci-app-airoha-flowsense`](https://github.com/yahuisme/packages/tree/main/luci-app-airoha-flowsense) | PPE 硬件流控与加速状态实时监控 |
| [`luci-app-mlo`](https://github.com/yahuisme/packages/tree/main/luci-app-mlo) | Wi-Fi 7 多链路聚合（MLO）控制面板 |
| [`luci-app-wifi7`](https://github.com/yahuisme/packages/tree/main/luci-app-wifi7) | Wi-Fi 7 状态与高级射频管理 |
| `luci-app-usteer` | AP / Mesh 弱信号剔除与智能漫游辅助 |
| `luci-app-wol` | 网络唤醒（Wake-on-LAN） |
| `luci-app-ttyd` | 网页终端控制台 |

---

## 📦 固件版本

| 固件 | 说明 |
| --- | --- |
| `ubi2` | 常规版本，使用标准 CPU 工作参数 |
| `ubi2-oc` | 超频版本，使用项目提供的超频配置 |

---

## 默认访问

- 管理地址：`192.168.8.1`
- 管理密码：无
- Wi-Fi SSID：`W1700K`
- Wi-Fi 密码：`12345678`

---

## 📡 默认无线配置

| 项目 | 2.4 GHz | 5 GHz | 6 GHz |
| --- | --- | --- | --- |
| 状态 | 开启 | 开启 | **关闭** |
| 区域 | US | US | US |
| 信道 | 1 | 36 | 37 |
| 频宽 / 模式 | Wi‑Fi 7（EHT20） | Wi‑Fi 7（EHT160） | Wi‑Fi 7（EHT320） |
| SSID | `W1700K` | `W1700K` | `W1700K-6G` |
| 加密 | WPA2-PSK | WPA2-PSK | WPA3-SAE |
| 密码 | `12345678` | `12345678` | `12345678` |
| 发射功率 | 23 dBm | 25 dBm | 25 dBm |

---

## 🌡️ 温度监控

LuCI 状态首页显示 CPU、主板、10G WAN/LAN PHY、2.4/5/6 GHz WiFi 温度及风扇转速/占空比，随温度区间变色提示。

---

## 🔄 自动构建

GitHub Actions 每日自动构建：

```text
W1700K-OpenWrt_<构建时间>_r<版本号>
W1700K-OpenWrt-OC_<构建时间>_r<版本号>
```
