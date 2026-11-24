bool mt7996_rx_check(struct mt76_dev *mdev, void *data, int len)
{
	struct mt7996_dev *dev = container_of(mdev, struct mt7996_dev, mt76);
	__le32 *rxd = (__le32 *)data;
	__le32 *end = (__le32 *)&rxd[len / 4];
	enum rx_pkt_type type;

	type = le32_get_bits(rxd[0], MT_RXD0_PKT_TYPE);
	if (type != PKT_TYPE_NORMAL) {
		u32 sw_type = le32_get_bits(rxd[0], MT_RXD0_SW_PKT_TYPE_MASK);

		if (unlikely((sw_type & MT_RXD0_SW_PKT_TYPE_MAP) ==
			     MT_RXD0_SW_PKT_TYPE_FRAME))
			return true;
	}

	switch (type) {
	case PKT_TYPE_TXRX_NOTIFY:
		mt7996_mac_tx_free(dev, data, len);
		return false;
	case PKT_TYPE_TXS:
		for (rxd += MT_TXS_HDR_SIZE; rxd + MT_TXS_SIZE <= end; rxd += MT_TXS_SIZE)
			mt7996_mac_add_txs(dev, rxd);
		return false;
	case PKT_TYPE_RX_FW_MONITOR:
		mt7996_debugfs_rx_fw_monitor(dev, data, len);
		return false;
	default:
		return true;
	}
}
