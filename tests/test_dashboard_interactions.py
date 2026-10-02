from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from posture_track.alerts import AlertRecovery
from posture_track.dashboard import dashboard_bars, dashboard_hit
from posture_track.domain import Result, Temporal
from posture_track.storage import Recorder


class DashboardInteractionTests(unittest.TestCase):
    stats = {"date":"2026-10-02","days":[("2026-10-02",1800,600)],
             "month_days":[("2026-10-01",1800,0),("2026-10-02",1800,600)]}

    def test_bars_take_precedence_over_period_card(self):
        for period in ("week","month"):
            bars = dashboard_bars(1000,650,self.stats,period)
            bar = next(b for b in bars if b["score"] is not None)
            self.assertEqual(dashboard_hit(1000,650,self.stats,period,bar["x"],bar["base"]-10),bar["key"])
            self.assertEqual(dashboard_hit(1000,650,self.stats,period,22,500),"period")
        self.assertEqual(dashboard_hit(1000,650,self.stats,"week",20,120),"today")
        self.assertEqual(dashboard_hit(1000,650,self.stats,"week",300,350),"switch_week")

    def test_month_bars_group_calendar_weeks_and_weight_eligible_days(self):
        bars = dashboard_bars(1000,650,self.stats,"month")
        self.assertEqual(len(bars),5)
        self.assertEqual(bars[0]["first"].isoformat(),"2026-10-01")
        self.assertEqual(bars[0]["last"].isoformat(),"2026-10-04")
        self.assertAlmostEqual(bars[0]["score"],100*3600/4200)

    def test_drilldown_matches_date_and_week_and_clips_event_times(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Recorder(Path(folder)/"records.db")
            wall = datetime(2026,10,2,12,tzinfo=timezone(timedelta(hours=9)))
            recorder.db.executemany("INSERT INTO daily VALUES(?,?,?)",self.stats["month_days"])
            recorder.db.execute("INSERT INTO posture_events(start,end,name,view,version) VALUES(?,?,?,?,?)",
                                ("2026-10-01T23:59:58+09:00","2026-10-02T00:00:03+09:00","lean","front",1))
            periods = recorder.summary(wall)["periods"]
            self.assertEqual(periods["day:2026-10-02"]["targets"]["lean"]["seconds"],3)
            self.assertEqual(periods["range_week:2026-10-01"]["targets"]["lean"]["seconds"],5)
            self.assertAlmostEqual(periods["range_week:2026-10-01"]["score"],dashboard_bars(1000,650,self.stats,"month")[0]["score"])
            recorder.close()


class AlertRecoveryTests(unittest.TestCase):
    def test_visible_alert_keeps_sampling_and_unknown_does_not_dismiss(self):
        recovery = AlertRecovery()
        recovery.trigger("posture",0)
        self.assertEqual(recovery.interval(1,5),.2)
        self.assertEqual(recovery.interval(21,5),.5)
        self.assertTrue(recovery.fast(21))
        self.assertEqual(recovery.update(2,"unknown",{}),[])
        self.assertEqual(recovery.update(3,"good",{}),[])
        self.assertEqual(recovery.update(3.2,"unknown",{}),[])
        self.assertEqual(recovery.update(4,"good",{}),[])
        self.assertEqual(recovery.update(4.25,"good",{}),["posture"])
        self.assertEqual(recovery.interval(5,5),5)

    def test_touch_and_posture_recover_independently(self):
        recovery = AlertRecovery()
        recovery.trigger("posture",0)
        recovery.trigger("touch",0)
        self.assertEqual(recovery.update(1,"bad",{"face_touch":Result("good")}),["touch"])
        self.assertEqual(recovery.update(1.8,"bad",{"face_touch":Result("good")}),[])
        self.assertIn("posture",recovery.active)
        self.assertEqual(recovery.reset(),["posture"])
        self.assertFalse(recovery.fast(2))

    def test_fast_recovery_keeps_entry_hold_and_requires_sustained_correction(self):
        temporal = Temporal()
        for now in (0,.2,.4,1,2):
            self.assertNotEqual(temporal.update(20,10,now,10,fast_recovery=True).status,"bad")
        self.assertEqual(temporal.update(20,10,3.2,10,fast_recovery=True).status,"bad")
        for now in (3.4,3.6,3.8):
            self.assertNotEqual(temporal.update(0,10,now,10,fast_recovery=True).status,"good")
        for now in (4,4.2):
            result = temporal.update(0,10,now,10,fast_recovery=True)
        self.assertEqual(result.status,"good")

    def test_one_corrected_frame_does_not_end_bad_posture(self):
        temporal=Temporal()
        for now in (0,1,2,3.2):
            temporal.update(20,10,now,10)
        self.assertNotEqual(temporal.update(0,10,3.4,10,fast_recovery=True).status,"good")
        for now in (3.6,3.8,4,4.2):
            result=temporal.update(20,10,now,10,fast_recovery=True)
        self.assertEqual(result.status,"bad")


if __name__ == "__main__":
    unittest.main()
