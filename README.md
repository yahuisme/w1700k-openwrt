# Quantum Fiber W1700K OpenWrt

适用于 **Quantum Fiber W1700K** 路由器的定制 OpenWrt 固件构建项目。

本项目基于 [w1700k/builds](https://github.com/w1700k/builds) 进行 Fork，并在原有固件基础上加入中文语言、Aurora 主题、默认无线配置以及温度监控等定制功能。

> **注意：本项目仅适用于 Quantum Fiber W1700K，请勿将固件刷入其他型号设备。**

---

## ✨ 主要特性

本项目目前包含以下基础定制：

- 🇨🇳 LuCI 默认中文
- 🎨 Aurora LuCI 主题
- ⭐ Aurora 设置为默认主题
- 🇭🇰 系统时区设置为香港时间
- 📡 默认开启 2.4 GHz Wi-Fi
- 📡 默认开启 5 GHz Wi-Fi
- 🇺🇸 无线区域设置为 US
- 📶 2.4 GHz 默认信道：1
- 📶 5 GHz 默认信道：36
- 📡 默认发射功率保持系统默认值
- 🔐 默认使用 WPA2-PSK
- 🔑 默认 Wi-Fi 密码：`12345678`
- 📶 默认 SSID：`W1700K`
- 🌡️ LuCI 首页增加设备温度及风扇转速显示
- 🔄 每天自动构建最新固件
- 🚀 Aurora 每次构建自动拉取最新版本
- 📦 当前主要构建 `ubi2` 固件

---
