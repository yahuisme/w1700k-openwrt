# AI 协力构建的 Quantum Fiber W1700K OpenWrt 固件

适用于 **Quantum Fiber W1700K** 路由器的定制 OpenWrt 固件构建项目。

本项目基于 [W1700K OpenWrt Builds](https://github.com/w1700k/builds) Fork，在原版固件基础上加入多项定制功能。

> ⚠️ **仅适用于 Quantum Fiber W1700K，请勿刷入其他型号设备。**

---

## ✨ 主要特性

- 🌐 CN LuCI 默认中文
- 🎨 内置 Aurora LuCI 主题为默认主题
- 🕐 系统时区：香港（UTC+8）
- 📡 默认开启 2.4 GHz / 5 GHz Wi-Fi
- 📡 默认不开启 6 GHz Wi-Fi
- 🌡️ LuCI 首页增加设备温度及风扇转速显示
- 🔄 每日自动构建最新固件
- 📦 提供 `ubi2` 和 `ubi2-oc` 两种版本

---

## 📦 固件版本

| 固件 | 说明 |
| --- | --- |
| `ubi2` | 常规版本，使用标准 CPU 工作参数 |
| `ubi2-oc` | 超频版本，使用项目提供的超频配置 |

一般情况下推荐使用 **`ubi2` 常规版本**。

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
| 发射功率 | 23 dBm | 23 dBm | 23 dBm |

---

## 🌡️ 温度监控

LuCI 状态首页增加「温度与风扇」信息：

- CPU 温度
- 主板 温度
- 10G WAN PHY 温度
- 10G LAN PHY 温度
- 2.4 GHz WiFi 温度
- 5 GHz WiFi 温度
- 6 GHz WiFi 温度
- 风扇转速及占空比

温度达到不同区间会自动变化不同颜色提示。

---

## 🔄 自动构建

GitHub Actions 每天 **香港时间 19:00** 自动构建：

```text
W1700K-ubi2
W1700K-ubi2-oc
