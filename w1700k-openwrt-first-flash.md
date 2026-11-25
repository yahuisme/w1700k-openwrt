# W1700K OpenWrt 首次刷机 / 完整重装（含救砖）

首次刷机、救砖重装或旧版迁移时，先在原厂 U-Boot 中刷入 Chainloader，再启动 Installer 安装系统。无法进入原厂 U-Boot 时，本教程不适用。

> 仅适用于 Quantum Fiber / Gemtek W1700K。首次刷机和完整重装都会清除原有系统与配置。刷写前确认型号，将本机原厂数据备份到电脑；刷写期间不要断电。

## 1. 准备

- Windows 电脑、网线、3.3V USB-TTL
- [PuTTY 中文版](https://github.com/larryli/putty)：串口终端
- [Tftpd64 官方下载](https://github.com/PJO2/tftpd64/releases/)：TFTP 服务

从 [OpenWrt Releases](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-OpenWrt-) 下载同一次发布的两个文件。`C:\tftp` 只放这次下载的两个文件：

```text
openwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb
openwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb
```

已安装修正版 Chainloader 且 UBI2 兼容版本为 2.0 时，日常升级用同发行版的 `openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb`，无需重刷 Chainloader。升级镜像不能替代 Installer。

## 2. 连接与设置

### 接线

路由器保持断电。网口朝向自己时，UART 从左到右：

```text
1    2     3     4     5
TX   GND   VCC   N/A   RX
```

USB-TTL 只接以下三根线：

```text
W1700K TX  → TTL RX
W1700K GND → TTL GND
W1700K RX  → TTL TX
```

**不接 VCC。必须使用 3.3V TTL，不能使用 RS-232。**

电脑用网线直连 W1700K **黄色 1G LAN 口**。

### PuTTY

COM 端口见 Windows「设备管理器 → 端口」。

```text
连接类型：串口（Serial）
串口：实际 COM 号，例如 COM3
速度：115200
数据位：8
停止位：1
校验：无（None）
流控：无（None）
```

打开串口，路由器暂不通电。

### 电脑有线网卡

```text
IP 地址：  192.168.1.10
子网掩码： 255.255.255.0
网关：     留空
DNS：      留空
```

暂时关闭 Wi-Fi、VPN 和其他虚拟网卡。

### Tftpd64

- `Current Directory`：`C:\tftp`
- `Server interfaces`：`192.168.1.10`
- 防火墙提示：允许 Tftpd64 通过专用网络

## 3. 刷入系统

### 写入 Chainloader

**以下命令只在原厂 U-Boot 中执行，不能在替换版 U-Boot 中执行。认不出原厂提示符就停止。**

通电，看到第一处 `Hit any key to stop autoboot` 时按 Enter 或空格，停在原厂 U-Boot 后立即下载 Chainloader：

```text
setenv serverip 192.168.1.10 ; setenv ipaddr 192.168.1.1 ; tftpboot 0x89000000 openwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb
```

继续前确认：

- TFTP 下载成功，文件完整加载到 `0x89000000`。
- 文件大小不超过 `0x100000` 字节。

**下载失败时不要擦写。** 下载成功后，用 `printenv bootcmd bootcmd_orig` 查看并保存启动参数。已有 `bootcmd_orig` 就保留原值；只有确认 `bootcmd` 仍是原厂值且没有备份时，才用 `setenv bootcmd_orig "$bootcmd"` 备份。

无论以前是否刷过，均逐行执行。**每步确认成功后再继续；如有报错，停在原厂 U-Boot，不要重启，保留串口日志。**

```text
setenv one flash read 0x600000 0x100000 \$loadaddr
setenv two "; bootm"
setenv bootcmd "$one$two"
saveenv
flash erase 0x600000 0x100000
flash write 0x600000 0x100000 0x89000000
reset
```

### 启动 Installer

重启后进入 Chainloader 菜单。

确认 Tftpd64 正在运行且目录中有 Installer，再选择：

```text
Boot installer via TFTP.
```

在 Tftpd64 核对请求名，默认是 `openwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb`。如仍请求旧名称，把本次下载的 Installer 复制一份并改成请求名，再选一次菜单；不要使用之前下载的文件。

确认加载的是本次下载的 Installer，再在串口处理以下提示：

```text
Initialize/reinstall UBI2 on mtd2 and erase its contents? (yes/no)
```

- 输入 `yes` 并按 Enter：开始安装。
- 输入 `no`：取消。

等待以下提示，并让设备自动重启：

```text
[installer] Install complete. Rebooting...
```

> 进入命令行不代表安装完成，短暂无输出时不要断电。报错或未自动重启时，保留完整串口日志，不要盲目重刷。

## 4. 登录后台

Installer 已装好完整系统，无需再刷升级镜像。

1. 电脑保持连接黄色 1G LAN 口。
2. 将有线网卡恢复为自动获取 IP 和 DNS。
3. 等待重新获取地址，打开 `192.168.8.1`。

- 用户名：`root`
- 初始密码：留空

登录后先设置管理员密码，再配置上网和无线。

`192.168.1.1` 用于 U-Boot 下载；正式系统默认地址为 `192.168.8.1`。

## 遇到问题

**串口无输出**

检查 COM 端口、`115200` 速率、流控 `None`，以及 TX/RX 交叉连接和 GND。

**TFTP 失败**

检查电脑 IP、Tftpd64 网卡、目录、完整文件名和防火墙，观察是否收到文件请求。

**后台打不开**

- 确认安装完成且已重启，电脑已恢复自动获取地址。
- 用 `ipconfig` 查看直连网卡通过 DHCP 获得的 IPv4 默认网关，先试该地址。默认设置未生效时，LAN 可能仍用 `192.168.1.1`。
- 没拿到地址就重插网线；仍不通时，查看 TTL 串口启动日志，确认已进入正式系统而非 Installer 或 Recovery。可在正式系统串口运行 `ip -4 addr show br-lan` 查看 LAN 地址。不要仅因网页打不开就重刷。

**提示原厂数据损坏**

使用本设备原有备份恢复，不要使用其他设备的数据。

[返回项目首页](README.md) · [OpenWrt 设备资料](https://openwrt.org/toh/gemtek/mxf-w1700k)
