from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from posture_track.domain import Result
from posture_track.storage import Recorder
from posture_track.dashboard import dashboard_regions


class RecordDetailTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.recorder = Recorder(Path(self.folder.name)/'records.sqlite3')
        self.wall = datetime(2026,10,2,12,tzinfo=timezone(timedelta(hours=9)))

    def tearDown(self):
        self.recorder.close()
        self.folder.cleanup()

    def test_continuous_violations_count_time_once_per_target(self):
        for now in (0,2,4):
            self.recorder.update(now,self.wall+timedelta(seconds=now),'bad','front',1,4,
                                 results={'lean':Result('bad'),'head_bend':Result('bad')})
        targets = self.recorder.summary(self.wall)['periods']['today']['targets']
        self.assertEqual(targets['lean']['seconds'],4)
        self.assertEqual(targets['head_bend']['seconds'],4)
        self.assertEqual(targets['lean']['episodes'],1)
        self.assertEqual(self.recorder.summary(self.wall)['today_bad'],4)

    def test_unknown_disabled_and_test_intervals_are_not_recorded(self):
        for now,status,write in ((0,'bad',True),(2,'unknown',True),(4,'bad',False),
                                 (6,'bad',True),(8,'bad',True)):
            self.recorder.update(now,self.wall+timedelta(seconds=now),'bad','front',1,4,
                                 allow_write=write,results={'lean':Result(status)})
        target = self.recorder.summary(self.wall)['periods']['today']['targets']['lean']
        self.assertEqual(target['seconds'],2)
        self.assertEqual(target['episodes'],1)

    def test_event_crossing_midnight_is_clipped_by_period(self):
        start = self.wall.replace(hour=23,minute=59,second=59)-timedelta(days=1)
        for now in (0,2,4):
            self.recorder.update(now,start+timedelta(seconds=now),'bad','front',1,4,
                                 results={'lean':Result('bad')})
        periods = self.recorder.summary(self.wall)['periods']
        self.assertEqual(periods['today']['targets']['lean']['seconds'],3)
        self.assertEqual(periods['week']['targets']['lean']['seconds'],4)
        self.assertEqual(periods['month']['targets']['lean']['seconds'],4)

    def test_month_and_week_use_weighted_qualified_days(self):
        self.recorder.db.executemany('INSERT INTO daily VALUES(?,?,?)',
                                    [('2026-09-29',1800,0),('2026-10-01',3600,0),
                                     ('2026-10-02',900,900),('2026-10-03',90,10)])
        summary = self.recorder.summary(self.wall+timedelta(days=1))
        self.assertAlmostEqual(summary['week'],87.5)
        self.assertAlmostEqual(summary['month'],100*4500/5400)
        self.assertEqual(summary['periods']['today']['score'],90)
        self.assertEqual(summary['periods']['month']['qualified_days'],2)

    def test_legacy_scores_are_preserved_without_invented_target_times(self):
        self.recorder.db.execute('INSERT INTO daily VALUES(?,?,?)',('2026-10-02',1800,200))
        detail = self.recorder.summary(self.wall)['periods']['today']
        self.assertEqual(detail['score'],90)
        self.assertIsNone(detail['details_since'])
        self.assertEqual(detail['targets']['lean']['seconds'],0)

    def test_day_week_month_click_regions_are_separate(self):
        for width,height in ((800,560),(1200,800)):
            regions = dashboard_regions(width,height)
            for key in ('today','week','month','switch_week','switch_month','plot'):
                x1,y1,x2,y2=regions[key]
                center=((x1+x2)/2,(y1+y2)/2)
                matched=[name for name,(a,b,c,d) in regions.items() if a<=center[0]<=c and b<=center[1]<=d]
                self.assertEqual(matched,[key])
