import unittest
import numpy as np

from posture_track.config import Settings
from posture_track.domain import Baseline, Calibration, Evaluator, Observation
from posture_track.upper_body import upper_body_metrics, upper_body_change
from posture_track.vision import extract


def geometry():
    pose = [(0,0,0)]*33
    pose[7],pose[8] = (280,190,1),(360,190,1)
    pose[11],pose[12] = (200,300,1),(440,300,1)
    # Hips deliberately outside the frame, with no reliable confidence.
    pose[23],pose[24] = (240,700,0),(400,700,0)
    face = [(320,180)]*478
    face[10],face[152] = (320,100),(320,260)
    face[33],face[133],face[263],face[362] = (270,160),(290,160),(370,160),(350,160)
    world = [(0,0,0)]*33
    world[7],world[8] = (-.07,-.2,-.1),(.07,-.2,-.1)
    world[11],world[12] = (-.2,0,0),(.2,0,0)
    return pose,face,world


class UpperBodyTests(unittest.TestCase):
    def test_sensitive_mode_detects_smaller_corroborated_change(self):
        rounded = self.metrics | {'upper_gap':self.metrics['upper_gap']*.965,
                                  'upper_span':self.metrics['upper_span']*.96}
        rounded.pop('upper_depth')
        self.assertLess(upper_body_change(rounded,self.baseline)[0],1)
        self.assertGreater(upper_body_change(rounded,self.baseline,sensitive=True)[0],1)
        for mode, expected in (('standard','good'),('sensitive','bad')):
            evaluator=Evaluator()
            settings=Settings(posture_sensitivity=mode,performance='High',enabled={t:t=='slouch' for t in Settings().enabled})
            for now in (0,.5,1,1.5,2,2.5,3):
                result=evaluator.evaluate(Observation(now,'front',rounded),self.baseline,settings)['slouch']
            self.assertEqual(result.status,expected)

    def test_new_default_exceeds_previous_sensitive_setting(self):
        rounded=self.metrics | {'upper_gap':self.metrics['upper_gap']*.95,
                               'upper_span':self.metrics['upper_span']*.95}
        rounded.pop('upper_depth')
        # Old sensitive width threshold was 8% * .75 = 6%.
        self.assertLess(.05/(.08*.75),1)
        self.assertGreater(upper_body_change(rounded,self.baseline)[0],1)

    def test_sensitive_mode_does_not_confirm_small_alternating_jitter(self):
        settings=Settings(posture_sensitivity='sensitive',performance='High',enabled={t:t=='slouch' for t in Settings().enabled})
        evaluator=Evaluator()
        for index in range(25):
            delta=(-1 if index%2 else 1)
            metrics=self.metrics | {'upper_gap':self.metrics['upper_gap']+delta*.025,
                                   'upper_span':self.metrics['upper_span']*(1+delta*.025)}
            result=evaluator.evaluate(Observation(index*.5,'front',metrics),self.baseline,settings)['slouch']
            self.assertNotEqual(result.status,'bad')

    def test_sensitive_mode_preserves_noise_floor_and_uniform_zoom_rejection(self):
        noisy=Baseline('front',self.metrics.copy(),{'upper_gap':.1,'upper_span':.2})
        changed=self.metrics | {'upper_gap':self.metrics['upper_gap']-.08,'upper_span':self.metrics['upper_span']*.935}
        changed.pop('upper_depth')
        self.assertLess(upper_body_change(changed,noisy,sensitive=True)[0],1)
        self.assertEqual(upper_body_change(self.metrics,self.baseline,sensitive=True)[0],0)

    def setUp(self):
        self.pose,self.face,self.world = geometry()
        self.metrics = upper_body_metrics(self.pose,self.face,self.world,(480,640,3),"front",0,0)
        self.baseline = Baseline("front",self.metrics.copy(),{})

    def test_upper_body_extracts_eye_ratio_without_visible_hips(self):
        obs = extract(0,self.pose,self.face,[],np.eye(3).tolist(),self.world,(480,640,3))
        self.assertEqual(obs.view,"front")
        self.assertAlmostEqual(obs.metrics["upper_span"],3)
        self.assertNotIn("torso_pitch",obs.metrics)

    def test_relative_proportions_ignore_uniform_zoom(self):
        for scale in (.8,.9,1.2,1.4):
            pose = [(x*scale,y*scale,q) for x,y,q in self.pose]
            face = [(x*scale,y*scale) for x,y in self.face]
            metrics = upper_body_metrics(pose,face,self.world,(800,1000,3),"front",0,0)
            self.assertAlmostEqual(upper_body_change(metrics,self.baseline)[0],0)

    def test_detects_compressed_neck_and_shoulder_eye_ratio_without_depth(self):
        metrics = self.metrics | {"upper_gap":self.metrics["upper_gap"]-.2,"upper_span":2.55}
        metrics.pop("upper_depth")
        self.assertGreater(upper_body_change(metrics,self.baseline)[0],1)
        settings = Settings(enabled={t: t=="slouch" for t in Settings().enabled})
        evaluator = Evaluator()
        for now in (0,1,2,3.2):
            result = evaluator.evaluate(Observation(now,"front",metrics),self.baseline,settings)["slouch"]
        self.assertEqual(result.status,"bad")
        self.assertIn("어깨",result.reason)

    def test_depth_only_or_head_drop_only_does_not_confirm_rounding(self):
        self.assertEqual(upper_body_change(self.metrics | {"upper_depth":.3},self.baseline)[0],0)
        self.assertEqual(upper_body_change(self.metrics | {"upper_gap":.2},self.baseline)[0],0)

    def test_visible_ratio_plus_forward_shoulder_depth_is_corroborated(self):
        metrics = self.metrics | {"upper_span":2.55,"upper_depth":.05}
        self.assertGreater(upper_body_change(metrics,self.baseline)[0],1)

    def test_turning_head_camera_distance_and_hidden_shoulders_are_unknown(self):
        for change in ({"upper_yaw":30},{"upper_pitch":50},{"upper_scale":230}):
            self.assertIsNone(upper_body_change(self.metrics | change,self.baseline)[0])
        pose = self.pose.copy()
        pose[11] = (200,300,.2)
        self.assertEqual(upper_body_metrics(pose,self.face,self.world,(480,640,3),"front",0,0),{})
        metrics = self.metrics.copy()
        del metrics["upper_eye_scale"]
        self.assertIsNone(upper_body_change(metrics,self.baseline)[0])

    def test_forward_leaning_is_not_rejected_as_camera_distance_change(self):
        # Head approaches the camera more than shoulders, without changing yaw.
        head_zoom,shoulder_zoom = 1.4,1.05
        metrics = self.metrics | {
            "upper_eye_scale":self.metrics["upper_eye_scale"]*head_zoom,
            "upper_scale":self.metrics["upper_scale"]*head_zoom,
            "upper_span":self.metrics["upper_span"]*shoulder_zoom/head_zoom,
            "upper_gap":self.metrics["upper_gap"]/head_zoom,
            "upper_pitch":18,
        }
        score,reason,_ = upper_body_change(metrics,self.baseline)
        self.assertIsNotNone(score)
        self.assertGreater(score,1)
        settings = Settings(enabled={t:t=="slouch" for t in Settings().enabled})
        evaluator = Evaluator()
        for now in (0,1,2,3.2):
            result = evaluator.evaluate(Observation(now,"front",metrics),self.baseline,settings)["slouch"]
        self.assertEqual(result.status,"bad")

    def test_extreme_projection_is_still_rejected(self):
        metrics = self.metrics | {"upper_eye_scale":self.metrics["upper_eye_scale"]*3,
                                 "upper_scale":self.metrics["upper_scale"]*3}
        self.assertIsNone(upper_body_change(metrics,self.baseline)[0])

    def test_moderate_turn_still_measures_slouch_with_projection_compensation(self):
        import math
        cosine=math.cos(math.radians(18))
        upright=self.metrics | {'upper_yaw':18,'upper_span':self.metrics['upper_span']/cosine,
                               'upper_eye_scale':self.metrics['upper_eye_scale']*cosine}
        self.assertEqual(upper_body_change(upright,self.baseline)[0],0)
        rounded=upright | {'upper_gap':self.metrics['upper_gap']-.25,
                           'upper_span':upright['upper_span']*.8}
        self.assertGreater(upper_body_change(rounded,self.baseline)[0],1)

    def test_old_baseline_requires_explicit_registration_instead_of_auto_learning(self):
        old = Baseline("front",{"roll":0,"head_gap":.5},{})
        result = Evaluator().evaluate(Observation(0,"front",self.metrics),old,Settings())["slouch"]
        self.assertEqual(result.status,"uncalibrated")
        self.assertIn("다시",result.reason)

    def test_new_metrics_survive_realistic_calibration_pixel_noise(self):
        calibration = Calibration(0,"front")
        for i in range(21):
            metrics = self.metrics | {"roll":0,"upper_scale":160+(i%3-1),"upper_eye_scale":80+(i%3-1)*.5}
            calibration.add(Observation(3+i*.3,"front",metrics))
        baseline = calibration.finish("camera")
        self.assertIn("upper_eye_scale",baseline.values)
        self.assertIn("upper_pitch",baseline.values)

    def test_forward_slouch_detects_even_when_chin_keeps_neck_gap_unchanged(self):
        metrics=self.metrics | {'upper_eye_scale':self.metrics['upper_eye_scale']*1.16,
                               'upper_scale':self.metrics['upper_scale']*1.16,
                               'upper_span':self.metrics['upper_span']/1.16}
        metrics.pop('upper_depth')
        self.assertGreater(upper_body_change(metrics,self.baseline)[0],1)
        self.assertEqual(metrics['upper_gap'],self.metrics['upper_gap'])

    def test_negative_depth_change_with_visible_rounding_is_not_missed(self):
        metrics=self.metrics | {'upper_gap':self.metrics['upper_gap']-.15,
                               'upper_depth':self.metrics['upper_depth']-.18}
        self.assertGreater(upper_body_change(metrics,self.baseline)[0],1)

    def test_moderate_dual_compression_no_longer_needs_ten_percent_shoulder_change(self):
        metrics=self.metrics | {'upper_gap':self.metrics['upper_gap']-.11,
                               'upper_span':self.metrics['upper_span']*.91}
        metrics.pop('upper_depth')
        self.assertGreater(upper_body_change(metrics,self.baseline)[0],1)

    def test_head_bending_alone_stays_separate_but_visible_forward_lean_can_be_measured(self):
        bent=self.metrics | {'upper_pitch':30,'upper_gap':.2,'upper_depth':.3}
        self.assertEqual(upper_body_change(bent,self.baseline)[0],0)
        leaning=bent | {'upper_eye_scale':self.metrics['upper_eye_scale']*1.2,
                        'upper_scale':self.metrics['upper_scale']*1.15,
                        'upper_span':self.metrics['upper_span']/1.2}
        self.assertGreater(upper_body_change(leaning,self.baseline)[0],1)

    def test_small_measurement_noise_does_not_confirm_slouch(self):
        settings=Settings(performance='High',enabled={t:t=='slouch' for t in Settings().enabled})
        evaluator=Evaluator()
        for index in range(25):
            delta=(-1 if index%2 else 1)
            metrics=self.metrics | {'upper_gap':self.metrics['upper_gap']+delta*.025,
                                   'upper_span':self.metrics['upper_span']*(1+delta*.025)}
            result=evaluator.evaluate(Observation(index*.5,'front',metrics),self.baseline,settings)['slouch']
            self.assertEqual(result.status,'good')

    def test_sustained_slouch_from_upright_confirms_promptly_but_one_frame_does_not(self):
        settings=Settings(performance='High',enabled={t:t=='slouch' for t in Settings().enabled})
        evaluator=Evaluator()
        rounded=self.metrics | {'upper_gap':self.metrics['upper_gap']-.18,
                               'upper_span':self.metrics['upper_span']*.85}
        evaluator.evaluate(Observation(0,'front',self.metrics),self.baseline,settings)
        result=evaluator.evaluate(Observation(.5,'front',rounded),self.baseline,settings)['slouch']
        self.assertNotEqual(result.status,'bad')
        self.assertEqual(evaluator.evaluate(Observation(1,'front',self.metrics),self.baseline,settings)['slouch'].status,'good')
        for now in (1.5,2,2.5,3,3.5,4,4.5):
            result=evaluator.evaluate(Observation(now,'front',rounded),self.baseline,settings)['slouch']
        self.assertEqual(result.status,'bad')

    def test_oblique_hidden_far_ear_does_not_disable_visible_ratio_detection(self):
        pose=self.pose.copy()
        pose[8]=(360,190,.1)
        metrics=upper_body_metrics(pose,self.face,self.world,(480,640,3),'oblique_right',0,37)
        self.assertIn('upper_span',metrics)
        self.assertNotIn('upper_gap',metrics)
        self.assertNotIn('upper_depth',metrics)
        baseline=Baseline('oblique_right',metrics.copy(),{})
        head_zoom=1.18
        face=[(320+(x-320)*head_zoom,180+(y-180)*head_zoom) for x,y in self.face]
        rounded=upper_body_metrics(pose,face,self.world,(480,640,3),'oblique_right',0,37)
        self.assertGreater(upper_body_change(rounded,baseline)[0],1)

    def test_existing_oblique_baseline_can_measure_when_ear_disappears(self):
        baseline=Baseline('oblique_right',self.metrics | {'upper_yaw':37},{})
        rounded=self.metrics | {'upper_yaw':37,'upper_scale':self.metrics['upper_scale']*1.18,
                                'upper_eye_scale':self.metrics['upper_eye_scale']*1.18,
                                'upper_span':self.metrics['upper_span']/1.18}
        rounded.pop('upper_gap')
        rounded.pop('upper_depth')
        self.assertGreater(upper_body_change(rounded,baseline)[0],1)

    def test_eye_projection_is_compensated_before_oblique_face_scale_rejection(self):
        import math
        for sign in (-1,1):
            baseline=Baseline('oblique_left' if sign<0 else 'oblique_right',self.metrics | {'upper_yaw':sign*37},{})
            ratio=math.cos(math.radians(57))/math.cos(math.radians(37))
            upright=self.metrics | {'upper_yaw':sign*57,'upper_eye_scale':self.metrics['upper_eye_scale']*ratio,
                                   'upper_span':self.metrics['upper_span']/ratio}
            self.assertEqual(upper_body_change(upright,baseline)[0],0)
            rounded=upright | {'upper_eye_scale':upright['upper_eye_scale']*1.18,
                              'upper_scale':self.metrics['upper_scale']*1.18,
                              'upper_span':upright['upper_span']/1.18}
            self.assertGreater(upper_body_change(rounded,baseline)[0],1)

    def test_shoulder_yaw_estimate_cannot_erase_independent_visible_slouch(self):
        baseline=Baseline('front',self.metrics | {'upper_body_yaw':10},{})
        rounded=self.metrics | {'upper_body_yaw':35,
                               'upper_scale':self.metrics['upper_scale']*1.12,
                               'upper_eye_scale':self.metrics['upper_eye_scale']*1.12,
                               'upper_span':self.metrics['upper_span']/1.12,
                               'upper_gap':self.metrics['upper_gap']/1.12,
                               'upper_depth':self.metrics['upper_depth']-.03}
        score=upper_body_change(rounded,baseline)[0]
        self.assertGreater(score,1)
        settings=Settings(performance='High',enabled={key:key=='slouch' for key in Settings().enabled})
        evaluator=Evaluator()
        for now in (0,.5,1,1.5,2,2.5):
            result=evaluator.evaluate(Observation(now,'front',rounded),baseline,settings)['slouch']
        self.assertEqual(result.status,'bad')

    def test_invalid_body_projection_does_not_disable_visible_neck_and_head_cues(self):
        baseline=Baseline('front',self.metrics | {'upper_body_yaw':10},{})
        rounded=self.metrics | {'upper_body_yaw':80,
                               'upper_scale':self.metrics['upper_scale']*1.15,
                               'upper_eye_scale':self.metrics['upper_eye_scale']*1.15,
                               'upper_span':self.metrics['upper_span']/1.15,
                               'upper_gap':self.metrics['upper_gap']-.15}
        self.assertGreater(upper_body_change(rounded,baseline)[0],1)
        upright=self.metrics | {'upper_body_yaw':80}
        self.assertEqual(upper_body_change(upright,baseline)[0],0)

    def test_old_slouch_reference_remains_usable_without_body_angle(self):
        legacy=Baseline('front',{key:value for key,value in self.metrics.items() if key!='upper_body_yaw'},{})
        rounded=self.metrics | {'upper_gap':self.metrics['upper_gap']-.18,
                               'upper_span':self.metrics['upper_span']*.85}
        self.assertGreater(upper_body_change(rounded,legacy)[0],1)


if __name__ == "__main__":
    unittest.main()
