# WAN LED offline fixture

`w1700k.dts`, `diag.sh`, `leds.sh` are verbatim official OpenWrt
`53ec2d05a487e6011cfa096de9211d15197c501b` files from:

- `target/linux/airoha/dts/an7581-w1700k-ubi.dts`
- `package/base-files/files/etc/diag.sh`
- `package/base-files/files/lib/functions/leds.sh`

The corresponding files at official ImmortalWrt
`305089f95180d4ab5206437b3527c7ed6cc46bc4` are byte-identical.
The test executes each repository's actual existing LED customization fragment:
boot green, failsafe red, running white; upgrade remains the official blue alias.
White is a dedicated GPIO 20 LED (`white:status`), not an RGB mixture.

Run without compiling or changing host networking:

```sh
WAN_LED_RUNTIME=/path/to/extracted/rootfs python3 -m unittest discover -s tests -p test_wan_led.py -v
```

Requires BusyBox ash, Bash, Python 3 and an AArch64 OpenWrt rootfs runnable on the
host. The rootfs supplies real jsonfilter and its musl loader/libraries. Missing
runtime is an error, not a silently skipped check. UCI and ubus are deterministic
I/O stubs; real official diag/LED functions and the production scripts execute
against isolated regular-file DT/sysfs fixtures. No daemon/network services run.
The sysfs fixture does not emulate kernel trigger formatting, timer blinking,
GPIO electrical behavior or hardware timing. Upgrade during the ubus query is
exercised; arbitrary scheduling between every sysfs write is not proven.

Logical interface `up` is not Internet reachability. Unknown status leaves the
lamp unchanged. Optional UCI `system.@system[0].wan_led=0` disables WAN handling;
`wan_led_interface` selects another logical interface (default `wan`). Active
status-LED kernel triggers and Aurora `system.@system[-1].leds_off=1` win.
Port-speed LEDs and network configuration are never written. There is one boot
sync at START=97 and iface hotplug updates only, without probes or a resident
process. Stage2 sets a marker and immediately hands back to native upgrade
indication; it does not sleep or wait for the hotplug query.
