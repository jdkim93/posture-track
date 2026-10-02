import unittest
import numpy as np

from posture_track.config import Settings
from posture_track.domain import Baseline, Evaluator
from posture_track.vision import FACE_REGION, extract


class FingerTouchTests(unittest.TestCase):
    def setUp(self):
        self.face=[(320,220)]*478
        for index,angle in zip(FACE_REGION,np.linspace(-np.pi/2,3*np.pi/2,len(FACE_REGION),endpoint=False)):
            self.face[index]=(320+80*np.cos(angle),220+120*np.sin(angle))
        self.face[10],self.face[152]=(320,100),(320,340)
        # Model wrist and palm unseen, only three index-finger joints visible.
        self.hand=[(float('nan'),float('nan'))]*21
        self.hand[6],self.hand[7],self.hand[8]=(345,210),(335,220),(325,230)

    def observation(self,now=0,hand=None,pose=None):
        return extract(now,pose or [],self.face,[self.hand if hand is None else hand],None,[],(480,640,3))

    def test_fingers_over_face_do_not_require_shoulders_wrists_or_registration(self):
        settings=Settings(performance='High')
        evaluator=Evaluator()
        first=self.observation()
        self.assertEqual(first.view,'unknown')
        self.assertEqual(first.metrics['touch_distance'],0)
        self.assertTrue(first.quality['finger_only_association'])
        self.assertEqual(evaluator.evaluate(first,None,settings)['face_touch'].status,'candidate')
        result=evaluator.evaluate(self.observation(.5),None,settings)
        self.assertEqual(result['face_touch'].status,'bad')
        self.assertEqual(result['slouch'].status,'unknown')

    def test_visible_wrist_does_not_need_pose_wrist_association(self):
        hand=list(self.hand)
        hand[0]=(350,380)
        pose=[(0,0,0)]*33
        pose[15]=(40,420,1) # A different hand's wrist must not reject overlap.
        self.assertEqual(self.observation(hand=hand,pose=pose).metrics['touch_distance'],0)

    def test_forehead_overlap_is_included(self):
        hand=list(self.hand)
        hand[6],hand[7],hand[8]=(320,120),(325,130),(330,140)
        self.assertEqual(self.observation(hand=hand).metrics['touch_distance'],0)

    def test_offscreen_wrist_cannot_invent_contact_through_interpolated_segments(self):
        hand=[(-200,220)]*21
        hand[5],hand[6]=(600,220),(610,225)
        obs=self.observation(hand=hand)
        self.assertGreater(obs.metrics['touch_distance'],.06)

    def test_single_point_or_implausibly_long_finger_is_not_a_valid_segment(self):
        hand=[(float('nan'),float('nan'))]*21
        hand[8]=(320,220)
        self.assertNotIn('touch_distance',self.observation(hand=hand).metrics)
        hand[7]=(40,220)
        self.assertNotIn('touch_distance',self.observation(hand=hand).metrics)

    def test_hand_loss_and_visible_withdrawal_end_the_episode(self):
        evaluator=Evaluator()
        settings=Settings(performance='High')
        evaluator.evaluate(self.observation(),None,settings)
        evaluator.evaluate(self.observation(.5),None,settings)
        empty=extract(1,[],self.face,[],None,[],(480,640,3))
        self.assertEqual(evaluator.evaluate(empty,None,settings)['face_touch'].status,'unknown')
        self.assertEqual(evaluator.evaluate(self.observation(1.5),None,settings)['face_touch'].status,'candidate')
        far=list(self.hand)
        far[6],far[7],far[8]=(570,210),(580,220),(590,230)
        self.assertEqual(evaluator.evaluate(self.observation(2,far),None,settings)['face_touch'].status,'good')

    def test_shoulder_visibility_or_monitor_switch_does_not_reset_touch_sequence(self):
        evaluator=Evaluator()
        settings=Settings(performance='High')
        first=self.observation()
        first.view='front'
        evaluator.evaluate(first,Baseline('front',{},{}),settings)
        self.assertEqual(evaluator.evaluate(self.observation(.5),None,settings)['face_touch'].status,'bad')
        pending=self.observation(1)
        self.assertEqual(evaluator.suspend_screen_transition(pending,settings)['face_touch'].status,'bad')
