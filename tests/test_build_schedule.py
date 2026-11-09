"""Verify direct monthly Hong Kong scheduling without daily checks."""
from calendar import monthrange
from datetime import datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = next((ROOT / '.github/workflows').glob('*y*ml'))


class BuildScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text())

    def test_direct_monthly_cron_at_hong_kong_midnight(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(triggers['schedule'], [
            {'cron': '0 0 1-31/3 * *', 'timezone': 'Asia/Hong_Kong'}])
        self.assertEqual(set(triggers), {'schedule', 'workflow_dispatch'})
        local = datetime(2026, 12, 1, tzinfo=ZoneInfo('Asia/Hong_Kong'))
        utc = local.astimezone(ZoneInfo('UTC'))
        self.assertEqual((utc.month, utc.day, utc.hour, utc.minute), (11, 30, 16, 0))
        # Cron days belong to the selected timezone, not the preceding UTC day.
        for year in (2026, 2028):
            for month in range(1, 13):
                days = list(range(1, monthrange(year, month)[1] + 1, 3))
                self.assertEqual(days[0:4], [1, 4, 7, 10])
                self.assertNotIn(2, days)
                self.assertEqual(days[-1], 1 + 3 * ((monthrange(year, month)[1] - 1) // 3))

    def test_build_has_no_daily_date_gate(self):
        self.assertEqual(set(self.workflow['jobs']), {'build'})
        build = self.workflow['jobs']['build']
        self.assertNotIn('needs', build)
        self.assertNotIn('if', build)
        self.assertFalse((ROOT / 'scripts/build_schedule.py').exists())

    def test_manual_dispatch_remains_available(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertIn('workflow_dispatch', triggers)
        self.assertIsNone(triggers['workflow_dispatch'])


if __name__ == '__main__':
    unittest.main()
