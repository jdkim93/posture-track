import math
import tempfile
import unittest
from pathlib import Path

from posture_track.config import Settings
from posture_track.domain import AlertTimer, Baseline, Calibration, Evaluator, Observation, Profiles, Result, overall
from posture_track.validation import Trial
from posture_track.vision import classify_view, valid


class ImprovementTests(unittest.TestCase):
    def test_ten_second_alert_timing_and_persistence(self):
        s = Settings(alert_seconds=10)
        timer = AlertTimer()
        for now in range(0, 10, 2):
            self.assertFalse(timer.update(True, now, s))
        self.assertTrue(timer.update(True, 10, s))
        self.assertFalse(timer.update(True, 12, s))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            s.save(path)
            self.assertEqual(Settings.load(path).alert_seconds, 10)

    def test_occlusion_is_unknown_not_unsupported_or_good(self):
        s = Settings()
        b = Baseline("front", {"pitch": 0, "roll": 0, "shoulder_angle": 0}, {})
        e = Evaluator()
        for now in (0, 2, 4):
            results = e.evaluate(Observation(now, "front", {"pitch": 0, "roll": 0}), b, s)
        self.assertEqual(results["uneven_shoulders"].status, "unknown")
        self.assertEqual(overall(results, s), "unknown")

    def test_side_still_excludes_structurally_unsupported_axes(self):
        b = Baseline("side_right", {"pitch": 0, "forward": .1, "side_scale": 100, "side_pair": 7, "torso_pitch": 0}, {})
        obs = Observation(0, "side_right", {"pitch": 0, "forward": .1, "forward_pixels": 10, "side_scale": 100, "side_pair": 7, "torso_pitch": 0})
        r = Evaluator().evaluate(obs, b, Settings())
        self.assertEqual(r["lean"].status, "unsupported")
        self.assertEqual(overall(r, Settings()), "good")

    def test_pair_switch_and_nonfinite_values_reject(self):
        b = Baseline("side_right", {"forward": .1, "side_scale": 100, "side_pair": 7}, {})
        r = Evaluator().evaluate(Observation(0, "side_right", {"forward": 1, "forward_pixels": 100, "side_scale": 100, "side_pair": 8, "pitch": math.nan}), b, Settings())
        self.assertEqual(r["forward_head"].status, "unknown")
        self.assertEqual(r["head_bend"].status, "unknown")
        self.assertFalse(valid([(1, 1, math.inf)], 0, 640, 480))
        self.assertEqual(classify_view(math.nan, 0), "unknown")

    def test_calibration_tolerates_isolated_missing_metric(self):
        c = Calibration(0, "front")
        for i in range(30):
            metrics = {"pitch": 0, "roll": 0}
            if i != 10:
                metrics["shoulder_angle"] = 0
            c.add(Observation(3 + i * .3, "front", metrics))
        self.assertIn("shoulder_angle", c.finish("camera").values)

    def test_calibration_rejects_discontinuous_samples(self):
        c = Calibration(0, "front")
        for i in range(20):
            c.add(Observation(3 + i * .3, "front", {"pitch": 0, "roll": 0}))
        c.add(Observation(30, "front", {"pitch": 0, "roll": 0}))
        with self.assertRaises(ValueError):
            c.finish("camera")

    def test_multiple_profiles_commit_and_preserve_others(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            p = Profiles(path)
            p.save(Baseline("front", {"roll": 0}, {}))
            p.save_many([Baseline("side_left", {"forward": 0}, {}), Baseline("side_right", {"forward": 0}, {})])
            self.assertEqual(set(Profiles(path).items), {"front", "side_left", "side_right"})

    def test_trial_unknown_coverage_and_condition_change(self):
        t = Trial("head_bend", "bad", 0, "front", 1)
        for now, status in ((0, "good"), (5, "unknown"), (7, "good"), (9, "bad")):
            t.observe(now, "front", 1, {"head_bend": Result(status)})
        report = t.report()
        self.assertAlmostEqual(report["coverage"], 2 / 3)
        self.assertEqual(report["agreement"], .5)
        with self.assertRaises(ValueError):
            t.observe(11, "side_right", 1, {"head_bend": Result("bad")})


if __name__ == "__main__":
    unittest.main()
