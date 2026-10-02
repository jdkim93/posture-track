from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from posture_track.config import Settings, atomic_json
from posture_track.domain import AlertTimer
from posture_track.reminders import Reminder, ReminderBook


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)/"reminders.json"
        self.book = ReminderBook(self.path)
        self.now = datetime(2026,10,2,9,tzinfo=timezone(timedelta(hours=9)))

    def tearDown(self):
        self.folder.cleanup()

    def test_examples_are_disabled_silent_and_persisted(self):
        loaded = ReminderBook(self.path)
        self.assertEqual([(r.title,r.interval_minutes) for r in loaded.items],[("물 마시기",120),("스트레칭",60)])
        self.assertTrue(all(not r.enabled and r.muted for r in loaded.items))
        self.assertEqual(loaded.due(self.now+timedelta(days=5)),[])

    def test_interval_exact_deadline_and_restart_do_not_duplicate(self):
        self.book.upsert(replace(self.book.items[0],enabled=True),self.now)
        due = self.now+timedelta(hours=2)
        self.assertEqual(self.book.due(due-timedelta(seconds=1)),[])
        self.assertEqual([r.id for r in self.book.due(due)],["water"])
        restarted = ReminderBook(self.path)
        self.assertEqual(restarted.due(due),[])
        self.assertEqual([r.id for r in restarted.due(due+timedelta(hours=2))],["water"])

    def test_daily_clock_time_and_next_day(self):
        alarm = Reminder("daily","눈 쉬기",mode="daily",time="10:30",enabled=True)
        self.book.upsert(alarm,self.now)
        at = self.now.replace(hour=10,minute=30)
        self.assertEqual(self.book.due(at-timedelta(seconds=1)),[])
        self.assertEqual([r.id for r in self.book.due(at)],["daily"])
        self.assertEqual(self.book.due(at+timedelta(seconds=1)),[])
        self.assertEqual([r.id for r in self.book.due(at+timedelta(days=1))],["daily"])

    def test_elapsed_daily_time_waits_until_tomorrow(self):
        self.book.upsert(Reminder("daily","휴식",mode="daily",time="08:00",enabled=True),self.now)
        alarm = self.book.items[-1]
        self.assertEqual(datetime.fromisoformat(alarm.next_due).date(),self.now.date()+timedelta(days=1))

    def test_suspend_skips_missed_intervals_without_alarm_storm(self):
        self.book.upsert(replace(self.book.items[0],enabled=True),self.now)
        later = self.now+timedelta(hours=10,minutes=30)
        self.assertEqual(len(self.book.due(later)),1)
        self.assertEqual(self.book.due(later),[])
        self.assertEqual(datetime.fromisoformat(self.book.items[0].next_due).hour,21)

    def test_disable_and_enable_restarts_interval_but_title_does_not(self):
        self.book.upsert(replace(self.book.items[0],enabled=True),self.now)
        deadline = self.book.items[0].next_due
        self.book.upsert(replace(self.book.items[0],title="물 한 잔",muted=False),self.now+timedelta(minutes=5))
        self.assertEqual(self.book.items[0].next_due,deadline)
        self.book.upsert(replace(self.book.items[0],enabled=False),self.now)
        self.assertIsNone(self.book.items[0].next_due)
        self.assertEqual(self.book.due(self.now+timedelta(days=10)),[])
        self.book.upsert(replace(self.book.items[0],enabled=True),self.now+timedelta(minutes=30))
        self.assertEqual(datetime.fromisoformat(self.book.items[0].next_due),self.now+timedelta(hours=2,minutes=30))

    def test_edit_interval_reschedules_and_delete_persists(self):
        self.book.upsert(replace(self.book.items[0],enabled=True),self.now)
        self.book.upsert(replace(self.book.items[0],interval_minutes=60),self.now+timedelta(minutes=5))
        self.assertEqual(datetime.fromisoformat(self.book.items[0].next_due),self.now+timedelta(hours=1,minutes=5))
        self.book.remove("water")
        self.assertNotIn("water",[r.id for r in ReminderBook(self.path).items])

    def test_invalid_times_and_intervals_are_rejected_without_changes(self):
        original = self.path.read_text(encoding="utf-8")
        for item in (Reminder("bad","",enabled=True),Reminder("bad","test",time="24:00"),
                     Reminder("bad","test",time="9:00"),Reminder("bad","test",interval_minutes=0),
                     Reminder("bad","test",interval_minutes=10081)):
            with self.assertRaises(ValueError):
                self.book.upsert(item,self.now)
        self.assertEqual(self.path.read_text(encoding="utf-8"),original)


class SilentDefaultTests(unittest.TestCase):
    def test_default_and_old_preferences_are_silent(self):
        self.assertTrue(Settings().muted)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"settings.json"
            atomic_json(path,{"muted":False})
            self.assertTrue(Settings.load(path).muted)
            settings = Settings(muted=False)
            settings.save(path)
            self.assertFalse(Settings.load(path).muted)

    def test_muting_sound_keeps_visual_posture_alarm(self):
        settings = Settings(performance="High",alert_seconds=10,muted=True)
        timer = AlertTimer()
        for i in range(20):
            self.assertFalse(timer.update(True,i*.5,settings))
        self.assertFalse(timer.update(True,9.5,settings))
        self.assertTrue(timer.update(True,10,settings))


if __name__=="__main__":
    unittest.main()
