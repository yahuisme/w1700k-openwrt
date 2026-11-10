"""Local documentation contracts; no network or device operations."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
DISTRO = "openwrt"
PREFIX = f"{DISTRO}-airoha-an7581-gemtek_w1700k-ubi-"


class InstallerDocsTest(unittest.TestCase):
    def test_download_and_tutorial_are_local(self):
        readme = (ROOT / "README.md").read_text()
        guide = ROOT / "w1700k-first-flash.md"
        self.assertTrue(guide.is_file(), "Missing local first-install guide")
        text = guide.read_text()
        self.assertIn("[W1700K 刷机教程](w1700k-first-flash.md)", readme)
        for doc in [readme, text]:
            self.assertNotIn("w1700k-ubi2-installer", doc)
            self.assertIn(f"https://github.com/yahuisme/w1700k-{DISTRO}/releases", doc)
            for suffix in ["chainload-uboot", "initramfs-installer", "squashfs-sysupgrade"]:
                self.assertIn(PREFIX + suffix + ".itb", doc)
        self.assertEqual(re.findall(r"^## ([1-4])\. ", text, re.M), ["1", "2", "3", "4"])
        for value in ["192.168.8.1", "`root`", "初始密码：留空", "不接 VCC", "必须使用 3.3V TTL", "0x100000", "下载失败时不要擦写"]:
            self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()
