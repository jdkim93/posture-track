import unittest
from types import SimpleNamespace

import numpy as np

from posture_track.orientation import CameraOrientation, rotate_frame, upright_score


def face_result(dx=0, dy=.4, count=1):
    points = [SimpleNamespace(x=.5, y=.2) for _ in range(153)]
    points[152] = SimpleNamespace(x=.5 + dx, y=.2 + dy)
    return SimpleNamespace(face_landmarks=[points] * count)


class OrientationTests(unittest.TestCase):
    def test_multiple_people_never_scan_a_wrong_upright_candidate(self):
        orientation = CameraOrientation()
        frame = np.arange(180).reshape(6,10,3)
        calls = []
        def probe(candidate):
            calls.append(candidate.shape)
            return face_result(count=2) if np.array_equal(candidate,frame) else face_result()
        for now in (1,2,3):
            corrected,ready,changed = orientation.correct(frame,probe,now,10)
            self.assertFalse(ready)
            self.assertFalse(changed)
            self.assertEqual(orientation.turns,0)
            np.testing.assert_array_equal(corrected,frame)
        self.assertEqual(len(calls),3)

    def test_frozen_rotation_keeps_axes_and_clears_pending_switch(self):
        orientation = CameraOrientation()
        orientation.turns,orientation.candidate,orientation.last = 3,1,0
        frame = np.arange(180).reshape(6,10,3)
        result = face_result(count=0)
        result.freeze_rotation = True
        corrected,ready,changed = orientation.correct(frame,lambda _:result,1,10)
        self.assertTrue(ready)
        self.assertFalse(changed)
        self.assertEqual(orientation.turns,3)
        self.assertIsNone(orientation.candidate)
        np.testing.assert_array_equal(corrected,rotate_frame(frame,3))

    def test_all_camera_rotations_restore_identical_pixels(self):
        upright = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
        for camera_turns in range(4):
            with self.subTest(camera_turns=camera_turns):
                orientation = CameraOrientation()
                raw = rotate_frame(upright, camera_turns)
                def probe(frame):
                    return face_result(count=int(np.array_equal(frame, upright)))
                first, ready, changed = orientation.correct(raw, probe, 1, 10)
                if camera_turns:
                    self.assertFalse(ready)
                    self.assertFalse(changed)
                corrected, ready, changed = orientation.correct(raw, probe, 2, 10)
                self.assertTrue(ready)
                np.testing.assert_array_equal(corrected, upright)
                self.assertTrue(corrected.flags.c_contiguous)
                self.assertEqual(orientation.turns, (-camera_turns) % 4)

    def test_face_tilt_does_not_trigger_quarter_turn(self):
        orientation = CameraOrientation()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        _, ready, changed = orientation.correct(frame, lambda _: face_result(.1, .4), 1, 10)
        self.assertTrue(ready)
        self.assertFalse(changed)
        self.assertEqual(orientation.turns, 0)

    def test_ambiguous_missing_and_multiple_faces_do_not_switch(self):
        for result in (face_result(dy=-.4), face_result(count=0), face_result(count=2)):
            orientation = CameraOrientation()
            _, ready, changed = orientation.correct(np.zeros((20, 30, 3)), lambda _: result, 1, 10)
            self.assertFalse(ready)
            self.assertFalse(changed)
        orientation = CameraOrientation()
        frame = np.zeros((20, 30, 3))
        calls = iter([face_result(count=0), face_result(), face_result(), face_result(count=0)])
        self.assertFalse(orientation.correct(frame, lambda _: next(calls), 1, 10)[1])

    def test_gap_and_duplicate_timestamp_cannot_confirm_switch(self):
        upright = np.arange(72).reshape(4, 6, 3)
        raw = rotate_frame(upright, 1)
        def probe(frame):
            return face_result(count=int(np.array_equal(frame, upright)))
        orientation = CameraOrientation()
        for now in (1, 1, 20):
            self.assertFalse(orientation.correct(raw, probe, now, 10)[1])
        self.assertTrue(orientation.correct(raw, probe, 21, 10)[1])
        self.assertFalse(orientation.correct(upright, probe, 22, 10)[1])
        self.assertTrue(orientation.correct(upright, probe, 23, 10)[1])
        self.assertEqual(orientation.turns, 0)

    def test_nonfinite_face_is_rejected(self):
        self.assertEqual(upright_score(face_result(float('nan')), (480, 640, 3)), 0)
