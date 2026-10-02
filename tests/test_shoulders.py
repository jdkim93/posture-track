import unittest
import numpy as np

from posture_track.shoulders import ShoulderGuard


class ShoulderTests(unittest.TestCase):
    def test_only_visible_shoulder_tops_are_enough_for_posture(self):
        from posture_track.vision import extract
        pose, face, mask = self.fixture()
        pose[11], pose[12] = (470, 476, .70), (170, 476, .70)
        world = [(0, 0, 0)] * 33
        world[11], world[12] = (-.2, 0, 0), (.2, 0, 0)
        face[33], face[133], face[263], face[362] = (270,160),(290,160),(370,160),(350,160)
        guard = ShoulderGuard()
        checked, _ = guard.check(pose, face, mask, (480,640), 0)
        self.assertEqual(checked[11][2], 0)
        checked, _ = guard.check(pose, face, mask, (480,640), .5)
        observation = extract(.5, checked, face, [], np.eye(3), world, (480,640))
        self.assertEqual(observation.view, 'front')
        self.assertIn('upper_span', observation.metrics)
        self.assertIn('shoulder_angle', observation.metrics)

    def test_moderate_confidence_needs_consistent_points_even_away_from_edge(self):
        pose, face, mask = self.fixture()
        pose[11] = (470, 360, .70)
        guard = ShoulderGuard()
        self.assertEqual(guard.check(pose,face,mask,(480,640),0)[0][11][2],0)
        pose[11] = (520, 360, .70)
        self.assertEqual(guard.check(pose,face,mask,(480,640),.5)[0][11][2],0)
        self.assertEqual(guard.check(pose,face,mask,(480,640),1)[0][11][2],.70)

    def fixture(self):
        face = [(320, 180)] * 478
        face[10], face[152] = (320, 100), (320, 300)
        face[234], face[454] = (260, 180), (380, 180)
        pose = [(0, 0, 0)] * 33
        pose[11], pose[12] = (470, 360, .99), (170, 360, .99)
        return pose, face, np.ones((480, 640, 1), dtype=np.float32)

    def test_background_point_rejected_despite_high_confidence(self):
        pose, face, mask = self.fixture()
        mask[345:375, 455:485] = 0
        checked, details = ShoulderGuard().check(pose, face, mask, (480, 640), 0)
        self.assertEqual(checked[11][2], 0)
        self.assertFalse(details["11"]["accepted"])
        self.assertTrue(details["12"]["accepted"])

    def test_jump_requires_repeat_and_real_stable_movement_recovers(self):
        pose, face, mask = self.fixture()
        guard = ShoulderGuard()
        guard.check(pose, face, mask, (480, 640), 0)
        pose[11] = (520, 360, .99)
        checked, _ = guard.check(pose, face, mask, (480, 640), .5)
        self.assertEqual(checked[11][2], 0)
        checked, _ = guard.check(pose, face, mask, (480, 640), 1.5)
        self.assertEqual(checked[11][2], .99)

    def test_head_scale_change_does_not_create_false_jump(self):
        pose, face, mask = self.fixture()
        guard = ShoulderGuard()
        guard.check(pose, face, mask, (480, 640), 0)
        anchor = np.asarray((320, 180))
        pose = [tuple(anchor + (np.asarray(p[:2]) - anchor) * 1.15) + (p[2],) for p in pose]
        face = [tuple(anchor + (np.asarray(p) - anchor) * 1.15) for p in face]
        _, details = guard.check(pose, face, mask, (480, 640), .5)
        self.assertTrue(details["11"]["accepted"])
        self.assertTrue(details["12"]["accepted"])

    def test_missing_mask_and_implausible_position_are_unknown(self):
        pose, face, mask = self.fixture()
        checked, _ = ShoulderGuard().check(pose, face, None, (480, 640), 0)
        self.assertEqual(checked[11][2], 0)
        pose[11] = (470, 30, .99)
        checked, _ = ShoulderGuard().check(pose, face, mask, (480, 640), 0)
        self.assertEqual(checked[11][2], 0)

    def test_partial_visible_shoulder_requires_two_consistent_observations(self):
        pose, face, mask = self.fixture()
        pose[11] = (470, 476, .81)
        guard = ShoulderGuard()
        checked, _ = guard.check(pose, face, mask, (480, 640), 0)
        self.assertEqual(checked[11][2], 0)
        checked, details = guard.check(pose, face, mask, (480, 640), .5)
        self.assertEqual(checked[11][2], .81)
        self.assertTrue(details['11']['partial'])
        self.assertEqual(checked[11][:2], (470, 476))

    def test_partial_shoulder_does_not_accept_background_or_offscreen(self):
        pose, face, mask = self.fixture()
        pose[11] = (470, 486, .99)
        checked, _ = ShoulderGuard().check(pose, face, mask, (480, 640), 0)
        self.assertEqual(checked[11][2], 0)
        pose[11] = (470, 476, .81)
        mask[465:, 455:485] = 0
        guard = ShoulderGuard()
        for now in (0, .5):
            checked, _ = guard.check(pose, face, mask, (480, 640), now)
            self.assertEqual(checked[11][2], 0)

    def test_partial_sequence_resets_on_gap_and_missing_detection(self):
        pose, face, mask = self.fixture()
        pose[11] = (470, 476, .81)
        guard = ShoulderGuard()
        guard.check(pose, face, mask, (480, 640), 0, 1)
        checked, _ = guard.check(pose, face, mask, (480, 640), 2, 1)
        self.assertEqual(checked[11][2], 0)
        guard.check(pose, face, None, (480, 640), 2.5, 1)
        checked, _ = guard.check(pose, face, mask, (480, 640), 3, 1)
        self.assertEqual(checked[11][2], 0)


if __name__ == "__main__":
    unittest.main()
