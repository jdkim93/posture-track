import unittest

from posture_track.domain import Observation, Result
from posture_track.feedback import posture_feedback


class FeedbackTests(unittest.TestCase):
    def test_candidate_and_confirmed_bad_are_distinct(self):
        title, _, color = posture_feedback({'lean':Result('candidate')})
        self.assertIn('확인 중',title)
        self.assertEqual(color,'#d0b28d')
        title, detail, color = posture_feedback({'lean':Result('bad')})
        self.assertIn('이탈',title)
        self.assertIn('기울임',detail)
        self.assertEqual(color,'#e59c9e')

    def test_uncalibrated_and_unknown_never_show_good(self):
        self.assertIn('등록',posture_feedback({'lean':Result('uncalibrated')})[0])
        self.assertNotIn('범위',posture_feedback({'lean':Result('unknown')})[0])
        self.assertIn('일부',posture_feedback({'lean':Result('good'),'head_bend':Result('unknown')})[0])

    def test_pause_uses_actual_tracking_reason(self):
        obs = Observation(0,reasons={'subject':'두 사람이 겹쳐 보여요'},quality={'subject_tracking':'waiting'})
        title, detail, _ = posture_feedback({'lean':Result('unknown')},obs)
        self.assertIn('멈춤',title)
        self.assertIn('겹쳐',detail)

    def test_supported_good_and_face_touch_are_separate(self):
        self.assertIn('범위',posture_feedback({'lean':Result('good'),'slouch':Result('unsupported')})[0])
        title, detail, _ = posture_feedback({'lean':Result('good'),'face_touch':Result('bad')})
        self.assertIn('얼굴',title)
        self.assertIn('별도',detail)
