# W1700K OpenWrt U-Boot 与首次安装教程

- **首次安装**：从原厂 U-Boot 开始，按以下四步操作。
- **重装系统**：仅确认已安装修正版 Chainloader（兼容版本 2.0）时，才可直接启动 Installer。
- **旧版或布局不明**：先按下文核对 Chainloader；旧布局必须先更换 Chainloader，再用 Installer 重建 UBI2。
- **日常升级**：已有修正版 Chainloader 和兼容版本 2.0 系统时，使用 [sysupgrade 固件](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-OpenWrt-)，不要运行 Installer。

> 仅适用于 Quantum Fiber / Gemtek W1700K。安装或重装会清除原有系统与配置。刷写前确认型号，并将本机原厂数据备份保存到电脑；刷写期间不要断电。

## 1. 准备

- Windows 电脑、网线、3.3V USB-TTL
- [PuTTY 中文版](https://github.com/larryli/putty)：串口终端
- [Tftpd64 官方下载](https://github.com/PJO2/tftpd64/releases/)：TFTP 服务

从 [OpenWrt Releases](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-OpenWrt-) 下载固件并放入 `C:\tftp`。首次安装或更换 Chainloader 时，下载同一次发布的两个文件；确认现有 Chainloader 已修正时，只需第二个：

```text
openwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb
openwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb
```

`openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb` 只用于同发行版日常升级，不能替代 Installer。

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

### 核对已安装的 Chainloader

首次安装请直接看下一节。重装时先通电，从串口的 Chainloader 菜单进入控制台，执行只读命令 `mtd list`。未自定义分区时，确认 `ubi` 范围是 `0x00700000`–`0x1be00000`，且 `reserved_bmt` 范围是 `0x1be00000`–`0x20000000`，才可跳到“启动 Installer”。无法进入控制台就按布局不明处理，不要继续重装。

菜单项 `Boot installer via TFTP.` 在旧版也存在；系统或 Installer 的分区表不能证明 Chainloader 已修正。

若范围不符或无法确认，**先不要运行 Installer 或强制 sysupgrade**。[上游分区修正 `ee771d3`](https://github.com/openwrt/openwrt/commit/ee771d3dd01c811d2a28eab09a700cefdafd05af) 要求更换旧 Chainloader 并重装。用串口重新通电，在进入替换版菜单前中断第一阶段的原厂 AXON U-Boot，再按下一节更换；若进不了或认不出原厂提示符，停止并保存完整串口日志，参考 [OpenWrt 设备资料](https://openwrt.org/toh/gemtek/mxf-w1700k#install_the_u-boot_chainloader)。

### 写入 Chainloader

**仅在确认 Chainloader 已修正时跳过本节。以下命令仅适用于原厂 AXON U-Boot，不能在替换版 U-Boot 中执行。**

1. 给路由器通电。
2. 看到 `Hit any key to stop autoboot` 时，按 Enter 或空格中断启动。
3. 停在 U-Boot 命令行后，保存串口日志和原始 `bootcmd`。

先下载 Chainloader：

```text
setenv serverip 192.168.1.10 ; setenv ipaddr 192.168.1.1 ; tftpboot 0x89000000 openwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb
```

继续前确认：

- TFTP 下载成功，文件完整加载到 `0x89000000`。
- 文件大小不超过 `0x100000` 字节。

**下载失败时不要擦写。确认无误后，逐行执行：**

- 首次安装：执行以下全部命令。
- 已安装过 Chainloader：在原厂 U-Boot 确认现有 `bootcmd` 已从 `0x600000` 读取 `0x100000` 字节到 `$loadaddr` 后执行 `bootm`，只执行从 `flash erase` 开始的三行，保留原来的 `bootcmd_orig`。不确定时停止，不要覆盖原厂环境。

```text
setenv bootcmd_orig "$bootcmd"
setenv one flash read 0x600000 0x100000 \$loadaddr
setenv two "; bootm"
setenv bootcmd "$one$two"
saveenv
flash erase 0x600000 0x100000
flash write 0x600000 0x100000 0x89000000
reset
```

### 启动 Installer

重启后进入 U-Boot 菜单。若跳过了 Chainloader 写入，此时通电进入菜单。

保持 Tftpd64 运行、Installer 文件在目录中，选择：

```text
Boot installer via TFTP.
```

本仓库 Chainloader 默认请求 `openwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb`。

若已有 Chainloader 请求的文件名不同，以 Tftpd64 显示的请求名为准：将本次下载的 Installer 复制一份并改为该名称，再选择菜单，不要换用其他发行版或版本的文件。

下载并启动后，串口会提示：

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

安装完成后即为本仓库的完整系统，包含中文 LuCI，无需再次升级。

1. 电脑保持连接黄色 1G LAN 口。
2. 将有线网卡恢复为自动获取 IP 和 DNS。
3. 等待重新获取地址，打开 `192.168.8.1`。

- 用户名：`root`
- 初始密码：留空

登录后先设置管理员密码，再配置上网和无线。

注意：`192.168.1.1` 是 U-Boot 下载阶段地址，正式系统默认地址为 `192.168.8.1`。

## 遇到问题

**串口无输出**

检查 COM 端口、`115200` 速率、流控 `None`，以及 TX/RX 交叉连接和 GND。

**TFTP 失败**

检查电脑 IP、Tftpd64 网卡、目录、完整文件名和防火墙，观察是否收到文件请求。

**后台打不开**

- 确认安装完成且已重启，电脑已恢复自动获取地址。
- 运行 `ipconfig`，查看直连有线网卡通过 DHCP 获得的 IPv4 默认网关；若不是 `192.168.8.1`，先试实际网关。项目默认设置未生效时，原生 LAN 地址可能仍为 `192.168.1.1`。
- 未获取地址时重新插拔网线；仍失败则看 TTL 串口启动日志，确认已进入正式系统而非 Installer 或 Recovery。在正式系统串口可用 `ip -4 addr show br-lan` 查看实际 LAN 地址，不要仅因网页打不开就重刷。

**提示原厂数据损坏**

使用本设备原有备份恢复，不要使用其他设备的数据。

[返回项目首页](README.md) · [OpenWrt 设备资料](https://openwrt.org/toh/gemtek/mxf-w1700k)
