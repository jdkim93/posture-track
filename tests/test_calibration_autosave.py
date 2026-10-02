import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from posture_track.config import Settings
from posture_track.domain import Baseline, Calibration, Observation, Profiles
from posture_track.worker import Worker


class AutoSaveTests(unittest.TestCase):
    def test_side_monitor_without_visible_shoulders_can_save_head_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker(Path(folder),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(folder)/'profiles.json')
            worker.profiles.save(Baseline('front',{'pitch':0,'roll':0},{},profile_id='main',camera_signature=worker.signature()))
            worker.registration_target={'profile_id':'added','label':'옆 화면'}
            worker.calibration=Calibration(0,'side_right')
            worker.calibration_session=True
            for index in range(30):
                worker.advance_calibration(Observation(index*.3,'side_right',{'pitch':-8,'view_pitch':-8,'view_yaw':70}))
                if worker.calibration is None:
                    break
            saved=Profiles(worker.profiles.path)
            self.assertEqual(set(saved.items),{'main','added'})
            self.assertEqual(saved.items['added'].label,'옆 화면')
            self.assertEqual(saved.items['added'].view,'side_right')
            self.assertEqual(worker.registration_info()['status'],'saved')

    def test_slow_camera_extends_collection_instead_of_failing_at_eight_seconds(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker(Path(folder),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(folder)/'profiles.json')
            worker.registration_target={'profile_id':'added','label':'화면 2'}
            worker.calibration=Calibration(0,'oblique_right')
            worker.calibration_session=True
            for index in range(1,16):
                worker.advance_calibration(Observation(index*.55,'oblique_right',{'pitch':-8,'roll':0,'view_yaw':35}))
            self.assertIsNotNone(worker.calibration)
            self.assertEqual(worker.profiles.items,{})
            for index in range(16,20):
                worker.advance_calibration(Observation(index*.55,'oblique_right',{'pitch':-8,'roll':0,'view_yaw':35}))
                if worker.calibration is None:
                    break
            self.assertIn('added',Profiles(worker.profiles.path).items)

    def test_missing_samples_stop_at_limit_and_keep_existing_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker(Path(folder),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(folder)/'profiles.json')
            worker.profiles.save(Baseline('front',{'roll':4},{},profile_id='main'))
            worker.registration_target={'profile_id':'added','label':'옆 화면'}
            worker.calibration=Calibration(0,'side_right')
            worker.calibration_session=True
            worker.advance_calibration(Observation(5))
            self.assertIsNotNone(worker.calibration)
            worker.advance_calibration(Observation(10))
            self.assertIsNone(worker.calibration)
            self.assertEqual(set(Profiles(worker.profiles.path).items),{'main'})
            self.assertEqual(worker.registration_info()['target_name'],'옆 화면')
            self.assertEqual(worker.registration_info()['status'],'error')

    def test_oblique_eye_ratio_noise_uses_relative_limit_and_optional_depth_can_be_omitted(self):
        calibration=Calibration(0,'oblique_right')
        for index in range(19):
            calibration.add(Observation(.6+index*.3,'oblique_right',
                                       {'roll':0,'pitch':-8,'view_yaw':35,'upper_span':6+(index%3-1)*.1,
                                        'upper_depth':(index%3-1)*.4}))
        baseline=calibration.finish('cam')
        self.assertIn('upper_span',baseline.values)
        self.assertNotIn('upper_depth',baseline.values)

    def test_short_registration_requires_sufficient_time_and_stable_distinct_samples(self):
        calibration=Calibration(0,'front')
        for index in range(29):
            calibration.add(Observation(index*.3,'front',{'roll':1,'pitch':2}))
        self.assertEqual(Calibration.DURATION,8)
        self.assertGreaterEqual(calibration.samples[0].timestamp,Calibration.SETTLE)
        self.assertEqual(calibration.finish('cam').values['roll'],1)
        too_short=Calibration(0,'front')
        for index in range(12):
            too_short.add(Observation(.6+index*.05,'front',{'roll':1,'pitch':2}))
        with self.assertRaises(ValueError):
            too_short.finish('cam')

    def test_short_registration_still_rejects_moving_posture(self):
        calibration=Calibration(0,'front')
        for index in range(19):
            calibration.add(Observation(.6+index*.3,'front',{'roll':(-10 if index%2 else 10),'pitch':2}))
        with self.assertRaises(ValueError):
            calibration.finish('cam')

    def test_completed_calibration_persists_and_preserves_other_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker(Path(folder),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(folder)/'profiles.json')
            worker.profiles.save(Baseline('side_left',{'forward':.2},{},camera_signature=worker.signature()))
            worker.calibration=Calibration(0,'front')
            worker.calibration_session=True
            for i in range(21):
                worker.calibration.add(Observation(3+i*.5,'front',{'roll':1.,'pitch':2.}))
            worker.complete_calibration()
            saved=Profiles(worker.profiles.path)
            self.assertEqual(saved.items['front'].values['roll'],1.)
            self.assertIn('side_left',saved.items)
            self.assertFalse(worker.calibration_session)
            self.assertIsNone(worker.calibration)
            self.assertEqual(worker.events.get()[0],'calibration_saved')

    def test_bad_calibration_keeps_previous_baseline_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker(Path(folder),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(folder)/'profiles.json')
            worker.profiles.save(Baseline('front',{'roll':4.},{},camera_signature=worker.signature()))
            worker.calibration=Calibration(0,'front')
            worker.calibration_session=True
            worker.complete_calibration()
            self.assertEqual(Profiles(worker.profiles.path).items['front'].values['roll'],4.)
            self.assertFalse(worker.calibration_session)
            self.assertEqual(worker.events.get()[0],'error')
            self.assertEqual(worker.events.get()[0],'registration_failed')
            self.assertEqual(worker.registration_info()['status'],'error')
            self.assertTrue(worker.registration_info()['detail'])

    def test_second_monitor_registration_survives_reload_and_is_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker(Path(folder),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(folder)/'profiles.json')
            worker.profiles.save(Baseline('front',{'roll':1.},{},camera_signature=worker.signature()))
            worker.calibration=Calibration(0,'oblique_right')
            worker.calibration_session=True
            from test_upper_body import geometry
            from posture_track.vision import extract
            import numpy as np
            import math
            pose,face,world=geometry()
            angle=math.radians(40)
            rotation=[[math.cos(angle),0,math.sin(angle)],[0,1,0],[-math.sin(angle),0,math.cos(angle)]]
            observed=extract(3,pose,face,[],rotation,world,(480,640,3))
            self.assertEqual(observed.view,'oblique_right')
            for i in range(21):
                worker.calibration.add(Observation(3+i*.5,'oblique_right',observed.metrics | {'view_yaw':40+i*.05}))
            worker.complete_calibration()
            worker.profiles=Profiles(worker.profiles.path)
            self.assertEqual(set(worker.registration_info()['saved_views']),{'front','oblique_right'})
            self.assertEqual(worker.registration_info()['target_view'],'oblique_right')
            from posture_track.domain import Evaluator
            results=Evaluator().evaluate(Observation(20,'oblique_right',observed.metrics),worker.profiles.items['oblique_right'],Settings())
            self.assertFalse(any(result.status=='uncalibrated' for result in results.values()))

    def test_direction_boundary_does_not_drop_registered_view(self):
        worker=Worker(Path('.'),Settings(),demo=True)
        self.assertEqual(worker.stable_view('oblique_right',0,40),'unknown')
        self.assertEqual(worker.stable_view('oblique_right',2,40),'oblique_right')
        self.assertEqual(worker.stable_view('front',3,24),'oblique_right')
        self.assertEqual(worker.stable_view('oblique_right',4,26),'oblique_right')
        self.assertEqual(worker.stable_view('side_right',5,61),'unknown')
        self.assertEqual(worker.stable_view('front',6,0),'unknown')
        self.assertEqual(worker.stable_view('front',8,0),'front')
        self.assertEqual(worker.stable_view('unknown',9,None),'unknown')
        self.assertEqual(worker.view,'unknown')
