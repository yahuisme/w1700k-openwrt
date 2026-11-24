"""Distribution-specific first-flash guides; no network or device writes."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/W1700K.yaml'
SYSTEMS = {'openwrt': 'OpenWrt', 'immortalwrt': 'ImmortalWrt'}


class InstallerDocsTest(unittest.TestCase):
    def test_each_distribution_has_a_complete_separate_guide(self):
        readme = (ROOT / 'README.md').read_text()
        installer_readme = (ROOT / 'installer/README.md').read_text()
        for system, title in SYSTEMS.items():
            with self.subTest(system=system):
                filename = f'w1700k-{system}-first-flash.md'
                self.assertTrue((ROOT / filename).is_file(), filename)
                text = (ROOT / filename).read_text()
                self.assertIn(f']({filename})', readme)
                self.assertIn(f'](../{filename})', installer_readme)
                self.assertIn('[PuTTY 中文版](https://github.com/larryli/putty)', text)
                self.assertIn('[Tftpd64 官方下载](https://github.com/PJO2/tftpd64/releases/)', text)
                self.assertIn(f'# W1700K {title}', text)
                self.assertIn(f'/w1700k-openwrt/releases?q=W1700K-{title}-', text)
                self.assertIn('[返回项目首页](README.md)', text)
                self.assertEqual(re.findall(r'^## ([1-4])\. ', text, re.M), ['1', '2', '3', '4'])
                for suffix in ('chainload-uboot', 'initramfs-installer', 'squashfs-sysupgrade'):
                    self.assertIn(f'{system}-airoha-an7581-gemtek_w1700k-ubi-{suffix}.itb', text)
                other = next(value for value in SYSTEMS if value != system)
                self.assertNotIn(f'{other}-airoha-an7581-', text)
                for value in ('192.168.8.1', '`root`', '初始密码：留空', '不接 VCC',
                              '必须使用 3.3V TTL', '0x100000', '下载失败时不要擦写',
                              'Boot installer via TFTP.', '同一次发布', '请求名',
                              'flash erase 0x600000 0x100000',
                              'flash write 0x600000 0x100000 0x89000000'):
                    self.assertIn(value, text)
                self.assertTrue(text.endswith('\n'))
                self.assertNotIn('/releases/latest', text)
                self.assertNotIn('w1700k-ubi2-installer', text)
                self.assertNotRegex(text, r'(?:0\. Exit|\d+\. Boot installer via TFTP)')
                verify, flash = text.split('### 写入 Chainloader', 1)
                for value in ('兼容版本 2.0', '`mtd list`', '`0x00700000`–`0x1be00000`',
                              '`0x1be00000`–`0x20000000`', '在旧版也存在',
                              '无法进入控制台', '先不要运行 Installer 或强制 sysupgrade',
                              'ee771d3dd01c811d2a28eab09a700cefdafd05af'):
                    self.assertIn(value, verify)
                self.assertIn('不能在替换版 U-Boot 中执行', flash.split('```', 1)[0])
                for value in ('`yes` 并按 Enter', 'DHCP 获得的 IPv4 默认网关', 'TTL 串口启动日志'):
                    self.assertIn(value, text)
        self.assertIn('两个独立 Release', readme)
        self.assertIn('各自只保留最新一版', readme)
        self.assertIn('重装仅在确认已是兼容版本 2.0 布局时可跳过', readme)

    def test_release_notes_link_to_the_selected_guide(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('/blob/main/w1700k-${SYSTEM}-first-flash.md)', workflow)


if __name__ == '__main__':
    unittest.main()
