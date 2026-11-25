# 迁移校验

`test_migration.py` 对照两个不可变的迁移前 Git 快照，检查完整补丁清单与文件字节；允许删除 `920` 原首个 txpower 判断 hunk；通用 `610` 保留 OpenWrt 原始字节，两版最终 regdb 等价性由 `test_regdb.py` 验证。

- OpenWrt：[`b527db7ab1f918f0467056c50c332cafe31df7c8`](https://github.com/yahuisme/w1700k-openwrt/commit/b527db7ab1f918f0467056c50c332cafe31df7c8)
- ImmortalWrt：[`b61b737b26b06b1be1085f356c761cb516aa618e`](https://github.com/yahuisme/w1700k-immortalwrt/commit/b61b737b26b06b1be1085f356c761cb516aa618e)

从 W1700K 固件仓库根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 user/w1700k-patches/tests/test_migration.py
```

默认读取带校验和的 `fixtures/migration-baseline.tar.gz`，内容来自 [packages 初次集中补丁的提交](https://github.com/yahuisme/packages/commit/14cc379984cc45cf10c6ce228fb44944bfa4f6af)，不需要 packages 或旧固件仓库。若要直接比对上述旧快照，可显式设置 `W1700K_OPENWRT_REPO`、`W1700K_IMMORTALWRT_REPO`。

本测试只验证迁移完整性及明确允许的维护差异；LuCI `998` 的原生 radio 路径、本机频率/缓存与 tab 差异保存在独立精确夹具中，要求历史 preimage 唯一，不替换历史基线。测试不编译、不修改固件仓库，不能代替源码适用性和功能验收。

## hostapd 上下文校验

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s user/w1700k-patches/tests -p test_hostapd_context.py -v
```

`fixtures/hostapd-context/manifest.json` 固定完整源码及 SHA256：OpenWrt `8d316065`、`7424e2ca` 与 ImmortalWrt `a4ba8240`。前者与 ImmortalWrt 的三个输入文件相同。测试要求 `920` 在旧、新源码上零 fuzz 应用；补丁新增/删除的代码不变、旧源码输出逐字节不变，新版关闭流程保持原样。历史补丁夹具沿用清单中固定的 packages 提交和 SHA256。该校验不执行无线操作，也不代替固件或实机验收。

## mt76 专项校验

`913` TX-free 与 `914` RRO 修复是迁移后新增补丁，不纳入旧快照字节等价比较，由固定源码函数夹具验证。原 `912` MCU 统计改造及其专用测试、供体/协议夹具和归档已移除；保留官方统计路径：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s user/w1700k-patches/tests -p test_txfree_cleanup.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s user/w1700k-patches/tests -p test_rro_cleanup.py -v
```

`914` 另检查 RRO 拒绝数据与 skb 分配失败的缓冲区回收。测试应用实际补丁并检查源码契约，不编译或执行内核 C，不代替固件构建和实机验收。

两系统完整 mt76 源码应用顺序为各自官方前置补丁、`911`、`913`、`914`、`915`、`916`、`917`。在 mt76 `0936617dc529ff9da0385221d3fa6de732231177` 上逐个实际应用，要求 `--fuzz=0 --no-backup-if-mismatch`、无 reject/backup；合法行偏移不是依赖。删掉 `912` 后 `913` 原有 `next:` 上下文仍匹配，无需刷新。

## 原生缺陷回移回归

共享 payload 共 20 个 patch，ImmortalWrt 另有一个 fw4 refresh。新增 `004` / `005` 位于 buildroot 层，`915` / `916` / `917` 位于 mt76 原生 package patch 层。正式回归在仓库根目录 `tests/test_native_fixes.py`，精确源码、官方 commit patch 和 SHA256 保存在 `tests/fixtures/w1700k-native-fixes/`，不依赖 scratch 生效。

从 fresh 仓库运行（ImmortalWrt 先在 fresh disposable copy 执行 `scripts/select_distribution.py immortalwrt`）：

```bash
flock /path/to/shared-tests.lock /opt/test-tools/bin/run-bounded-test \
  /opt/test-tools/run-in-repo "$PWD" env -u OPENWRT_SOURCE PYTHONPATH=.:tests \
  python3 -m unittest test_native_fixes test_mt76_payloads -v
```

测试执行实际 customization 的 preflight/guard/apply/copy 块，再在 exact selected mt76 全文件上有序零 fuzz 应用官方前置和全部本地 mt76 补丁；reset 重建各自 Linux 6.18.64/.60 完整 clock 文件的全部 touching 原生补丁。完整 `custom.sh` 及全部 payload missing/empty 由 `test_shared_patch_source.py` 配合精确 source 环境另验。最终配置/设备 manifest/真实 staging shell 覆盖有效 control、缺包、module/disabled/重复/冲突、manifest 缺失/重复/空/符号链接；OpenWrt 不额外选择 EIP93。

NPU 部分帧跨 poll、分配失败/cleanup 及 HE/EHT/IV/A-MSDU oracle 是绑定正式完整函数 hash 的 Python 数据流模型；含源码突变负例。它们不执行 kernel C、DMA、射频或实机网络，不替代授权 hosted build 及硬件验收。当前 mt76 master 的后继修改已核对：五个 reached 函数与正式修复版本相同。selected 缺独立的较早 WCID 生命周期修复 `6a2f1454`；仅在 oracle 内显式正规化其 prologue 后比较 A-MSDU 完整函数，不将它作为本次 header 定位修复的前置，不声称修复其它 station-removal/replay 风险。未导入其余 205-commit 跨度。

## 多射频扫描校验

```bash
PYTHONDONTWRITEBYTECODE=1 python3 user/w1700k-patches/tests/test_iwinfo_scan.py -v
LUCI_CHANNEL_SOURCE=/path/to/luci/modules/luci-mod-status PYTHONDONTWRITEBYTECODE=1 python3 user/w1700k-patches/tests/test_channel_analysis.py -v
```

后端夹具固定 iwinfo `66bdd1a` 与两系统相同的官方 `100-multi_radio.patch`，验证完整补丁链和源码契约，不编译或执行 C。

前端默认使用 `fixtures/scan-rpc` 的校验和固定完整 LuCI 视图；`LUCI_CHANNEL_SOURCE` 可指定两系统或 pinned CI 的同一精确视图。真实 `network.js` 的 `WifiDevice.getScanList()`、完整 `rpc.js` 及 `luci.js` 内 Class/Headers/Response/Request（包括 batching/flush）直接执行，仅注入 UCI/设备枚举、最小 DOM、XHR transport 与帧边界。固定版本及 Git blob/SHA256 见 `manifest.json`；两系统与 pinned CI 的 network/rpc/视图相同，Request 执行片段也相同。

扫描保持 pending 时，同帧 info 已通过独立 HTTP batch 返回，整次 refresh 仍等待 scan；这是传输分组与 Promise 语义回归，不是设备扫描耗时或吞吐基准。保留本机频率/信道核验、旧本机图清理、邻居缓存与各 band tab 测试；不再测试已删除的前端 netdev 选择器。停用 radio、无活动接口及 MLO 不在前端借用其他网卡，由 iwinfo 的 radio mask/临时 STA 路径负责；多链路本机信息可能缺失，不能把此测试称为 MLO/per-link 验收。info 的 ubus 错误/非对象归一为空并保留邻居，HTTP 错误仍按原生语义拒绝刷新。实际无线扫描仍需固件与设备验收。

## watchdog 校验

```bash
PYTHONDONTWRITEBYTECODE=1 python3 user/w1700k-patches/tests/test_watchdog_timeout.py -v
```

watchdog 使用 `001-watchdog-reconcile-timeout.patch`，检查固定 procd 源码、调用顺序及 pending timer 源码契约；Python 数值 oracle 覆盖接受/拒绝 timeout、离线请求、停止/恢复和 last-confirmed 回退，不执行 C/ioctl 或真实 watchdog。默认 sysfs cap、解析测试和 500ms 扩展已移除；保留官方秒级 API，一秒 timeout 的次秒喂狗不在支持范围。

## 通用 regdb 验证

`test_regdb.py` 使用校验和验证的源码归档，分别执行旧补丁链与新补丁链，要求完整 `db.txt` 逐字节一致。设置 `REGDB_ARCHIVE`、`REGDB_SOURCE_OPENWRT`、`REGDB_SOURCE_IMMORTALWRT` 后运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 user/w1700k-patches/tests/test_regdb.py
```

两个 source 变量指向未定制的官方源码，包含真实 regdb 配方和补丁。历史补丁与迁移校验共用基线夹具。ImmortalWrt 新链只移除 `600-custom-change-txpower-and-dfs.patch`，不移除其他官方补丁。
