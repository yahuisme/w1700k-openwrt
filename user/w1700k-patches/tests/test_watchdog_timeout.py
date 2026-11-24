#!/usr/bin/env python3
"""Pinned-source watchdog contracts; no C/firmware compilation or device I/O.

Fixture: https://github.com/openwrt/procd/blob/
fb6116870115a66686709017ecabfd724804bbdf/{watchdog.c,system.c}
The same procd revision is used by both firmware recipes. The timer fixture
is libubox a396f38a8568a1d670c240465cd8d24fdfdf6463/uloop.c, also shared
by the two pinned firmware recipes. Tests apply the
production patch with native GNU patch, then inspect the actual C source.
The source-bound Python protocol oracle never executes the patched C,
timers, ioctls or kernel C and does not cover target musl/ILP32.
Run: python3 w1700k-patches/tests/test_watchdog_timeout.py -v
"""
import importlib.util
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "tree/package/system/procd/patches/001-watchdog-reconcile-timeout.patch"
FIXTURE = Path(__file__).parent / "fixtures/watchdog/watchdog.c.fixture"
SHA256 = "d58e6783c988dc5217cedbf2056ee647a8a5d8e25a69c79c9cbed25019a88f88"
GIT_BLOB = "6d40d68b8aac03d494d291d1dcb40bc5af9838d8"


def function(source, name):
    """Return a complete top-level C function, not an earlier call site."""
    import re
    match = re.search(r"^(?:static )?(?:void|int|bool|char\*) " + re.escape(name)
                      + r"\([^\n]*\)\n\{", source, re.M)
    if not match:
        raise AssertionError(f"missing source function: {name}")
    end = source.index("\n}", match.end()) + 2
    return source[match.start():end]


class WatchdogTimeout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = FIXTURE.read_bytes()
        assert hashlib.sha256(data).hexdigest() == SHA256, "official source SHA256 mismatch"
        blob = b"blob " + str(len(data)).encode() + b"\0" + data
        assert hashlib.sha1(blob).hexdigest() == GIT_BLOB, "official Git blob mismatch"
        cls.original = data.decode()
        cls.temp = tempfile.TemporaryDirectory(prefix="watchdog-timeout-")
        cls.addClassCleanup(cls.temp.cleanup)
        target = Path(cls.temp.name) / "watchdog.c"
        target.write_bytes(data)
        # Missing production patch exposes the real upstream source for RED.
        if PATCH.exists():
            result = subprocess.run(
                ["patch", "-p1", "--batch", "--forward", "--fuzz=0",
                 "--no-backup-if-mismatch", "-i", str(PATCH)],
                cwd=cls.temp.name, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "fuzz" not in result.stdout.lower(), result.stdout
            assert "offset" not in result.stdout.lower(), result.stdout
        cls.source = target.read_text()
        directory = FIXTURE.parent
        system = (directory / "system.c.fixture").read_bytes()
        assert hashlib.sha256(system).hexdigest() == (
            "e8ca33a4c48d6d3fce27f54f6f2a55e6e1b4db01ccee8c8e31f5bd347523beb6"
        ), "official system.c SHA256 mismatch"
        blob = b"blob " + str(len(system)).encode() + b"\0" + system
        assert hashlib.sha1(blob).hexdigest() == "8c7fc071762e95ed002b3926ef9d454d9bddd31e"
        cls.system = system.decode()
        spec = importlib.util.spec_from_file_location(
            "watchdog_frequency_contract", directory / "frequency_contract.py")
        assert spec is not None and spec.loader is not None
        cls.contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.contract)

    def oracle(self, **kwargs):
        # An independent protocol oracle is useful only while the complete
        # production setter/callback and unmodified caller contracts match.
        self.assertEqual(function(self.source, "watchdog_timeout_cb"),
                         self.contract.TIMEOUT_CALLBACK)
        return self.contract.ProtocolOracle(self.source, function, **kwargs)

    def test_rejected_ubus_timeout_reconciles_actual_timeout_and_pending_timer(self):
        # Same immutable procd revision: system.c chooses frequency BEFORE
        # watchdog_timeout(). Only the latter can see a rejected driver's value.
        self.assertLess(self.system.index("\t\twatchdog_frequency(freq);"),
                        self.system.index("\t\twatchdog_timeout(timeout);"))
        oracle = self.oracle()
        oracle.ubus(timeout=60, frequency=30, accepted=None, readback=28)
        self.assertEqual(oracle.calls, [("SETTIMEOUT", 60), ("GETTIMEOUT",)])
        self.assertEqual((oracle.actual, oracle.timeout, oracle.frequency), (28, 28, 14))
        self.assertEqual((oracle.pings, oracle.delay_ms), (1, 14000))
        self.assertLess(oracle.delay_ms, oracle.actual * 1000)

    def test_default_and_seconds_callback_remain_official(self):
        self.assertEqual(function(self.source, "watchdog_timeout_cb"),
                         function(self.original, "watchdog_timeout_cb"))
        self.assertEqual(function(self.source, "watchdog_init"),
                         function(self.original, "watchdog_init"))
        self.assertNotIn("max_timeout", self.source)
        self.assertNotIn("wdt_timeout_set", self.source)
        oracle = self.oracle(timeout=30, pending=False, confirmed=False)
        oracle.driver_set(accepted=None, readback=28)
        self.assertEqual(oracle.calls, [("SETTIMEOUT", 30), ("GETTIMEOUT",)])
        self.assertEqual((oracle.timeout, oracle.frequency, oracle.pings), (28, 5, 0))
        oracle.ping_and_arm()  # official init callback follows negotiation
        self.assertEqual(oracle.delay_ms, 5000)

    def test_timeout_only_acceptance_and_rejection_use_driver_value(self):
        for accepted, readback, expected_timeout, expected_frequency in [
                (8, None, 8, 4), (12, None, 12, 5),
                (None, 4, 4, 2), (None, 28, 28, 5)]:
            with self.subTest(accepted=accepted, readback=readback):
                oracle = self.oracle()
                oracle.ubus(timeout=12, accepted=accepted, readback=readback)
                self.assertEqual((oracle.timeout, oracle.frequency),
                                 (expected_timeout, expected_frequency))
                self.assertEqual(oracle.delay_ms, expected_frequency * 1000)
                self.assertEqual(oracle.pings, 1)
                self.assertLess(oracle.delay_ms, oracle.actual * 1000)

    def test_failed_or_nonpositive_readback_is_not_an_actual_timeout(self):
        for readback in [None, 0, -1]:
            with self.subTest(readback=readback):
                oracle = self.oracle()
                oracle.ubus(timeout=60, frequency=30, readback=readback)
                # Current hardware state remains unknown, but the failed
                # request must not replace the last confirmed timeout bound.
                self.assertIsNone(oracle.actual)
                self.assertEqual((oracle.timeout, oracle.frequency), (28, 14))
                self.assertEqual((oracle.pings, oracle.delay_ms), (1, 14000))
                self.assertEqual(oracle.calls, [("SETTIMEOUT", 60), ("GETTIMEOUT",)])

    def test_offline_explicit_request_survives_init_and_restart(self):
        for accepted, readback, expected in [(60, None, (60, 30)),
                                             (None, 28, (28, 14))]:
            with self.subTest(accepted=accepted, readback=readback):
                oracle = self.oracle()
                oracle.online, oracle.pending, oracle.delay_ms = False, False, None
                oracle.ubus(timeout=60, frequency=30)
                self.assertEqual(oracle.calls, [])
                self.assertEqual((oracle.timeout, oracle.frequency), (60, 30))
                # Both init and restart call the unchanged official setter path.
                oracle.online = True
                oracle.driver_set(accepted, readback)
                self.assertEqual(oracle.pings, 0, "do not activate a stopped timer in the setter")
                oracle.ping_and_arm()  # unchanged init/restart callback
                self.assertEqual((oracle.timeout, oracle.frequency), expected)
                self.assertEqual(oracle.pings, 1)
                self.assertLess(oracle.delay_ms, oracle.actual * 1000)

    def test_default_28_5_and_seconds_based_limits_have_safe_intervals(self):
        for timeout, frequency, delay in [(28, 5, 5000), (5, 2, 2000),
                                          (4, 2, 2000), (3, 1, 1000),
                                          (2, 1, 1000)]:
            with self.subTest(timeout=timeout):
                oracle = self.oracle(timeout=timeout, pending=False)
                oracle.driver_set(accepted=timeout)
                oracle.ping_and_arm()
                self.assertEqual((oracle.timeout, oracle.frequency, oracle.delay_ms),
                                 (timeout, frequency, delay))
                self.assertLess(oracle.delay_ms, timeout * 1000)

    def test_rearm_replaces_pending_uloop_timer(self):
        # Both shipped distro libubox recipes pin this same revision. The
        # callback pings first: merely resetting a deadline could postpone a
        # heartbeat relative to the previous write when timeout gets shorter.
        data = (FIXTURE.parent / "uloop.c.fixture").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "5810bf4dd7c1df588e62bc807d5b0858f1c15514547796714a47d7544e72ac77")
        setter = function(data.decode(), "uloop_timeout_set")
        self.assertIn("if (timeout->pending)\n\t\tuloop_timeout_cancel(timeout);", setter)
        self.assertLess(setter.index("uloop_timeout_cancel(timeout)"),
                        setter.index("uloop_gettime(time)"))
        self.assertIn("return uloop_timeout_add(timeout);", setter)
        self.assertLess(self.contract.TIMEOUT_CALLBACK.index("watchdog_ping();"),
                        self.contract.TIMEOUT_CALLBACK.index("uloop_timeout_set("))

    def test_frequency_only_request_keeps_the_pinned_caller_guard(self):
        # watchdog_frequency() is not a ubus method: system.c is its only
        # writer and bounds frequency-only calls against the cached timeout.
        # Do not clamp the low-level setter against the OLD timeout: system.c
        # also calls it before a combined request for a larger timeout.
        for frequency, expected in [(30, 14), (3, 3), (0, 5)]:
            with self.subTest(frequency=frequency):
                oracle = self.oracle()
                oracle.ubus(frequency=frequency)
                self.assertEqual(oracle.frequency, expected)
                self.assertEqual(oracle.calls, [], "frequency-only must not set a timeout")
                self.assertEqual((oracle.pings, oracle.delay_ms), (0, 5000))
                oracle.ping_and_arm()  # existing pending timer fires normally
                self.assertEqual(oracle.delay_ms, expected * 1000)
                self.assertLess(oracle.delay_ms, oracle.actual * 1000)
        oracle = self.oracle()
        oracle.ubus(timeout=60, frequency=30, accepted=60)
        self.assertEqual((oracle.timeout, oracle.frequency, oracle.delay_ms),
                         (60, 30, 30000), "preserve a valid larger explicit request")
        self.assertEqual(function(self.source, "watchdog_frequency"),
                         function(self.original, "watchdog_frequency"))

    def test_stop_resume_reconciles_without_losing_the_explicit_request(self):
        oracle = self.oracle()
        oracle.ubus(timeout=60, frequency=30, accepted=60)
        oracle.online, oracle.pending, oracle.delay_ms = False, False, None
        before = oracle.pings
        oracle.online = True
        oracle.driver_set(accepted=None, readback=28)
        self.assertEqual(oracle.pings, before)
        oracle.ping_and_arm()  # original resume callback, after setter
        self.assertEqual((oracle.timeout, oracle.frequency, oracle.delay_ms),
                         (28, 14, 14000))
        self.assertEqual(oracle.calls,
                         [("SETTIMEOUT", 60), ("SETTIMEOUT", 60), ("GETTIMEOUT",)])

    def test_unknown_timeout_uses_last_confirmed_bound_after_both_ioctls_fail(self):
        oracle = self.oracle()
        oracle.ubus(timeout=60, frequency=30, accepted=None, readback=None)
        self.assertIsNone(oracle.actual, "failed ioctls do not confirm the current hardware timeout")
        self.assertEqual(oracle.last_timeout, 28)
        oracle.ping_and_arm()
        self.assertEqual((oracle.timeout, oracle.frequency, oracle.delay_ms), (28, 14, 14000))
        oracle.ubus(frequency=30)
        self.assertEqual(oracle.frequency, 14, "failed request must not loosen frequency-only guard")

    def test_never_confirmed_timeout_stays_unknown(self):
        oracle = self.oracle(timeout=30, confirmed=False)
        oracle.ubus(timeout=60, frequency=30, accepted=None, readback=None)
        self.assertIsNone(oracle.actual)
        self.assertEqual(oracle.last_timeout, 0)
        self.assertEqual(oracle.pings, 0)
        # With no successful observation there is no hardware bound to invent.
        self.assertEqual((oracle.timeout, oracle.frequency), (60, 30))

    def test_negative_source_mutants_cannot_bypass_reconciliation(self):
        source = self.source
        mutants = {
            "omit-frequency-clamp": ("\tif (wdt_frequency > timeout / 2)\n\t\twdt_frequency = timeout / 2;\n", ""),
            "trust-request-after-readback-failure": (
                "\t\tif (ioctl(wdt_fd, WDIOC_GETTIMEOUT, &timeout) || timeout <= 0)\n\t\t\ttimeout = wdt_last_timeout;",
                "\t\tioctl(wdt_fd, WDIOC_GETTIMEOUT, &timeout);"),
            "forget-last-confirmed-timeout": ("\twdt_last_timeout = timeout;\n", ""),
            "accept-nonpositive-timeout": ("\tif (timeout <= 0)\n\t\treturn -1;\n", ""),
            "omit-pending-rearm": ("\tif (wdt_timeout.pending)\n\t\twatchdog_timeout_cb(&wdt_timeout);\n", ""),
            "restart-stopped-timer": ("\tif (wdt_timeout.pending)\n\t\twatchdog_timeout_cb(&wdt_timeout);",
                                      "\twatchdog_timeout_cb(&wdt_timeout);"),
        }
        for name, (old, new) in mutants.items():
            with self.subTest(mutant=name):
                self.assertEqual(source.count(old), 1)
                changed = source.replace(old, new, 1)
                with self.assertRaises(AssertionError):
                    self.assertEqual(function(changed, "watchdog_timeout_cb"),
                                     self.contract.TIMEOUT_CALLBACK)
                    self.contract.ProtocolOracle(changed, function)

    def test_all_other_source_bytes_remain_official(self):
        source = self.source
        added = "static int wdt_last_timeout;\n"
        self.assertEqual(source.count(added), 1)
        source = source.replace(added, "", 1)
        setter = function(source, "watchdog_set_drv_timeout")
        self.assertEqual(setter, self.contract.DRIVER_SETTER)
        source = source.replace(setter, function(self.original, "watchdog_set_drv_timeout"), 1)
        # Default negotiation, seconds callback, WDTFD, offline requests and
        # stop/start retain every official byte outside this one setter/state.
        self.assertEqual(source, self.original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
