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
                              'Boot installer via TFTP.', '同一次发布',
                              'flash erase 0x600000 0x100000',
                              'flash write 0x600000 0x100000 0x89000000'):
                    self.assertIn(value, text)
                self.assertTrue(text.endswith('\n'))
                self.assertNotIn('/releases/latest', text)
                self.assertNotIn('w1700k-ubi2-installer', text)
                self.assertNotRegex(text, r'(?:0\. Exit|\d+\. Boot installer via TFTP)')
                self.assertIn(f'# W1700K {title} 首次刷机 / 完整重装（含救砖）\n', text)
                self.assertIn('在原厂 U-Boot 中刷入 Chainloader，再启动 Installer 安装系统', text)
                self.assertIn('无法进入原厂 U-Boot 时，本教程不适用', text)
                self.assertIn('会清除原有系统与配置', text)
                self.assertIn('UBI2 兼容版本为 2.0', text)
                self.assertNotRegex(text, r'跳过|只执行|只需第二个|mtd list')
                flash, _ = text.split('### 写入 Chainloader', 1)[1].split('### 启动 Installer', 1)
                self.assertIn('不能在替换版 U-Boot 中执行', flash.split('```', 1)[0])
                self.assertIn('已有 `bootcmd_orig` 就保留原值', flash)
                blocks = re.findall(r'```text\n(.*?)\n```', flash, re.S)
                self.assertEqual(len(blocks), 2)
                self.assertIn(f'tftpboot 0x89000000 {system}-airoha-an7581-gemtek_w1700k-ubi-chainload-uboot.itb', blocks[0])
                self.assertEqual(blocks[1].splitlines(), [
                    r'setenv one flash read 0x600000 0x100000 \$loadaddr',
                    'setenv two "; bootm"', 'setenv bootcmd "$one$two"', 'saveenv',
                    'flash erase 0x600000 0x100000', 'flash write 0x600000 0x100000 0x89000000', 'reset',
                ])
                self.assertIn('无论以前是否刷过，均逐行执行', flash)
                self.assertIn('每步确认成功后再继续；如有报错，停在原厂 U-Boot，不要重启', flash.split(blocks[1], 1)[0])
                installer = text.split('### 启动 Installer', 1)[1].split('## 4.', 1)[0]
                self.assertIn('只放这次下载的两个文件', text)
                filename = f'{system}-airoha-an7581-gemtek_w1700k-ubi-initramfs-installer.itb'
                self.assertIn(f'`{filename}`', installer)
                self.assertIn('不要使用之前下载的文件', installer)
                self.assertLess(installer.index('确认加载的是本次下载的 Installer'),
                                installer.index('`yes` 并按 Enter'))
                for value in ('`yes` 并按 Enter', 'DHCP 获得的 IPv4 默认网关', 'TTL 串口启动日志'):
                    self.assertIn(value, text)
        self.assertIn('两个发行版各自构建和发布', readme)
        self.assertIn('只保留各自最新一版', readme)
        self.assertIn('## 首次刷机 / 完整重装（含救砖）\n', readme)
        self.assertIn('`chainload-uboot.itb` | 在原厂 U-Boot 中首次刷入或重刷 Chainloader |', readme)
        self.assertIn('## 日常升级\n', readme)

    def test_release_notes_link_to_the_selected_guide(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('/blob/main/w1700k-${SYSTEM}-first-flash.md)', workflow)


if __name__ == '__main__':
    unittest.main()
