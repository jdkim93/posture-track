import unittest
import numpy as np

from posture_track.config import Settings
from posture_track.domain import Baseline, Calibration, Evaluator, Observation
from posture_track.upper_body import upper_body_metrics, upper_body_change, forward_neck_change
from test_upper_body import geometry


class ForwardNeckTests(unittest.TestCase):
    def setUp(self):
        self.pose,self.face,self.world=geometry()
        self.view='oblique_right'
        self.base_metrics=upper_body_metrics(self.pose,self.face,self.world,(480,640,3),self.view,0,37)
        self.baseline=Baseline(self.view,self.base_metrics,{})

    def rotated_body(self,angle):
        theta=np.deg2rad(angle)
        rotation=np.array([[np.cos(theta),0,np.sin(theta)],[0,1,0],[-np.sin(theta),0,np.cos(theta)]])
        world=[tuple(rotation@np.array(point)) for point in self.world]
        pose=list(self.pose)
        for index in (11,12):
            x,y,q=pose[index]
            pose[index]=(320+(x-320)*np.cos(theta),y,q)
        return pose,world

    def forward_metrics(self):
        world=list(self.world)
        for index in (7,8):
            x,y,z=world[index]
            world[index]=(x,y,z-.055)
        face=[(320+(x-320)*1.08,180+(y-180)*1.08) for x,y in self.face]
        return upper_body_metrics(self.pose,face,world,(480,640,3),self.view,0,37)

    def test_shoulders_front_head_turned_and_neck_forward_is_detected(self):
        metrics=self.forward_metrics()
        self.assertGreater(forward_neck_change(metrics,self.baseline)[0],1)
        settings=Settings(performance='High',enabled={t:t=='forward_head' for t in Settings().enabled})
        evaluator=Evaluator()
        for now in (0,.5,1,1.5,2,2.5):
            result=evaluator.evaluate(Observation(now,self.view,metrics),self.baseline,settings)['forward_head']
        self.assertEqual(result.status,'bad')

    def test_body_rotation_alone_is_not_forward_neck_or_slouch(self):
        for angle in (-40,-25,25,40):
            pose,world=self.rotated_body(angle)
            metrics=upper_body_metrics(pose,self.face,world,(480,640,3),self.view,0,37)
            self.assertAlmostEqual(forward_neck_change(metrics,self.baseline)[0],0)
            self.assertAlmostEqual(upper_body_change(metrics,self.baseline)[0],0)
            # Registering while turned, then facing front must also stay good.
            turned=Baseline(self.view,metrics,{})
            self.assertAlmostEqual(forward_neck_change(self.base_metrics,turned)[0],0)
            self.assertAlmostEqual(upper_body_change(self.base_metrics,turned)[0],0)

    def test_head_direction_change_alone_is_not_neck_protraction(self):
        ratio=np.cos(np.deg2rad(48))/np.cos(np.deg2rad(37))
        metrics=self.base_metrics | {'upper_yaw':48,'upper_eye_scale':self.base_metrics['upper_eye_scale']*ratio,
                                     'upper_span':self.base_metrics['upper_span']/ratio}
        self.assertEqual(forward_neck_change(metrics,self.baseline)[0],0)

    def test_world_depth_alone_does_not_confirm_and_uniform_zoom_cancels(self):
        depth_only=self.base_metrics | {'upper_depth':self.base_metrics['upper_depth']-.2}
        self.assertEqual(forward_neck_change(depth_only,self.baseline)[0],0)
        for zoom in (.8,1.3):
            pose=[(x*zoom,y*zoom,q) for x,y,q in self.pose]
            face=[(x*zoom,y*zoom) for x,y in self.face]
            metrics=upper_body_metrics(pose,face,self.world,(800,1000,3),self.view,0,37)
            self.assertAlmostEqual(forward_neck_change(metrics,self.baseline)[0],0)

    def test_missing_ear_or_body_reference_is_explicit_not_good(self):
        missing=self.forward_metrics()
        del missing['upper_depth']
        del missing['upper_neck_left_forward']
        del missing['upper_neck_right_forward']
        self.assertIsNone(forward_neck_change(missing,self.baseline)[0])
        legacy=Baseline(self.view,{key:value for key,value in self.base_metrics.items() if key!='upper_body_yaw'},{})
        score,reason,needs_registration=forward_neck_change(self.forward_metrics(),legacy)
        self.assertIsNone(score)
        self.assertTrue(needs_registration)
        self.assertIn('다시 등록',reason)

    def test_body_angle_calibrates_as_degrees_and_survives_rotation(self):
        pose,world=self.rotated_body(30)
        metrics=upper_body_metrics(pose,self.face,world,(480,640,3),self.view,0,37)
        calibration=Calibration(0,self.view)
        for index in range(26):
            calibration.add(Observation(.6+index*.3,self.view,metrics | {'roll':0,'upper_body_yaw':30+(index%3-1)*.5}))
        baseline=calibration.finish('cam')
        self.assertAlmostEqual(baseline.values['upper_body_yaw'],30)

    def test_correcting_neck_can_clear_confirmed_deviation(self):
        settings=Settings(performance='High',enabled={t:t=='forward_head' for t in Settings().enabled})
        evaluator=Evaluator()
        for now in (0,.5,1,1.5,2,2.5):
            result=evaluator.evaluate(Observation(now,self.view,self.forward_metrics()),self.baseline,settings)['forward_head']
        self.assertEqual(result.status,'bad')
        for now in (2.7,2.9,3.1,3.3,3.5,3.7,3.9,4.1):
            result=evaluator.evaluate(Observation(now,self.view,self.base_metrics),self.baseline,settings,fast_recovery=True)['forward_head']
        self.assertEqual(result.status,'good')

    def test_hidden_far_ear_uses_same_visible_ear_without_borrowing_the_other(self):
        metrics=self.forward_metrics()
        del metrics['upper_neck_right_forward']
        del metrics['upper_depth']
        del metrics['upper_gap']
        self.assertGreater(forward_neck_change(metrics,self.baseline)[0],1)
        metrics['upper_body_yaw']=20
        self.assertIsNone(forward_neck_change(metrics,self.baseline)[0])

    def test_neck_changes_do_not_choose_a_different_monitor(self):
        import tempfile
        from pathlib import Path
        from posture_track.domain import Profiles
        with tempfile.TemporaryDirectory() as folder:
            profiles=Profiles(Path(folder)/'profiles.json')
            profiles.save(Baseline('front',self.base_metrics | {'view_yaw':0,'upper_yaw':0},{},camera_signature='cam',profile_id='main'))
            profiles.save(Baseline(self.view,self.base_metrics | {'view_yaw':37},{},camera_signature='cam',profile_id='second'))
            obs=Observation(0,self.view,self.forward_metrics() | {'view_yaw':37})
            self.assertEqual(profiles.select(obs,'cam','second').profile_id,'second')
