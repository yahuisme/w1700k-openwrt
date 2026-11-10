# UBI2 Installer

本目录独立维护 W1700K UBI2 安装脚本，运行 overlay 与正式固件分离。安装逻辑源自 Kenneth Kasilag / hurrian 的 W1700K UBI Installer，按 [GPL-3.0](LICENSE) 保留；本项目维护分区预检、原厂数据校验、写入回读与失败停止机制。

构建复用本次官方源码与正式配置：先生成并校验 sysupgrade、Recovery、Chainloader，封存正式产物后，仅替换 overlay 增量生成 Installer。Installer 内嵌同次 sysupgrade 和 Recovery，不联网选择其他 Release。正式固件与内部 Recovery 不含自动安装入口。

`installer.json` 记录本次内嵌镜像与 Installer 的大小和 SHA-256，随构建记录保存，不作为 Release 附件。下载区仅发布三个 ITB。

## 隔离测试

在仓库根目录使用系统 Python；需要 root、BusyBox、python3-libfdt、python3-yaml、device-tree-compiler、u-boot-tools：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/installer -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_installer_*.py' -v
```

`TMPDIR` 必须指向可写的私有临时目录。运行测试使用 chroot 内的普通文件模拟设备，擦写、重启、同步和等待均被拦截，不访问主机设备。这些结果不代表真实 NAND 刷写或硬件启动验收。
