# procd watchdog source fixture

`watchdog.c.fixture` is unchanged official procd source at `fb6116870115a66686709017ecabfd724804bbdf`, selected by both distribution recipes.

- URL: https://github.com/openwrt/procd/blob/fb6116870115a66686709017ecabfd724804bbdf/watchdog.c
- SHA256: `d58e6783c988dc5217cedbf2056ee647a8a5d8e25a69c79c9cbed25019a88f88`
- Git blob: `6d40d68b8aac03d494d291d1dcb40bc5af9838d8`

Tests apply the production patch and compare all source bytes outside the driver setter and one last-confirmed state variable. The official init, seconds-based callback, deferred requests, WDTFD adoption and stop/start remain exact. There is no sysfs parser or default clamp. The Python oracle is not execution of compiled procd C, musl or watchdog ioctls. No host `/dev/watchdog` or sysfs files are accessed.

`system.c.fixture` pins the same procd revision's frequency-before-timeout call order; `uloop.c.fixture` pins libubox `a396f38a8568a1d670c240465cd8d24fdfdf6463`. Their SHA256 values are asserted in the suite. `frequency_contract.py` checks complete patched functions before applying a numeric protocol oracle for accepted/rejected timeouts, pending timers, stopped requests and last-confirmed fallback. A failed readback is not a fresh hardware observation; a device with no confirmed timeout remains unverified. The one-second timeout/subsecond-heartbeat extension is intentionally absent and not a supported safety claim.
