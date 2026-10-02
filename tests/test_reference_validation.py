import unittest

from posture_track.domain import Result
from posture_track.validation import ReferenceTrial


class ReferenceTests(unittest.TestCase):
    def test_behavior_unknown_remains_separate_from_posture_reference(self):
        trial = ReferenceTrial(0, "front", 1, ["head_bend", "face_touch"], ["face_touch"])
        trial.observe(6, "front", 1, {"head_bend": Result("good"), "face_touch": Result("unknown")})
        report = trial.report()
        self.assertEqual(report["counts"], {"good": 1})
        self.assertEqual(report["per_target"]["face_touch"]["counts"], {"unknown": 1})

    def test_one_interval_records_all_enabled_postures(self):
        trial = ReferenceTrial(0, "front", 1, ["head_bend", "lean", "slouch"])
        results = {"head_bend": Result("good", 2, 15), "lean": Result("bad", 12, 10),
                   "slouch": Result("unsupported")}
        trial.observe(6, "front", 1, results)
        report = trial.report()
        self.assertEqual(report["counts"], {"bad": 1})
        self.assertEqual(report["per_target"]["head_bend"]["counts"], {"good": 1})
        self.assertEqual(report["per_target"]["lean"]["counts"], {"bad": 1})
        self.assertEqual(report["per_target"]["slouch"]["status_counts"], {"unsupported": 1})

    def test_unsupported_not_counted_as_normal_and_occlusion_is_unknown(self):
        trial = ReferenceTrial(0, "front", 1, ["head_bend", "lean"])
        trial.observe(6, "front", 1, {"head_bend": Result("good"), "lean": Result("unknown")})
        self.assertEqual(trial.report()["counts"], {"unknown": 1})
        trial = ReferenceTrial(0, "front", 1, ["head_bend", "slouch"])
        trial.observe(6, "front", 1, {"head_bend": Result("good"), "slouch": Result("unsupported")})
        self.assertEqual(trial.report()["counts"], {"good": 1})

    def test_direction_change_cancels_common_reference(self):
        trial = ReferenceTrial(0, "front", 1, ["head_bend"])
        with self.assertRaises(ValueError):
            trial.observe(6, "side_left", 1, {"head_bend": Result("good")})


if __name__ == "__main__":
    unittest.main()
