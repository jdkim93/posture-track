import tempfile
import unittest
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from posture_track.config import Settings, ALERT_DELAYS
from posture_track.domain import AlertTimer, Baseline, Calibration, Evaluator, Observation, Temporal, line_delta, overall
from posture_track.storage import Recorder


class StateTests(unittest.TestCase):
    def test_bad_requires_stability_and_loss_breaks_continuity(self):
        state = Temporal()
        self.assertEqual(state.update(30, 15, 0, 4).status, "candidate")
        self.assertEqual(state.update(30, 15, 2, 4).status, "candidate")
        self.assertEqual(state.update(30, 15, 4, 4).status, "bad")
        self.assertEqual(state.update(30, 15, 20, 4).status, "candidate")
        self.assertIsNone(state.bad_since)

    def test_recovery_requires_stability(self):
        state = Temporal()
        for now in (0, 2, 4):
            state.update(30, 15, now, 4)
        values = [state.update(0, 15, now, 4).status for now in (6, 8, 10, 12, 14)]
        self.assertIn("recovering", values)
        self.assertEqual(values[-1], "good")

    def test_line_angle_wrap(self):
        self.assertAlmostEqual(line_delta(-179, 179), 2)

    def test_toggle_cancels_and_does_not_backdate(self):
        settings = Settings()
        evaluator = Evaluator()
        profile = Baseline("front", {"pitch": 0}, {"pitch": 0})
        for now in (0, 2, 4):
            results = evaluator.evaluate(Observation(now, "front", {"pitch": 30}), profile, settings)
        self.assertEqual(results["head_bend"].status, "bad")
        settings.enabled["head_bend"] = False
        settings.version += 1
        results = evaluator.evaluate(Observation(6, "front", {"pitch": 30}), profile, settings)
        self.assertEqual(results["head_bend"].status, "off")
        settings.enabled["head_bend"] = True
        settings.version += 1
        results = evaluator.evaluate(Observation(8, "front", {"pitch": 30}), profile, settings)
        self.assertEqual(results["head_bend"].status, "candidate")

    def test_all_off_and_behavior_is_not_posture(self):
        settings = Settings()
        settings.enabled = {key: False for key in settings.enabled}
        settings.enabled["face_touch"] = True
        evaluator = Evaluator()
        results = evaluator.evaluate(Observation(0, "front", {"touch_distance": 0}), None, settings)
        self.assertEqual(overall(results, settings), "disabled")

    def test_unknown_does_not_create_normal(self):
        settings = Settings()
        evaluator = Evaluator()
        results = evaluator.evaluate(Observation(0), None, settings)
        self.assertEqual(overall(results, settings), "unknown")

    def test_side_scale_change_is_unknown(self):
        profile = Baseline("side_right", {"forward": .1, "side_scale": 100}, {"forward": 0})
        results = Evaluator().evaluate(Observation(0, "side_right", {"forward": 1, "forward_pixels": 100, "side_scale": 200}), profile, Settings())
        self.assertEqual(results["forward_head"].status, "unknown")

    def test_default_twenty_second_alert_and_ten_minute_repeat(self):
        settings = Settings()
        timer = AlertTimer()
        for now in range(0, 20, 2):
            self.assertFalse(timer.update(True, now, settings))
        self.assertTrue(timer.update(True, 20, settings))
        for now in range(22, 620, 2):
            self.assertFalse(timer.update(True, now, settings))
        self.assertTrue(timer.update(True, 620, settings))
        self.assertFalse(timer.update(False, 622, settings))
        self.assertFalse(timer.update(True, 624, settings))

    def test_fresh_defaults_and_user_changes_persist(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'settings.json'
            fresh=Settings.load(path)
            self.assertEqual(fresh.interval,2)
            self.assertEqual(fresh.alert_seconds,20)
            fresh.performance='High'
            fresh.alert_seconds=120
            fresh.save(path)
            restored=Settings.load(path)
            self.assertEqual(restored.interval,.5)
            self.assertEqual(restored.alert_seconds,120)

    def test_alert_gap_breaks_continuity(self):
        timer = AlertTimer()
        timer.update(True, 0, Settings())
        self.assertFalse(timer.update(True, 1000, Settings()))

    def test_short_alert_value_is_a_persistent_production_option(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            settings = Settings(alert_seconds=10)
            settings.save(path)
            self.assertEqual(Settings.load(path).alert_seconds, 10)

    def test_all_official_alert_options_survive_restart(self):
        self.assertEqual(list(ALERT_DELAYS),['10초','20초','1분','2분','5분','10분','20분'])
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'settings.json'
            for seconds in ALERT_DELAYS.values():
                Settings(alert_seconds=seconds).save(path)
                self.assertEqual(Settings.load(path).alert_seconds,seconds)

    def test_calibration_does_not_accept_one_frame(self):
        calibration = Calibration(0, "front")
        calibration.add(Observation(4, "front", {"pitch": 0, "roll": 0}))
        with self.assertRaises(ValueError):
            calibration.finish("camera")

    def test_network_guard_rejects_connections(self):
        code = "from posture_track.privacy import enforce_local_only; enforce_local_only(); import socket; socket.create_connection(('127.0.0.1', 9))"
        run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("external network connections are disabled", run.stderr)


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.recorder = Recorder(Path(self.directory.name) / "records.sqlite3")

    def tearDown(self):
        self.recorder.close()
        self.directory.cleanup()

    def test_midnight_split(self):
        start = datetime(2026, 10, 1, 23, 59, 59, tzinfo=timezone(timedelta(hours=9)))
        self.recorder.update(0, start, "good", "front", 1, 4)
        self.recorder.update(2, start + timedelta(seconds=2), "good", "front", 1, 4)
        rows = list(self.recorder.db.execute("SELECT day,good FROM daily ORDER BY day"))
        self.assertEqual(rows, [("2026-10-01", 1), ("2026-10-02", 1)])

    def test_unknown_and_setting_change_not_bridged(self):
        start = datetime.now().astimezone()
        for now, state, version in ((0, "bad", 1), (2, "unknown", 1), (4, "bad", 1), (6, "bad", 2)):
            self.recorder.update(now, start + timedelta(seconds=now), state, "front", version, 4)
        self.assertEqual(list(self.recorder.db.execute("SELECT * FROM daily")), [])

    def test_clock_jump_not_allocated(self):
        start = datetime.now().astimezone()
        self.recorder.update(0, start, "good", "front", 1, 4)
        self.recorder.update(2, start + timedelta(hours=1), "good", "front", 1, 4)
        self.assertEqual(list(self.recorder.db.execute("SELECT * FROM daily")), [])

    def test_demo_never_writes_intervals(self):
        start = datetime.now().astimezone()
        self.recorder.update(0, start, "good", "front", 1, 4, allow_write=False)
        self.recorder.update(2, start + timedelta(seconds=2), "good", "front", 1, 4, allow_write=False)
        self.assertEqual(list(self.recorder.db.execute("SELECT * FROM daily")), [])

    def test_behavior_remains_separate_and_counts_contiguous_episode(self):
        start = datetime.now().astimezone()
        for now in (0, 2, 4):
            self.recorder.update(now, start + timedelta(seconds=now), "disabled", "front", 1, 4, touch=True)
        summary = self.recorder.summary(start)
        self.assertEqual(summary["today_good"], 0)
        self.assertEqual(summary["today_bad"], 0)
        self.assertEqual(summary["touch_episodes"], 1)
        self.assertEqual(summary["touch_seconds"], 4)


if __name__ == "__main__":
    unittest.main()
