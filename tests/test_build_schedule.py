"""Verify direct daily Hong Kong scheduling without a date gate."""
from datetime import datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/W1700K.yaml'


class BuildScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text())

    def test_direct_daily_cron_at_six_hong_kong_time(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(triggers['schedule'], [
            {'cron': '0 6 * * *', 'timezone': 'Asia/Hong_Kong'}])
        self.assertEqual(set(triggers), {'schedule', 'workflow_dispatch'})
        hk = ZoneInfo(triggers['schedule'][0]['timezone'])
        for local_date, utc_date in (
            ((2026, 12, 1), (2026, 11, 30)),
            ((2027, 1, 1), (2026, 12, 31)),
            ((2028, 3, 1), (2028, 2, 29)),
        ):
            with self.subTest(local_date=local_date):
                local = datetime(*local_date, 6, tzinfo=hk)
                self.assertEqual(local.astimezone(ZoneInfo('UTC')),
                                 datetime(*utc_date, 22, tzinfo=ZoneInfo('UTC')))
        self.assertIn('每天香港时间 06:00 自动构建', (ROOT / 'README.md').read_text())

    def test_build_has_no_daily_date_gate(self):
        self.assertEqual(set(self.workflow['jobs']), {'openwrt', 'immortalwrt'})
        self.assertNotIn('needs', self.workflow['jobs']['openwrt'])
        self.assertNotIn('if', self.workflow['jobs']['openwrt'])
        self.assertEqual(self.workflow['jobs']['immortalwrt']['needs'], 'openwrt')
        self.assertFalse((ROOT / 'scripts/build_schedule.py').exists())

    def test_manual_dispatch_remains_available(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertIn('workflow_dispatch', triggers)
        self.assertIsNone(triggers['workflow_dispatch'])


if __name__ == '__main__':
    unittest.main()
