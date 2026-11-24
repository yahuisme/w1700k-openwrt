# TX-free 源码夹具

`mt7996/mac.c` 是不可变的官方 `mt7996_mac_tx_free()` 原始函数；`mt7996/queue_rx_skb.c` 是同版官方 `mt7996_queue_rx_skb()` 原始函数。均取自 openwrt/mt76 提交 `0936617dc529ff9da0385221d3fa6de732231177`，第二个函数仅去掉末尾额外空行；`mt7996/rx_check.c` 保留同版原始 DMA 分类入口。

- 原始文件 SHA-256：`afbb328d9711a5eb335c3f36230b25cbe26fb66154fe9738b157ccff23e9899f`
- TXFREE 函数 SHA-256：`a22a9a73f3db00e933ee79041dbf41e9d1abe481e1d7c7babffe2ff0d0ec8fbf`
- queue_rx_skb 函数 SHA-256：`27befddc178b6e4c9b3403b97ea724a70af5ddd0d7e84f5bb072e58241998b55`
- rx_check 函数 SHA-256：`8ca542bea25ff041c32d92f122a3fd5b7f9d13fe2043b5b4108eb1aa58eaef00`
- 原文件许可：BSD-3-Clause-Clear；Copyright (C) 2022 MediaTek Inc.

测试在私有目录拼接原始函数并零 fuzz 应用实际 `913`，逐一检查唯一允许的差异：最小 8 字节头、完整 4 字节 info/ver7 扩展 word、截断时保留 `WARN_ON_ONCE` 并 `break`、TXFREE 分片 skb 经 `pskb_may_pull` 成功后才解析。反向归一化后仍要求与原 TXFREE 夹具逐字节相等；两个接收入口均在读取首个 descriptor word 前验长；skb 首字 pull 成功后重取指针，失败即释放并返回。队列函数另对 TXFREE 完整 pull，保留 WED bypass、失败时的 skb 消费及其它分支。没有更改 token ownership，也不引入超时回收。

属于源码契约验证，不编译或执行内核 C，不等于 skb 分配失败、DMA、固件构建或硬件测试。
