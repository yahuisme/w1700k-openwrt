void mt7996_queue_rx_skb(struct mt76_dev *mdev, enum mt76_rxq_id q,
			 struct sk_buff *skb, u32 *info)
{
	struct mt7996_dev *dev = container_of(mdev, struct mt7996_dev, mt76);
	__le32 *rxd = (__le32 *)skb->data;
	__le32 *end = (__le32 *)&skb->data[skb->len];
	enum rx_pkt_type type;

	type = le32_get_bits(rxd[0], MT_RXD0_PKT_TYPE);
	if (type != PKT_TYPE_NORMAL) {
		u32 sw_type = le32_get_bits(rxd[0], MT_RXD0_SW_PKT_TYPE_MASK);

		if (unlikely((sw_type & MT_RXD0_SW_PKT_TYPE_MAP) ==
			     MT_RXD0_SW_PKT_TYPE_FRAME))
			type = PKT_TYPE_NORMAL;
	}

	switch (type) {
	case PKT_TYPE_TXRX_NOTIFY:
		if (mtk_wed_device_active(&dev->mt76.mmio.wed_hif2) &&
		    q == MT_RXQ_TXFREE_BAND2) {
			dev_kfree_skb(skb);
			break;
		}

		mt7996_mac_tx_free(dev, skb->data, skb->len);
		napi_consume_skb(skb, 1);
		break;
	case PKT_TYPE_RX_EVENT:
		mt7996_mcu_rx_event(dev, skb);
		break;
	case PKT_TYPE_TXS:
		for (rxd += MT_TXS_HDR_SIZE; rxd + MT_TXS_SIZE <= end; rxd += MT_TXS_SIZE)
			mt7996_mac_add_txs(dev, rxd);
		dev_kfree_skb(skb);
		break;
	case PKT_TYPE_RX_FW_MONITOR:
		mt7996_debugfs_rx_fw_monitor(dev, skb->data, skb->len);
		dev_kfree_skb(skb);
		break;
	case PKT_TYPE_NORMAL:
		if (!mt7996_mac_fill_rx(dev, q, skb, info)) {
			mt76_rx(&dev->mt76, q, skb);
			return;
		}
		fallthrough;
	default:
		dev_kfree_skb(skb);
		break;
	}
}
