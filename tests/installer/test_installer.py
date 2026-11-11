"""Run the real installer in a disposable chroot with BusyBox ash.

Requires root, busybox and its dynamic libraries; never exposes host /dev or
/sys. Hardware commands, sync, reboot and sleep are scripts, not applets.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = json.loads((ROOT / 'user/default/build.json').read_text())['system']


class InstallerSourceTest(unittest.TestCase):
    def test_installer_overlay_is_self_contained(self):
        for name in ["installer/install.sh", "lib/preinit/00_installer"]:
            path = ROOT / "installer/files" / name
            self.assertTrue(path.is_file(), f"Missing migrated installer overlay: {path}")
            self.assertGreater(path.stat().st_size, 0)


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="installer-test-", dir=os.environ["TMPDIR"])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.put("bin/busybox", Path("/usr/bin/busybox").read_bytes(), 0o755)
        libs = subprocess.check_output(["ldd", "/usr/bin/busybox"], text=True)
        for token in libs.split():
            if token.startswith("/") and Path(token).is_file():
                self.put(token, Path(token).read_bytes(), 0o755)
        for cmd in "sh ash head cat basename mkdir hexdump dd strings grep cut tr sed wc cp printf cmp rm awk sha256sum".split():
            (self.root / "bin" / cmd).symlink_to("busybox")
        # Ubuntu ash has a sleep builtin which bypasses PATH stubs. Override
        # it only in the private scripts, never in the shipped installer.
        sleep_stub = b'sleep() { /bin/sleep "$@"; }\n'
        installer = (ROOT / "installer/files/installer/install.sh").read_bytes()
        self.put("installer/install.sh", installer.replace(b'#!/bin/sh\n', b'#!/bin/sh\n' + sleep_stub, 1), 0o755)
        self.put("preinit", sleep_stub + (ROOT / "installer/files/lib/preinit/00_installer").read_bytes())
        self.put("dev/null", b"")
        self.put("dev/zero", bytes(65536))
        raw = bytearray(0x600000)
        dsd = b"wan_mac=02:11:22:33:44:55\nlan_mac=02:11:22:33:44:66\nfan_id=FAN\nserial_number=SERIAL\n"
        raw[0x400000:0x400000+len(dsd)] = dsd
        raw[0x405000:0x406e00] = b"\x90\x79" + b"E" * (0x1e00-2)
        self.put("dev/mtd0", raw)
        for n, name, size, off in [(0,"vendor",0x600000,0),(1,"chainloader",0x100000,0x600000),(2,"ubi",0x1b700000,0x700000)]:
            for k,v in {"name":name,"size":size,"offset":off,"erasesize":131072}.items():
                self.put(f"sys/class/mtd/mtd{n}/{k}", str(v)+"\n")
        self.put("proc/device-tree/compatible", b"gemtek,w1700k-ubi\0airoha,an7581\0")
        self.put("sys/class/ubi/ubi0/mtd_num", "2\n")
        for n in range(5):
            self.put(f"dev/ubi0_{n}", b"")
        self.put("dev/ubi0", b"")
        for suffix in ["initramfs-recovery", "squashfs-sysupgrade"]:
            self.put(f"installer/{SYSTEM}-airoha-an7581-gemtek_w1700k-ubi-{suffix}.itb", (suffix.encode()+b"\0")*100)
        images = sorted((self.root / "installer").glob("*.itb"))
        self.manifest = ''.join(hashlib.sha256(image.read_bytes()).hexdigest() +
                                '  ' + image.name + '\n' for image in images)
        self.put("installer/payload.sha256", self.manifest)
        for cmd in "sync reboot sleep ubidetach ubiformat ubiattach ubimkvol mknod".split():
            self.stub(cmd, 'echo "'+cmd+' $*" >> /calls\nexit 0\n')
        self.stub("ubinfo", "exit 1\n")
        self.stub("ubiupdatevol", 'echo "ubiupdatevol $*" >> /calls\ncp "$2" "$1"\n')
        for p in ["functions.sh", "upgrade/common.sh", "upgrade/fit.sh"]:
            self.put("lib/"+p, "\n")
        self.put("lib/upgrade/nand.sh", '''nand_upgrade_fit() {
  echo nand_upgrade_fit >> /calls
  cp "$1" /dev/ubi0_4
}
nand_find_ubi() { echo ubi0; }
nand_find_volume() { [ "$2" = fit ] && echo ubi0_4 || echo "$2"; }
''')
        (self.root / "tmp").mkdir()

    def put(self, p, data, mode=0o644):
        p = self.root / str(p).lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink():
            p.unlink()
        p.write_bytes(data.encode() if isinstance(data, str) else data)
        p.chmod(mode)

    def stub(self, cmd, body):
        self.put("bin/"+cmd, "#!/bin/sh\n"+body, 0o755)

    def real_upgrade_helpers(self):
        for name, target in [("functions.sh", "functions.sh"), ("common.sh", "upgrade/common.sh"),
                             ("nand.sh", "upgrade/nand.sh"), ("fit.sh", "upgrade/fit.sh"),
                             ("uci.sh", "config/uci.sh")]:
            self.put("lib/" + target, (ROOT / 'tests/installer/fixtures' / SYSTEM / name).read_bytes())
        self.put("proc/mtd", 'mtd0: 00600000 00020000 "vendor"\nmtd1: 00100000 00020000 "chainloader"\nmtd2: 1b700000 00020000 "ubi"\n')
        self.stub("fw_printenv", "exit 1\n")  # Fresh env has no rootfs_data_max.
        self.stub("ubidetach", 'echo "ubidetach $*" >> /calls\nrm -rf /sys/class/ubi/ubi0*\n')
        self.stub("ubiattach", 'echo "ubiattach $*" >> /calls\nmkdir -p /sys/class/ubi/ubi0\necho 2 > /sys/class/ubi/ubi0/mtd_num\n')
        self.stub("ubirmvol", '''echo "ubirmvol $*" >> /calls
for vol in /sys/class/ubi/ubi0_*; do
  if [ "$(cat "$vol/name")" = "$3" ]; then rm -rf "$vol"; fi
done
''')
        self.stub("ubimkvol", '''echo "ubimkvol $*" >> /calls
shift
id= name=
while [ "$#" -gt 0 ]; do
  case "$1" in -n) id="$2"; shift;; -N) name="$2"; shift;; esac
  shift
done
if [ -z "$id" ]; then
  id=0
  while [ -d "/sys/class/ubi/ubi0_$id" ]; do id=$((id + 1)); done
fi
mkdir -p "/sys/class/ubi/ubi0_$id"
echo "$name" > "/sys/class/ubi/ubi0_$id/name"
: > "/dev/ubi0_$id"
''')
        self.stub("ubiupdatevol", '''echo "ubiupdatevol $*" >> /calls
if [ "$2" = -s ]; then cat > "$1"; else cp "$2" "$1"; fi
''')

    def test_real_helpers_first_migration_and_ttl_recovery(self):
        self.real_upgrade_helpers()
        # No existing volume is required: first migration, damaged/unattached
        # UBI and attached-but-empty UBI all reach the same rebuild path.
        for scenario in ["first-migration", "damaged-unattached", "attached-empty", "missing-fit"]:
            with self.subTest(scenario=scenario):
                for path in (self.root / "sys/class/ubi").glob("ubi0*"):
                    shutil.rmtree(path)
                if scenario in ["attached-empty", "missing-fit"]:
                    self.put("sys/class/ubi/ubi0/mtd_num", "2\n")
                if scenario == "missing-fit":
                    self.put("sys/class/ubi/ubi0_2/name", "factory\n")
                self.put("calls", "")
                p = self.run_installer()
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn("reboot returned", p.stdout)
                self.assertIn("stage=reboot", p.stdout)
                self.assertIn("reboot", self.calls)
                self.assertIn("Sync complete", p.stdout)
                self.assertIn("ubiformat /dev/mtd2 -y", self.calls)
                self.assertIn("ubirmvol /dev/ubi0 -N fit", self.calls)
                self.assertIn("ubiupdatevol /dev/ubi0_4 -s", self.calls)
                self.assertEqual("ubidetach" in self.calls, scenario in ["attached-empty", "missing-fit"])
                image = self.root / f"installer/{SYSTEM}-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb"
                self.assertEqual((self.root / "dev/ubi0_4").read_bytes(), image.read_bytes())
                self.assertEqual((self.root / "sys/class/ubi/ubi0_5/name").read_text().strip(), "rootfs_data")

    def test_real_helpers_fit_write_failure_stops_before_reboot(self):
        self.real_upgrade_helpers()
        self.stub("ubiupdatevol", '''echo "ubiupdatevol $*" >> /calls
[ "$2" != -s ] || exit 8
cp "$2" "$1"
''')
        p = self.run_installer()
        self.assertEqual(p.returncode, 8, p.stdout)
        self.assertIn("stage=write fit", p.stdout)
        self.assertNotIn("reboot", self.calls)

    def test_confirmed_recovery_does_not_prompt_again_in_ubiformat(self):
        self.stub("ubiformat", '''echo "ubiformat $*" >> /calls
case " $* " in *" -y "*) exit 0;; esac
echo SECOND_FORMAT_PROMPT
read -r answer
[ "$answer" = y ]
''')
        p = self.run_installer("yes\n")
        self.assertIn("Sync complete", p.stdout)
        self.assertNotIn("SECOND_FORMAT_PROMPT", p.stdout)

    def test_failed_ubinfo_still_requires_confirmation(self):
        # Failed probe can mean corrupt or unattached UBI, not first install.
        shutil.rmtree(self.root / "sys/class/ubi/ubi0")
        for answer in ["no\n", ""]:
            with self.subTest(answer=answer):
                p = self.run_installer(answer)
                self.assertIn("User aborted", p.stdout)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertNotIn("ubiformat", self.calls)

    def run_installer(self, answer="yes\n", preinit=False):
        def isolate():
            os.chroot(self.root)
            os.chdir("/")
        script = ". /preinit; echo NORMAL_BOOT" if preinit else "/installer/install.sh"
        p = subprocess.run(["/bin/ash", "-c", script], preexec_fn=isolate,
                           env={"PATH":"/bin", "LC_ALL":"C"}, input=answer,
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        calls = self.root / "calls"
        self.calls = calls.read_text() if calls.exists() else ""
        return p

    def assert_payload_rejected(self):
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("stage=verify payload", p.stdout)
        self.assertEqual(self.calls, "", p.stdout)
        self.assertFalse((self.root / "installer/factory.bin").exists())

    def test_missing_payload_manifest_stops_before_erase(self):
        (self.root / "installer/payload.sha256").unlink()
        self.assert_payload_rejected()

    def test_bad_payload_manifests_stop_before_erase(self):
        first = self.manifest.splitlines()[0]
        for manifest in ('', first + '\n', self.manifest + first + '\n',
                         self.manifest.replace(first[:64], '0' * 63, 1),
                         self.manifest.replace(first[:64], 'z' * 64, 1),
                         self.manifest + 'garbage\n'):
            with self.subTest(manifest=manifest):
                self.put("installer/payload.sha256", manifest)
                self.assert_payload_rejected()

    def test_missing_corrupt_or_truncated_payloads_stop_before_erase(self):
        for image in sorted((self.root / "installer").glob("*.itb")):
            original = image.read_bytes()
            for damage in ('missing', 'corrupt', 'truncated'):
                with self.subTest(image=image.name, damage=damage):
                    if damage == 'missing':
                        image.unlink()
                    elif damage == 'corrupt':
                        image.write_bytes(b'X' + original[1:])
                    else:
                        image.write_bytes(original[:-1])
                    self.assert_payload_rejected()
                    image.write_bytes(original)

    def test_digest_tool_failures_stop_before_erase(self):
        for tool in ('sha256sum', 'awk'):
            with self.subTest(tool=tool):
                # Plausible stdout must not hide the producer's nonzero exit.
                self.stub(tool, 'echo "' + self.manifest.splitlines()[0] + '"\nexit 8\n')
                self.assert_payload_rejected()
                (self.root / 'bin' / tool).unlink()
                (self.root / 'bin' / tool).symlink_to('busybox')

    def test_empty_payload_stops_before_erase(self):
        self.put(f"installer/{SYSTEM}-airoha-an7581-gemtek_w1700k-ubi-initramfs-recovery.itb", b"")
        p = self.run_installer()
        self.assertNotIn("ubiformat", self.calls, p.stdout)
        self.assertIn("Empty required file", p.stdout)

    def test_cancel_and_eof_never_write(self):
        self.stub("ubinfo", "exit 0\n")
        for answer in ["no\n", ""]:
            with self.subTest(answer=answer):
                p = self.run_installer(answer)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertIn("User aborted", p.stdout)
                self.assertEqual(self.calls, "")

    def test_reboot_failure_stage(self):
        self.stub("reboot", "exit 9\n")
        p = self.run_installer()
        self.assertEqual(p.returncode, 9)
        self.assertIn("stage=reboot", p.stdout)

    def test_dynamic_volume_padding_is_ignored(self):
        self.stub("ubiupdatevol", 'cp "$2" "$1"\nprintf "\\377\\377" >> "$1"\n')
        p = self.run_installer()
        self.assertIn("Install complete", p.stdout)
        self.assertNotIn("readback mismatch", p.stdout)
        factory = (self.root / "installer/factory.bin").read_bytes()
        self.assertEqual(len(factory), 0x10000)
        self.assertEqual(factory[:0x1e00], b"\x90\x79"+b"E"*(0x1e00-2))
        self.assertEqual(factory[0x5000:0x5006], bytes.fromhex("021122334455"))
        self.assertEqual(factory[0x7000:0x7003], b"FAN")
        self.assertEqual(factory[0x8000:0x8006], b"SERIAL")

    def test_hex_conversion_failure_stops_before_erase(self):
        self.stub("sed", "exit 8\n")
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertNotIn("ubiformat", self.calls, p.stdout)
        self.assertIn("stage=read factory data", p.stdout)

    def test_string_conversion_failure_stops_before_erase(self):
        self.stub("hexdump", '''case " $* " in
  *" -n "*|*" -s "*) exec /bin/busybox hexdump "$@";;
  *) exit 8;;
esac
''')
        p = self.run_installer()
        self.assertEqual(p.returncode, 8, p.stdout)
        self.assertNotIn("ubiformat", self.calls, p.stdout)
        self.assertIn("stage=read factory data", p.stdout)

    def test_factory_read_io_failure_reports_backup_conditionally(self):
        self.stub("dd", "exit 7\n")
        p = self.run_installer()
        self.assertEqual(p.returncode, 7, p.stdout)
        self.assertIn("stage=read factory data exit=7", p.stdout)
        self.assertNotIn("ubiformat", self.calls)
        self.assertIn("If calibration data is damaged", p.stdout)
        self.assertIn("original backup from this device", p.stdout)
        self.assertNotIn("Factory data could not be validated.", p.stdout)

    def test_bad_magic_never_erases(self):
        with (self.root / "dev/mtd0").open("r+b") as f:
            f.seek(0x405000)
            f.write(b"XX")
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("ubiformat", self.calls)
        self.assertIn("original backup from this device", p.stdout)

    def test_reboot_return_is_not_success(self):
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Sync complete", p.stdout)
        self.assertIn("reboot returned", p.stdout)
        self.assertIn("Install complete", p.stdout)

    def test_preinit_cancel_shell_exit_does_not_retry(self):
        self.stub("ubinfo", "echo prompt >> /calls\nexit 0\n")
        self.put("bin/sh", '''#!/bin/busybox sh
if [ "$1" = -i ]; then
  if [ -f /shell_seen ]; then kill -TERM "$PPID"; else
    printf seen > /shell_seen
  fi
  exit 0
fi
exec /bin/busybox sh "$@"
''', 0o755)
        p = self.run_installer("no\n", preinit=True)
        self.assertIn("Installer stopped (exit 0)", p.stdout)
        self.assertIn("Still stopped", p.stdout)
        self.assertNotIn("NORMAL_BOOT", p.stdout)
        self.assertEqual(self.calls.count("prompt"), 1)
        self.assertNotIn("ubiformat", self.calls)

    def test_preinit_failure_does_not_boot_normally(self):
        self.put("installer/install.sh", "#!/bin/sh\nexit 7\n", 0o755)
        self.stub("sh", '''if [ "$1" = -i ]; then
  echo DIAGNOSTIC_SHELL
  kill -TERM "$PPID"
  exit 0
fi
exec /bin/busybox sh "$@"
''')
        # Avoid recursive shebang in this one interpreter wrapper.
        p = self.root / "bin/sh"
        p.write_text(p.read_text().replace("#!/bin/sh", "#!/bin/busybox sh", 1))
        p = self.run_installer(preinit=True)
        self.assertIn("Installer stopped (exit 7)", p.stdout)
        self.assertIn("DIAGNOSTIC_SHELL", p.stdout)
        self.assertNotIn("NORMAL_BOOT", p.stdout)

    def test_erase_geometry_bounds(self):
        self.put("sys/class/mtd/mtd0/erasesize", str(0x200000))
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("EEPROM search exceeds vendor", p.stdout)
        self.assertNotIn("ubiformat", self.calls)

    def test_dsd_short_read(self):
        self.stub("dd", '''case "$*" in
  *of=/tmp/factory-build/dsd.bin*) printf 'wan_mac=02:11:22:33:44:55\\nlan_mac=02:11:22:33:44:66\\nfan_id=F\\nserial_number=S\\n' > /tmp/factory-build/dsd.bin ;;
  *) /bin/busybox dd "$@" ;;
esac
''')
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("DSD length", p.stdout)
        self.assertNotIn("ubiformat", self.calls)

    def test_wrong_layout_stops_before_raw_read(self):
        self.put("sys/class/mtd/mtd2/name", "firmware\n")
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("Unsupported MTD layout", p.stdout)
        self.assertNotIn("ubiformat", self.calls)

    def test_mtd_numeric_fields_must_be_valid(self):
        for field, value in [("size", ""), ("offset", "invalid")]:
            with self.subTest(field=field):
                self.put("sys/class/mtd/mtd2/size", str(0x1b700000) + "\n")
                self.put("sys/class/mtd/mtd2/offset", str(0x700000) + "\n")
                self.put("calls", "")
                self.put(f"sys/class/mtd/mtd2/{field}", value + "\n")
                p = self.run_installer()
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn("Unsupported MTD layout", p.stdout)
                self.assertNotIn("ubiformat", self.calls)

    def test_overflowing_mtd_numbers_never_erase(self):
        for field in ["size", "offset"]:
            with self.subTest(field=field):
                self.put("sys/class/mtd/mtd2/size", str(0x1b700000) + "\n")
                self.put("sys/class/mtd/mtd2/offset", str(0x700000) + "\n")
                self.put("calls", "")
                self.put(f"sys/class/mtd/mtd2/{field}", "9" * 100 + "\n")
                p = self.run_installer()
                self.assertNotIn("ubiformat", self.calls, p.stdout)
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn("Unsupported MTD layout: mtd2", p.stdout)

    def test_recovery_readback(self):
        self.stub("ubiupdatevol", 'cp "$2" "$1"\n[ "$1" != /dev/ubi0_3 ] || printf bad > "$1"\nexit 0\n')
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("readback mismatch: /dev/ubi0_3", p.stdout)

    def test_fit_readback_uses_discovered_volume(self):
        self.put("lib/upgrade/nand.sh", '''nand_upgrade_fit() { printf bad > /dev/ubi0_7; }
nand_find_ubi() { echo ubi0; }
nand_find_volume() { echo ubi0_7; }
''')
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("readback mismatch: /dev/ubi0_7", p.stdout)

    def test_corrupt_readback_stops(self):
        self.stub("ubiupdatevol", 'echo update >> /calls\nprintf bad > "$1"\n')
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("readback mismatch", p.stdout)
        self.assertNotIn("nand_upgrade_fit", self.calls)

    def test_write_failure_reports_stage(self):
        self.stub("ubiupdatevol", 'exit 7\n')
        p = self.run_installer()
        self.assertEqual(p.returncode, 7)
        self.assertIn("stage=write factory", p.stdout)
        self.assertNotIn("nand_upgrade_fit", self.calls)
        self.assertNotIn("Install complete", p.stdout)

    def test_valid_magic_reaches_write(self):
        p = self.run_installer()
        self.assertIn("ubiupdatevol", self.calls, p.stdout)
        self.assertIn("sleep 5", self.calls, p.stdout)
        self.assertIn("reboot returned", p.stdout)

    def test_short_eeprom_stops_before_erase(self):
        with (self.root / "dev/mtd0").open("r+b") as f:
            f.truncate(0x405100)
        p = self.run_installer()
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("EEPROM length", p.stdout)
        self.assertNotIn("ubiformat", self.calls)


if __name__ == "__main__":
    unittest.main()
