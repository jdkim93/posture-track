import tempfile
import unittest
from pathlib import Path

import numpy as np

from posture_track.config import Settings
from posture_track.domain import AlertTimer, Baseline, Evaluator, Observation, Profiles
from posture_track.screen_tracking import ScreenTracker, eye_direction_features


class ScreenTrackingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profiles = Profiles(Path(self.directory.name) / 'profiles.json')
        for identity, yaw, pitch in (('main', 0, 0), ('right', 35, -12), ('far-right', 55, 0)):
            self.profiles.save(Baseline('front' if yaw == 0 else 'oblique_right',
                                       {'view_yaw': yaw, 'view_pitch': pitch}, {},
                                       camera_signature='cam', profile_id=identity))
        self.tracker = ScreenTracker()

    def sample(self, now, yaw=0, pitch=0):
        return self.tracker.update(self.profiles,
                                   Observation(now, 'front', {'view_yaw': yaw, 'view_pitch': pitch}), 'cam')

    def acquire(self):
        self.assertIsNone(self.sample(0))
        self.assertEqual(self.sample(.4).profile_id, 'main')

    def test_nearest_reference_has_no_unregistered_angle_gate(self):
        for yaw, expected in ((18, 'right'), (85, 'far-right'), (-60, 'main')):
            result = self.profiles.select(Observation(0, 'unknown', {'view_yaw': yaw}), 'cam')
            self.assertEqual(result.profile_id, expected)

    def test_head_bending_does_not_select_horizontal_neighbor(self):
        self.acquire()
        for now, pitch in ((1, -35), (2, -65), (3, 35)):
            self.assertEqual(self.sample(now, pitch=pitch).profile_id, 'main')

    def test_noisy_frame_pauses_but_does_not_replace_reference(self):
        self.acquire()
        self.assertIsNone(self.sample(.8, 35))
        self.assertEqual(self.sample(1.1).profile_id, 'main')
        self.assertEqual(self.tracker.current, 'main')

    def test_sustained_screen_change_uses_that_reference(self):
        self.acquire()
        self.assertIsNone(self.sample(.8, 35))
        self.assertIsNone(self.sample(1.2, 35))
        self.assertEqual(self.sample(1.7, 35).profile_id, 'right')
        self.assertEqual(self.sample(2, 36, -35).profile_id, 'right')

    def test_missing_face_has_no_score_and_reacquisition_keeps_reference(self):
        self.acquire()
        self.assertIsNone(self.tracker.update(self.profiles, Observation(1), 'cam'))
        self.assertEqual(self.sample(1.3).profile_id, 'main')

    def test_vertical_screen_can_switch_after_sustained_direction_change(self):
        self.profiles.save(Baseline('front', {'view_yaw': 0, 'view_pitch': -30}, {},
                                   camera_signature='cam', profile_id='upper'))
        self.acquire()
        self.assertIsNone(self.sample(.8, 0, -30))
        self.assertEqual(self.sample(1.7, 0, -30).profile_id, 'upper')

    def test_normalized_eye_features_ignore_zoom_and_image_roll(self):
        face = np.full((478, 2), (320., 220.))
        for index, point in {33:(270,200),133:(290,200),263:(370,200),362:(350,200),
                             234:(240,230),454:(400,230),1:(340,230)}.items():
            face[index] = point
        original = eye_direction_features(face, (800,1000,3))
        self.assertEqual(set(original), {'screen_eye_span','screen_nose_offset'})
        theta = .6
        rotation = np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
        transformed = (face - (320,220)) @ rotation.T * 1.4 + (450,350)
        result = eye_direction_features(transformed, (800,1000,3))
        for key in original:
            self.assertAlmostEqual(result[key], original[key])
        face[1] = (float('nan'), 230)
        self.assertEqual(eye_direction_features(face, (800,1000,3)), {})

    def test_eye_evidence_resolves_nearby_screen_directions(self):
        for identity, span, nose in (('main',.5,0), ('right',.4,.15), ('far-right',.3,.25)):
            profile = self.profiles.items[identity]
            profile.values.update(screen_eye_span=span,screen_nose_offset=nose)
        observation = Observation(0, 'front', {'view_yaw': 17,'screen_eye_span':.4,'screen_nose_offset':.15})
        self.assertEqual(self.profiles.select(observation,'cam').profile_id, 'right')
        # Legacy references without these measurements must remain usable.
        del self.profiles.items['main'].values['screen_eye_span']
        self.assertEqual(self.profiles.select(observation,'cam').profile_id, 'main')

    def test_posture_uses_selected_screen_baseline_instead_of_best_posture_match(self):
        self.profiles.items['main'].values['pitch'] = 0
        self.profiles.items['right'].values['pitch'] = -25
        settings = Settings(performance='High')
        settings.enabled = {key: key == 'head_bend' for key in settings.enabled}
        evaluator = Evaluator()
        # Main-screen direction with a bent head must remain bad even though
        # its pitch happens to match the right-screen registration perfectly.
        for now in (0, .4, 1, 1.5, 2, 2.5, 3, 3.5, 4):
            obs = Observation(now, 'front', {'view_yaw': 0,'view_pitch': -25,'pitch': -25})
            baseline = self.tracker.update(self.profiles, obs, 'cam')
            result = evaluator.evaluate(obs, baseline, settings)['head_bend']
        self.assertEqual(self.tracker.current, 'main')
        self.assertEqual(result.status, 'bad')
        # Looking toward the registered right screen uses its own pitch zero.
        obs = Observation(5, 'oblique_right', {'view_yaw': 35,'view_pitch': -25,'pitch': -25})
        baseline = self.profiles.select(obs, 'cam')
        self.assertEqual(baseline.profile_id, 'right')
        self.assertEqual(evaluator.evaluate(obs, baseline, settings)['head_bend'].status, 'good')

    def test_selected_geometry_survives_raw_front_side_boundary(self):
        from posture_track.vision import extract
        from test_upper_body import geometry
        pose,face,world = geometry()
        theta = np.deg2rad(61)
        rotation = [[np.cos(theta),0,np.sin(theta)],[0,1,0],[-np.sin(theta),0,np.cos(theta)]]
        raw = extract(0,pose,face,[],rotation,world,(480,640,3))
        selected = extract(0,pose,face,[],rotation,world,(480,640,3),view_override='oblique_right')
        self.assertEqual(raw.view, 'side_right')
        self.assertEqual(selected.view, 'oblique_right')
        self.assertIn('shoulder_angle', selected.metrics)
        self.assertNotIn('shoulder_angle', raw.metrics)
        self.assertAlmostEqual(selected.metrics['view_yaw'], raw.metrics['view_yaw'])

    def test_bending_cannot_select_a_nearby_horizontal_screen(self):
        self.profiles.save(Baseline('front',{'view_yaw':6,'view_pitch':-50,'pitch':-50},{},
                                   camera_signature='cam',profile_id='nearby'))
        obs=Observation(0,'front',{'view_yaw':0,'view_pitch':-50,'pitch':-50})
        self.assertEqual(self.profiles.select(obs,'cam','main').profile_id,'main')

    def test_eye_projection_change_does_not_override_clear_direction(self):
        for identity in self.profiles.items:
            self.profiles.items[identity].values.update(screen_eye_span=.5,screen_nose_offset=0)
        self.profiles.items['right'].values.update(screen_eye_span=.2,screen_nose_offset=.2)
        obs=Observation(0,'front',{'view_yaw':10,'screen_eye_span':.2,'screen_nose_offset':.2})
        self.assertEqual(self.profiles.select(obs,'cam','main').profile_id,'main')

    def test_brief_screen_ambiguity_does_not_erase_posture_duration(self):
        settings=Settings(performance='High')
        settings.enabled={key:key=='head_bend' for key in settings.enabled}
        baseline=self.profiles.items['main']
        baseline.values['pitch']=0
        evaluator=Evaluator()
        def measure(now):
            return evaluator.evaluate(Observation(now,'front',{'pitch':35}),baseline,settings)['head_bend']
        for now in (0,.5,1):
            self.assertEqual(measure(now).status,'candidate')
        evaluator.suspend_screen_transition(Observation(1.3),settings)
        self.assertEqual(measure(1.6).status,'candidate')
        for now in (2.1,2.6):
            measure(now)
        evaluator.suspend_screen_transition(Observation(2.9),settings)
        measure(3.2)
        self.assertEqual(measure(3.7).status,'candidate')
        self.assertEqual(measure(4.3).status,'bad')

    def test_real_screen_switch_and_face_loss_reset_posture_duration(self):
        settings=Settings(performance='High')
        settings.enabled={key:key=='head_bend' for key in settings.enabled}
        first,second=self.profiles.items['main'],self.profiles.items['right']
        first.values['pitch']=second.values['pitch']=0
        evaluator=Evaluator()
        for now in (0,.5,1):
            evaluator.evaluate(Observation(now,'front',{'pitch':35}),first,settings)
        evaluator.suspend_screen_transition(Observation(1.3),settings)
        result=evaluator.evaluate(Observation(1.6,'oblique_right',{'pitch':35}),second,settings)
        self.assertEqual(result['head_bend'].status,'candidate')
        self.assertEqual(evaluator.states['head_bend'].candidate,1.6)
        evaluator.evaluate(Observation(2),None,settings)
        self.assertIsNone(evaluator.states['head_bend'].candidate)

    def test_brief_screen_pause_preserves_alert_time_without_counting_pause(self):
        timer=AlertTimer()
        settings=Settings(performance='High',alert_seconds=4)
        for now in (0,.5,1,1.5,2):
            self.assertFalse(timer.update(True,now,settings))
        timer.suspend(2.3)
        self.assertFalse(timer.update(True,2.6,settings))
        for now in (3.1,3.6,4.1):
            self.assertFalse(timer.update(True,now,settings))
        self.assertTrue(timer.update(True,4.7,settings))
        timer.suspend(5)
        self.assertFalse(timer.update(False,5.3,settings))
        self.assertIsNone(timer.started)

    def test_long_screen_uncertainty_discards_old_posture_evidence(self):
        settings=Settings(performance='High')
        settings.enabled={key:key=='head_bend' for key in settings.enabled}
        baseline=self.profiles.items['main']
        baseline.values['pitch']=0
        evaluator=Evaluator()
        for now in (0,.5,1):
            evaluator.evaluate(Observation(now,'front',{'pitch':35}),baseline,settings)
        evaluator.suspend_screen_transition(Observation(1.3),settings)
        evaluator.evaluate(Observation(4,'front',{'pitch':35}),baseline,settings)
        self.assertEqual(evaluator.states['head_bend'].candidate,4)
