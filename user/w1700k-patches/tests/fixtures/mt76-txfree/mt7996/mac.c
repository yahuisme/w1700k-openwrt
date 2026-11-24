static void
mt7996_mac_tx_free(struct mt7996_dev *dev, void *data, int len)
{
	__le32 *tx_free = (__le32 *)data, *cur_info;
	struct mt76_dev *mdev = &dev->mt76;
	struct mt76_phy *phy2 = mdev->phys[MT_BAND1];
	struct mt76_phy *phy3 = mdev->phys[MT_BAND2];
	struct ieee80211_link_sta *link_sta = NULL;
	struct mt76_txwi_cache *txwi;
	struct mt76_wcid *wcid = NULL;
	LIST_HEAD(free_list);
	struct sk_buff *skb, *tmp;
	void *end = data + len;
	bool wake = false;
	u16 total, count = 0;
	u8 ver;

	/* clean DMA queues and unmap buffers first */
	mt76_queue_tx_cleanup(dev, dev->mphy.q_tx[MT_TXQ_PSD], false);
	mt76_queue_tx_cleanup(dev, dev->mphy.q_tx[MT_TXQ_BE], false);
	if (phy2) {
		mt76_queue_tx_cleanup(dev, phy2->q_tx[MT_TXQ_PSD], false);
		mt76_queue_tx_cleanup(dev, phy2->q_tx[MT_TXQ_BE], false);
	}
	if (phy3) {
		mt76_queue_tx_cleanup(dev, phy3->q_tx[MT_TXQ_PSD], false);
		mt76_queue_tx_cleanup(dev, phy3->q_tx[MT_TXQ_BE], false);
	}

	ver = le32_get_bits(tx_free[1], MT_TXFREE1_VER);
	if (WARN_ON_ONCE(ver < 5))
		return;

	total = le32_get_bits(tx_free[0], MT_TXFREE0_MSDU_CNT);
	for (cur_info = &tx_free[2]; count < total; cur_info++) {
		u32 msdu, info;
		u8 i;

		if (WARN_ON_ONCE((void *)cur_info >= end))
			return;
		/* 1'b1: new wcid pair.
		 * 1'b0: msdu_id with the same 'wcid pair' as above.
		 */
		info = le32_to_cpu(*cur_info);
		if (info & MT_TXFREE_INFO_PAIR) {
			struct ieee80211_sta *sta;
			unsigned long valid_links;
			struct mt7996_sta *msta;
			unsigned int id;
			u16 idx;

			idx = FIELD_GET(MT_TXFREE_INFO_WLAN_ID, info);
			wcid = mt76_wcid_ptr(dev, idx);
			sta = wcid_to_sta(wcid);
			if (!sta) {
				link_sta = NULL;
				goto next;
			}

			link_sta = rcu_dereference(sta->link[wcid->link_id]);
			if (!link_sta)
				goto next;

			msta = (struct mt7996_sta *)sta->drv_priv;
			valid_links = sta->valid_links ?: BIT(0);

			/* For MLD STA, add all link's wcid to sta_poll_list */
			for_each_set_bit(id, &valid_links,
					 IEEE80211_MLD_MAX_NUM_LINKS) {
				struct mt7996_sta_link *msta_link;

				msta_link = mt7996_sta_link(msta, id);
				if (!msta_link)
					continue;

				mt76_wcid_add_poll(&dev->mt76,
						   &msta_link->wcid);
			}
next:
			/* ver 7 has a new DW with pair = 1, skip it */
			if (ver == 7 && ((void *)(cur_info + 1) < end) &&
			    (le32_to_cpu(*(cur_info + 1)) & MT_TXFREE_INFO_PAIR))
				cur_info++;
			continue;
		} else if (info & MT_TXFREE_INFO_HEADER) {
			u32 tx_retries = 0, tx_failed = 0, count;

			if (!wcid)
				continue;

			count = FIELD_GET(MT_TXFREE_INFO_COUNT, info);
			tx_retries = count ? count - 1 : 0;
			tx_failed = tx_retries +
				!!FIELD_GET(MT_TXFREE_INFO_STAT, info);

			wcid->stats.tx_retries += tx_retries;
			wcid->stats.tx_failed += tx_failed;
			continue;
		}

		for (i = 0; i < 2; i++) {
			msdu = (info >> (15 * i)) & MT_TXFREE_INFO_MSDU_ID;
			if (msdu == MT_TXFREE_INFO_MSDU_ID)
				continue;

			count++;
			txwi = mt76_token_release(mdev, msdu, &wake);
			if (!txwi)
				continue;

			mt7996_txwi_free(dev, txwi, link_sta, wcid,
					 &free_list);
		}
	}

	mt7996_mac_sta_poll(dev);

	if (wake)
		mt76_set_tx_blocked(&dev->mt76, false);

	mt76_worker_schedule(&dev->mt76.tx_worker);

	list_for_each_entry_safe(skb, tmp, &free_list, list) {
		skb_list_del_init(skb);
		napi_consume_skb(skb, 1);
	}
}

