# UBI2 Installer

首次刷机或完整重装（含救砖）请看对应教程：[OpenWrt](../w1700k-openwrt-first-flash.md) · [ImmortalWrt](../w1700k-immortalwrt-first-flash.md)。

本目录维护 W1700K UBI2 安装脚本，运行 overlay 与正式固件分离。安装逻辑源自 Kenneth Kasilag / hurrian 的 W1700K UBI Installer，按 [GPL-3.0](LICENSE) 保留；本项目维护分区预检、原厂数据校验、写入回读与失败停止机制。

先构建并封存完整 sysupgrade 与 Chainloader，再复用同次源码、工具链和包，通过原生打包流程生成精简 Recovery 与 Installer。临时环境沿用本仓硬件兼容修复，保留驱动、有线网络、SSH、UBI 与刷写工具，不包含 LuCI、Aurora、项目应用和日常设置。

此步骤位于构建末尾：结束时恢复正式配置、配方、overlay 与输出，随后只收集和发布封存产物，不复用临时 package/rootfs 状态继续构建正式固件。

Installer 自动写入同次构建的完整 sysupgrade，重启后无需再刷升级镜像。内嵌 Recovery 仅用于手动恢复，不会自动安装，默认管理地址为 `192.168.1.1`。

原厂 U-Boot 启动默认配置为 `conf-uboot` 的 Chainloader；Chainloader 明确选择 Linux FIT 的 `config-1`。Installer 只接受完整的 `yes` 确认行；UBI 回读用 BusyBox `cmp -n` 比较实际写入长度，不创建内存中的回读副本，也不比较卷的填充字节。

`installer.json` 记录本次内嵌镜像与 Installer 的大小和 SHA-256，随构建记录保存，不作为 Release 附件。下载区仅发布三个 ITB。

## 隔离测试

在仓库根目录使用系统 Python；需要 root、BusyBox、python3-libfdt、python3-yaml、device-tree-compiler、u-boot-tools：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/installer -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_installer_*.py' -v
```

`TMPDIR` 必须指向可写的私有临时目录。运行测试使用 chroot 内的普通文件模拟设备，擦写、重启、同步和等待均被拦截，不访问主机设备。这些结果不代表真实 NAND 刷写或硬件启动验收。
