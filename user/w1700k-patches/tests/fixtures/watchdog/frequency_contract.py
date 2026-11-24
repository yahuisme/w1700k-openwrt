"""Pinned-source protocol oracle; never executes procd C, timers or ioctls."""

DRIVER_SETTER = '''static int watchdog_set_drv_timeout(void)
{
	int timeout = wdt_drv_timeout;
	int ret;

	if (wdt_fd < 0)
		return -1;

	ret = ioctl(wdt_fd, WDIOC_SETTIMEOUT, &timeout);
	if (ret) {
		ERROR("WDT failed to set timeout %ds: %m\\n", wdt_drv_timeout);
		if (ioctl(wdt_fd, WDIOC_GETTIMEOUT, &timeout) || timeout <= 0)
			timeout = wdt_last_timeout;
	}

	if (timeout <= 0)
		return -1;

	wdt_drv_timeout = timeout;
	wdt_last_timeout = timeout;
	if (wdt_frequency > timeout / 2)
		wdt_frequency = timeout / 2;
	if (wdt_frequency < 1)
		wdt_frequency = 1;

	if (wdt_timeout.pending)
		watchdog_timeout_cb(&wdt_timeout);

	return ret;
}'''


TIMEOUT_CALLBACK = '''static void watchdog_timeout_cb(struct uloop_timeout *t)
{
	watchdog_ping();
	uloop_timeout_set(t, wdt_frequency * 1000);
}'''


class ProtocolOracle:
    """Independent numeric model, gated by complete actual-source contracts.

    `actual` is deliberately unknown after an ioctl failure without a positive
    readback. The official requested-timeout cache is not hardware evidence.
    """
    def __init__(self, source, function, timeout=28, frequency=5, pending=True,
                 confirmed=True):
        assert function(source, "watchdog_set_drv_timeout") == DRIVER_SETTER, (
            "failed SET/GETTIMEOUT must fall back to the last confirmed timeout")
        assert function(source, "watchdog_timeout_cb") == TIMEOUT_CALLBACK
        self.timeout, self.frequency = timeout, frequency
        self.actual = timeout if confirmed else None
        self.last_timeout = timeout if confirmed else 0
        self.pending = pending
        self.online = True
        self.delay_ms = frequency * 1000 if pending else None
        self.pings = 0
        self.calls = []

    def ping_and_arm(self):
        self.pings += 1
        self.delay_ms = self.frequency * 1000
        self.pending = True

    def driver_set(self, accepted, readback=None):
        if not self.online:
            return -1
        self.calls.append(("SETTIMEOUT", self.timeout))
        if accepted is not None:
            actual, result = accepted, 0
        else:
            self.calls.append(("GETTIMEOUT",))
            actual, result = readback, -1
        self.actual = actual if actual is not None and actual > 0 else None
        effective = self.actual if self.actual is not None else self.last_timeout
        if effective <= 0:
            return -1
        self.last_timeout = effective
        self.timeout = effective
        self.frequency = max(1, min(self.frequency, effective // 2))
        if self.pending:
            self.ping_and_arm()
        return result

    def set_frequency(self, frequency):
        if frequency:
            self.frequency = frequency

    def set_timeout(self, timeout, accepted, readback=None):
        if timeout:
            self.timeout = timeout
            if self.online:
                self.driver_set(accepted, readback)

    def ubus(self, timeout=None, frequency=None, accepted=None, readback=None):
        # Exact unmodified system.c watchdog_set ordering is pinned by the caller.
        if frequency:
            limit = timeout if timeout is not None else self.timeout
            self.set_frequency(min(frequency, limit // 2))
        if timeout is not None:
            if timeout <= self.frequency:
                timeout = self.frequency * 2
            self.set_timeout(timeout, accepted, readback)
