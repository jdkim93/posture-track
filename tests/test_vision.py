import math
import unittest

import numpy as np

from posture_track.vision import angles, classify_view, extract, wrist_anchor


class GeometryTests(unittest.TestCase):
    def test_boundary_wrist_requires_high_confidence_and_small_margin(self):
        pose = [(0, 0, 0)] * 33
        pose[15] = (400, 486, .9)
        self.assertTrue(wrist_anchor(pose, 15, 640, 480)[1])
        pose[15] = (400, 486, .8)
        self.assertIsNone(wrist_anchor(pose, 15, 640, 480))
        pose[15] = (400, 510, .99)
        self.assertIsNone(wrist_anchor(pose, 15, 640, 480))

    def test_boundary_anchor_cannot_associate_an_offscreen_hand_wrist(self):
        pose = [(0, 0, 0)] * 33
        pose[15] = (400, 486, .9)
        face = [(300, 220)] * 478
        face[10], face[152] = (300, 100), (300, 300)
        hand = [(400, 485)] * 21
        obs = extract(0, pose, face, [hand], None, [], (480, 640, 3))
        self.assertNotIn("touch_distance", obs.metrics)

    def test_visible_distant_hand_is_measurable_with_boundary_pose_wrist(self):
        pose = [(0, 0, 0)] * 33
        pose[15] = (400, 486, .9)
        face = [(300, 220)] * 478
        face[10], face[152] = (300, 100), (300, 300)
        hand = [(400, 400)] * 21
        hand[0] = (400, 472)
        obs = extract(0, pose, face, [hand], None, [], (480, 640, 3))
        self.assertGreater(obs.metrics["touch_distance"], .06)
        self.assertTrue(obs.quality["wrist_boundary_association"])

    def test_monitor_direction_follows_head_when_shoulders_stay_front(self):
        self.assertEqual(classify_view(85, 0), "side_right")
        self.assertEqual(classify_view(40, 0), "oblique_right")
        self.assertEqual(classify_view(-40, 0), "oblique_left")
        self.assertEqual(classify_view(30, 0), "oblique_right")
        self.assertEqual(classify_view(85, 80), "side_right")
        self.assertEqual(classify_view(-40, 45), "oblique_left")

    def test_rotation_angles(self):
        angle = math.radians(30)
        rotation = [[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]]
        pitch, yaw, roll = angles(rotation)
        self.assertAlmostEqual(pitch, 30)
        self.assertAlmostEqual(yaw, 0)
        self.assertAlmostEqual(roll, 0)

    def test_missing_subject_is_not_valid_front(self):
        obs = extract(0, [], [], [], None, [], (480, 640, 3))
        self.assertEqual(obs.view, "unknown")
        self.assertNotIn("touch_distance", obs.metrics)

    def test_front_horizontal_shift_not_forward_head(self):
        pose = [(0, 0, 0)] * 33
        pose[11], pose[12] = (200, 280, 1), (440, 280, 1)
        pose[7], pose[8] = (280, 180, 1), (390, 180, 1)
        world = [(0, 0, 0)] * 33
        world[11], world[12] = (-.2, 0, 0), (.2, 0, 0)
        obs = extract(0, pose, [], [], np.eye(3).tolist(), world, (480, 640, 3))
        self.assertEqual(obs.view, "front")
        self.assertNotIn("forward", obs.metrics)


if __name__ == "__main__":
    unittest.main()
