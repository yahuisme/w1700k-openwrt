# W1700K ImmortalWrt U-Boot 与首次安装教程

- **首次安装**：按以下四步操作。
- **重装系统**：若已有 `4. Boot installer via TFTP` 菜单，跳过“写入 Chainloader”。
- **日常升级**：已有兼容 UBI2 系统时，使用 [sysupgrade 固件](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-ImmortalWrt-)，不要运行 Installer。

> 安装会清除原有系统与配置。确认设备型号并保存本机原厂数据备份，刷写期间不要断电。

## 1. 准备

- Windows 电脑、网线、3.3V USB-TTL
- [PuTTY](https://www.putty.org/)：串口终端
- [Tftpd64](https://bitbucket.org/phjounin/tftpd64/wiki/Home)：TFTP 服务

从 [Release](https://github.com/yahuisme/w1700k-openwrt/releases?q=W1700K-ImmortalWrt-) 下载同一次发布的以下两个文件，放入 `C:\tftp`：

```text
immortalwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb
immortalwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb
```

另一个文件 `immortalwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb` 用于日常升级，不要替代 Installer。首次安装的两个文件不要混用发行版或版本。

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

**以下命令仅适用于原厂 U-Boot。已有 Installer 菜单则跳到下一步。**

1. 给路由器通电。
2. 看到 `Hit any key to stop autoboot` 时，按 Enter 或空格中断启动。
3. 停在 U-Boot 命令行后，保存串口日志和原始 `bootcmd`。

先下载 Chainloader：

```text
setenv serverip 192.168.1.10 ; setenv ipaddr 192.168.1.1 ; tftpboot 0x89000000 immortalwrt-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb
```

继续前确认：

- TFTP 下载成功，文件完整加载到 `0x89000000`。
- 文件大小不超过 `0x100000` 字节。

**下载失败时不要擦写。确认无误后，逐行执行：**

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
4. Boot installer via TFTP
```

本仓库 Chainloader 默认请求 `immortalwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb`。

若已有 Chainloader 请求的文件名不同，以 Tftpd64 显示的请求名为准：将本次下载的 Installer 复制一份并改为该名称，再选择菜单，不要换用其他发行版或版本的文件。

下载并启动后，串口会提示：

```text
Initialize/reinstall UBI2 on mtd2 and erase its contents? (yes/no)
```

- 输入 `yes`：开始安装。
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
- 运行 `ipconfig`，检查有线网卡地址是否为 `192.168.8.x`，网关是否为 `192.168.8.1`。
- 未获取地址时重新插拔网线，不要仅因网页打不开就重刷 Installer。

**提示原厂数据损坏**

使用本设备原有备份恢复，不要使用其他设备的数据。

[返回项目首页](README.md) · [OpenWrt 设备资料](https://openwrt.org/toh/gemtek/mxf-w1700k)
