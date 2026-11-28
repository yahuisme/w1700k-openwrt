# W1700K 补丁说明与来源

本目录的补丁随 W1700K 固件仓库版本维护，供 OpenWrt main 和 ImmortalWrt master 共用。LuCI 应用仍从 [packages](https://github.com/yahuisme/packages) 获取。

## 补丁清单

| 补丁 | 用途 | 来源与调整 |
| --- | --- | --- |
| `patches/002-*`、`tree/target/linux/airoha/patches-6.18/940-*` | CPUFreq 设备树资源与 CPU PLL 兼容回退 | [B]；保留官方频率与调频策略，不含超频 |
| `tree/target/linux/airoha/patches-6.18/745-*` | E2 PCS RX 校准 | [A]/[B]，作者 Gilly |
| `tree/target/linux/airoha/patches-6.18/746-*` | MDIO 扫描前解除 PHY 复位 | [A]/[B]，作者 Gilly |
| `tree/package/kernel/mt76/patches/911-*` | 功率变更时刷新固件功率限制 | 作者 Yanghan Ye；适配 OpenW1700k 的 `0011-refresh-power-limits-on-txpower-changes`，SKU 启用沿用官方；本项目移除有效 BSS 功率通知的缓存去重，保留错误日志，不增加自动重试 |
| `tree/package/kernel/mt76/patches/913-*` | TX-free 消息边界与分片校验，截断后完成已有回收与队列唤醒 | 基于 [C]/[D]；保留异常告警，不增加超时 token 回收 |
| `tree/package/kernel/mt76/patches/914-*` | RRO 丢弃数据及 skb 分配失败时归还接收缓冲区 | 本项目修复；保留成功路径的 skb 所有权转移 |
| `tree/package/kernel/mt76/patches/915-*` | 跨 NAPI poll 保留 NPU RX 部分帧、逐描述符推进及 cleanup/DMA read barrier | 原样回移正式 mt76 [a801adb](https://github.com/openwrt/mt76/commit/a801adb009f70cde062de22976d4d6c7dc13daa8)，作者 Lorenzo Bianconi；不使用已关闭 #1169 的旧方案 |
| `tree/package/kernel/mt76/patches/916-*`、`917-*` | EHT radiotap header 定位与首 A-MSDU 子帧 RFC1042 检查 | 原样配套回移正式 mt76 [1a519350](https://github.com/openwrt/mt76/commit/1a519350810083fce4ae1ab00ff58f02b716f6e0) / [6145ff0](https://github.com/openwrt/mt76/commit/6145ff0b02f315f8e80af01345cb3bd6caa62b84)，作者 Felix Fietkau |
| `tree/package/kernel/mt76/patches/918-*`、`919-*` | STA 移除及 PHY 注销时清理分段 A-MSDU 暂存 | 原样配套回移正式 mt76 [6a2f145](https://github.com/openwrt/mt76/commit/6a2f14547f724e6c4f882cfb44e81f04e6e82357) / [9a52272](https://github.com/openwrt/mt76/commit/9a5227284c5ab94788eb41c2f1474e4111cc9708)，作者 Eason Lai |
| `tree/target/linux/airoha/patches-6.18/925-*` | 写完命令字段后再通知 NPU | 仅回移 [OpenWrt #26812 第一提交](https://github.com/openwrt/openwrt/pull/26812/commits/49661833555b360e024950cf0a1466f0cd027cd5)，不增加重试或修改超时 |
| `patches/004-*` | 原生 `609-02` reset 的两处分支初始化 | 适配 [OpenWrt #26755](https://github.com/openwrt/openwrt/pull/26755) head `10715e0cecff464a3a5b6fd26bac971bf792ebc5`；仅将两处 `val |=` 改为 `val =`，不改 reset 策略 |
| `patches/005-*` | EIP93 原生软件包依赖 CBC provider | 适配 [OpenWrt #26863](https://github.com/openwrt/openwrt/pull/26863) head `a6f51b8ce24e12275bf578a98df4685c0fb2862e`；仅加 `+kmod-crypto-cbc`，不在 OpenWrt 自动选择 EIP93 |
| `patches/610-*` | CN/US 功率与频段定制 | 包含 [A] 的 US 高频段及 6 GHz 设置；迁移时对照固定源码，两版补丁处理后的 `db.txt` 一致 |
| `tree/package/network/utils/iwinfo/patches/998-*` | 按目标 radio 选择接口与创建临时扫描接口 | 本项目扩展官方 multi-radio 实现，使用 UCI radio 索引及原生接口 radio mask |
| `tree/package/network/utils/iwinfo/patches/999-*` | 按当前频率展示功率列表 | [A]/[B]，作者 Yanghan Ye |
| `tree/package/system/procd/patches/001-*` | watchdog 超时协商后约束喂狗周期 | 本项目修复；沿用官方 ioctl 路径，仅修改 setter 及 last-confirmed 状态 |
| `patches/920-*` | 非 MLO AP 按 BSS 设置功率 | 本项目实现，适用范围见下文 |
| `patches/921-*` | 小数 dBm 截断为整数后转换成 `iw` 接受的 mBm 参数 | 原样回移 [cf4cc7b](https://github.com/openwrt/openwrt/commit/cf4cc7b5492a1b4e8b3df9a3377cebfb1e80d1f3)，先于 `920` 应用，保留固定零和自动功率的区别 |
| `patches/998-*` | single-wiphy 多射频信道分析适配 | 作者 Gilly1970；沿用原生 radio scan/info（扫描沿用 `nobatch`），校验本机频率、清理失效缓存并限定 tab 频段，保留停用 AP 扫描；宽信道主信道线只挂在对应的 SVG 组内，随组移除 |
| `patches/110-*` | 修复 libwebsockets 5.1 下 ttyd 启动即退出 | 回移植 [ttyd #1589](https://github.com/tsl0922/ttyd/pull/1589)，保留官方绑定、认证与日志配置 |
| `patches/003-*` | 风扇初始化仅操作识别到的 NCT7802，写入失败时尝试恢复自动控制 | 回移植 [OpenWrt #26929](https://github.com/openwrt/openwrt/pull/26929)，保留两版各自的机型分支和官方曲线 |

### 来源

- [A] [OpenWRT-fanboy/OpenW1700k · `bce05fa86b22`](https://github.com/OpenWRT-fanboy/OpenW1700k/commit/bce05fa86b222741d8afcef2e5468a9481679041)
- [B] [OpenWRT-fanboy/OpenW1700k · `972634e64d19`](https://github.com/OpenWRT-fanboy/OpenW1700k/commit/972634e64d19cba0095b662a0bfd9561ebef635c)
- [C] [OpenWRT-fanboy/OpenW1700k · `23df1d78c647`](https://github.com/OpenWRT-fanboy/OpenW1700k/commit/23df1d78c6476d4a301ecd56aab65f4c6be86542)
- [D] [OpenWRT-fanboy/OpenW1700k · `12650fa28dfe`](https://github.com/OpenWRT-fanboy/OpenW1700k/commit/12650fa28dfedccb20d726780c06c8fa45074b18)

原作者信息保留在补丁头部。

## 应用方式

- `002`、`003`、`004`、`005`、`921` → `920`：在固件源码根目录应用。`004` 修正原生内核补丁，`005` 修正原生 package 依赖，不另造驱动层副本。平台 `925` 接在原生 coherent mailbox `924` 后；来源漂移或编号冲突须先检查吸收。
- mt76 保留 `0936617dc529ff9da0385221d3fa6de732231177`，不整体更新 master。默认 caller 校验 source version/hash、各自官方前置补丁字节、`609-02` 和 EIP93 package 段；漂移、上游吸收或新增 ID 冲突均停止，不能静默覆盖。源更新后先重审再撤 guard/回移。
- ImmortalWrt profile 显式预装 `kmod-crypto-cbc`，正式 final.config、设备 manifest 和 staging 门同时要求 EIP93/CBC；OpenWrt profile 不增这两个包。
- `610`：复制到 wireless-regdb 补丁目录，在官方 `500` 后应用；ImmortalWrt 仅移除被覆盖的 `600-custom-change-txpower-and-dfs.patch`。
- `998`：复制到 LuCI 的 luci-mod-status 补丁目录，由 LuCI 构建流程应用。
- `110`：复制到 ttyd 软件包补丁目录，在官方日志补丁后应用。
  本地回移标作 `1.7.7-r2`，以便 APK 区分原版 `r1`。上游修订变化时，需分别核对两套 feed 是否已吸收修复，并验证 APK 版本顺序。
- `tree/`：按源码目录结构复制，由内核与软件包构建流程应用。
- ImmortalWrt 单独替换官方 firewall4 FullCone 补丁：只有 IPv4 或 IPv6 启用 FullCone 才探测，探测失败时两者均回退至普通 masquerade；不改 UCI 设置或默认值。

## 多射频扫描

后端 `iwinfo/998` 接续[官方 multi-radio 补丁](https://github.com/openwrt/openwrt/blob/dab12e766366dceb149e70aa1155005b6a571299/package/network/utils/iwinfo/patches/100-multi_radio.patch)，按 UCI `radio` 索引匹配接口，停用 AP 时沿用临时 STA 扫描并绑定目标 radio。LuCI `998` 按信道与实际 MHz 核对本机数据，避免跨频段的假本机标记；不关闭停用 AP 的邻居扫描。

## 非 MLO AP 功率

`920` 在 `bss_add` 后设置功率，功率变更沿用 hostapd 重启路径。失败时记录日志并通知，不向 netifd 返回同步成功确认。

仅适用于共享 PHY 上所有活动 radio 均为非 MLO AP 的配置。混用 MLO 或非 AP 时，全局 PHY 设置仍可能覆盖功率；不提供 MLO 按链路控制。

支持显式设置 `0 dBm`，未设置时使用自动功率；小数设置向零截断为整数 dBm 后发送给驱动。

## 维护

官方优先，保留必要修复与既定定制；官方吸收后验证移除。必要补丁缺失或应用失败即停止构建。

不保留原 `912` MCU 统计改造：没有 W1700K 实测收益，恢复官方统计路径；`911`、`913`、`914` 不依赖它，分别保留功率刷新、TX-free 边界/收尾及 RRO 缓冲区归还修复。两系统官方前置补丁加 `911 → 913 → 914 → 915 → 916 → 917 → 918 → 919` 在固定 mt76 源码上按序应用。

watchdog 默认 `30 → 28` 已能通过官方 `GETTIMEOUT` 回读，不再读取 sysfs 或增加 500ms 喂狗。保留的是组合请求先设置 frequency、后协商 timeout 时的周期一致性修复，含 pending timer 重排、stopped/offline 行为及双 ioctl 失败时的 last-confirmed 上界。不支持一秒超时的次秒喂狗；不据源码契约宣称所有机型或硬件均已验收。

[迁移与 regdb 校验](tests/README.md)
