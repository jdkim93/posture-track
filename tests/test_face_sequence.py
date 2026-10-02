import unittest

from posture_track.config import Settings
from posture_track.domain import AlertTimer, ConsecutiveProximity, Evaluator, Observation
from posture_track.alerts import AlertRecovery


class FaceSequenceTests(unittest.TestCase):
    def test_two_new_near_observations_for_each_performance(self):
        for mode in ("Low", "Mid", "High"):
            with self.subTest(mode=mode):
                settings = Settings(performance=mode)
                evaluator = Evaluator()
                first = evaluator.evaluate(Observation(0, "front", {"touch_distance": .01}), None, settings)
                second = evaluator.evaluate(Observation(settings.interval, "front", {"touch_distance": .02}), None, settings)
                self.assertEqual(first["face_touch"].status, "candidate")
                self.assertEqual(second["face_touch"].status, "bad")
                self.assertEqual(second["face_touch"].held, 0)

    def test_far_observation_clears_sequence_and_confirmation(self):
        state = ConsecutiveProximity()
        self.assertEqual(state.update(0, .06, 0, 4).status, "candidate")
        self.assertEqual(state.update(.2, .06, 2, 4).status, "good")
        self.assertEqual(state.update(0, .06, 4, 4).status, "candidate")
        self.assertEqual(state.update(0, .06, 6, 4).status, "bad")
        self.assertEqual(state.update(.2, .06, 8, 4).status, "good")

    def test_missing_hand_breaks_consecutive_observations(self):
        settings = Settings()
        evaluator = Evaluator()
        for now in (0, 2):
            evaluator.evaluate(Observation(now, "front", {"touch_distance": 0}), None, settings)
        lost = evaluator.evaluate(Observation(4, "front"), None, settings)
        returned = evaluator.evaluate(Observation(6, "front", {"touch_distance": 0}), None, settings)
        self.assertEqual(lost["face_touch"].status, "unknown")
        self.assertEqual(returned["face_touch"].status, "candidate")

    def test_duplicate_frames_and_long_gaps_do_not_confirm(self):
        state = ConsecutiveProximity()
        state.update(0, .06, 0, 1)
        self.assertEqual(state.update(0, .06, 0, 1).status, "candidate")
        self.assertEqual(state.update(0, .06, 5, 1).status, "candidate")
        self.assertEqual(state.update(0, .06, 5.5, 1).status, "bad")

    def test_alert_wait_starts_after_confirmation(self):
        settings = Settings(performance="High", alert_seconds=10)
        state, timer = ConsecutiveProximity(), AlertTimer()
        for index in range(21):
            now = index * .5
            result = state.update(0, .06, now, 1)
            self.assertFalse(timer.update(result.status == "bad", now, settings))
        result = state.update(0, .06, 10.5, 1)
        self.assertTrue(timer.update(result.status == "bad", 10.5, settings))

    def test_lowered_hand_closes_old_alert_and_requires_ten_new_seconds(self):
        settings = Settings(performance="High",alert_seconds=10)
        evaluator,timer,recovery = Evaluator(),AlertTimer(),AlertRecovery()
        def sample(now,distance):
            metrics = {} if distance is None else {"touch_distance":distance}
            result = evaluator.evaluate(Observation(now,"front",metrics),None,settings)["face_touch"]
            sent = timer.update(result.status=="bad",now,settings)
            if sent:
                recovery.trigger("touch",now)
            cleared = recovery.update(now,"unknown",{"face_touch":result})
            return sent,cleared,result
        for i in range(21):
            self.assertFalse(sample(i*.5,0)[0])
        self.assertTrue(sample(10.5,0)[0])
        self.assertEqual(sample(10.7,.2)[1],["touch"])
        self.assertIsNone(timer.started)
        self.assertFalse(sample(11,0)[0])
        self.assertFalse(sample(11.2,0)[0])
        for i in range(1,50):
            self.assertFalse(sample(11.2+i*.2,0)[0])
            self.assertNotIn("touch",recovery.active)
        self.assertTrue(sample(21.3,0)[0])

    def test_lost_hand_ends_notification_without_claiming_recovery(self):
        settings = Settings(performance="High",alert_seconds=10)
        evaluator,timer,recovery = Evaluator(),AlertTimer(),AlertRecovery()
        for i in range(22):
            now = i*.5
            result = evaluator.evaluate(Observation(now,"front",{"touch_distance":0}),None,settings)["face_touch"]
            if timer.update(result.status=="bad",now,settings):
                recovery.trigger("touch",now)
        missing = evaluator.evaluate(Observation(10.7,"front"),None,settings)["face_touch"]
        self.assertEqual(missing.status,"unknown")
        self.assertFalse(timer.update(missing.status=="bad",10.7,settings))
        self.assertEqual(recovery.update(10.7,"unknown",{"face_touch":missing}),["touch"])
        for i in range(15):
            now = 11+i*.2
            result = evaluator.evaluate(Observation(now,"front",{"touch_distance":0}),None,settings)["face_touch"]
            self.assertFalse(timer.update(result.status=="bad",now,settings))
            self.assertNotIn("touch",recovery.active)


if __name__ == "__main__":
    unittest.main()
