'use strict';
'require baseclass';
'require rpc';
'require poll';

var callFanStatus = rpc.declare({
	object: 'luci.fan',
	method: 'getStatus',
	expect: { '': {} }
});

return baseclass.extend({
	title: _('温度与风扇'),

	load: function() {
		return L.resolveDefault(callFanStatus(), {});
	},

	render: function(data) {
		var sensors = [
			['CPU', 'temp_cpu'],
			['主板', 'temp_board'],
			['10G WAN', 'temp_phy2'],
			['10G LAN', 'temp_phy1'],
			['2.4 GHz', 'wifi_24g'],
			['5 GHz', 'wifi_5g'],
			['6 GHz', 'wifi_6g']
		];

		var nodes = {};

		function temp(value) {
			value = Number(value);
			return isFinite(value) && value > 0 ? value + ' °C' : '--';
		}

		function color(value) {
			value = Number(value);

			if (!isFinite(value))
				return '';

			if (value >= 80)
				return '#e53935';

			if (value >= 70)
				return '#f57c00';

			if (value >= 60)
				return '#e6a700';

			return '';
		}

		function fan(d) {
			if (d.fan_rpm == null || Number(d.fan_rpm) <= 0)
				return '--';

			return d.fan_rpm + ' RPM' +
				(d.fan_percentage != null
					? ' · ' + d.fan_percentage + '%'
					: '');
		}

		function valueBox(text, tone) {
			return E('div', {
				'style':
					'font-size:20px;' +
					'line-height:1.2;' +
					'white-space:nowrap;' +
					(tone ? 'color:' + tone + ';' : '')
			}, text);
		}

		function card(label, body) {
			return E('div', {
				'style':
					'padding:14px 12px;' +
					'border:1px solid var(--border-color-medium,#ddd);' +
					'border-radius:10px;' +
					'text-align:center;' +
					'min-width:0;'
			}, [
				E('div', {
					'style':
						'font-size:13px;' +
						'opacity:.7;' +
						'margin-bottom:7px;' +
						'white-space:nowrap;'
				}, label),

				body
			]);
		}

		var root = E('div', {
			'style':
				'display:grid;' +
				'grid-template-columns:' +
					'repeat(auto-fit,minmax(145px,1fr));' +
				'gap:12px;'
		});

		sensors.forEach(function(sensor) {
			var key = sensor[1];

			nodes[key] = valueBox(temp(data[key]), color(data[key]));

			root.appendChild(
				card(sensor[0], nodes[key])
			);
		});

		nodes.fan = valueBox(fan(data), '');

		root.appendChild(
			card('风扇', nodes.fan)
		);

		poll.add(function() {
			return L.resolveDefault(
				callFanStatus(),
				{}
			).then(function(d) {

				sensors.forEach(function(sensor) {
					var key = sensor[1];
					var node = nodes[key];

					node.textContent = temp(d[key]);
					node.style.color = color(d[key]);
				});

				nodes.fan.textContent = fan(d);
			});

		}, 5);

		return root;
	}
});
