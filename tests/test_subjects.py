import unittest
from types import SimpleNamespace

import numpy as np

from posture_track.subjects import Candidate, SubjectTracker, color_hist, describe_subjects, subject_hands
from posture_track.vision import LocalModels


def candidate(index, x, color=0, pose=None):
    histogram = np.zeros(128, dtype=np.float32)
    histogram[color] = 1
    return Candidate(index, index if pose is None else pose, np.array((x, .35)), .25,
                     histogram, histogram.copy())


def landmark(x, y, quality=1):
    return SimpleNamespace(x=x, y=y, z=0, visibility=quality, presence=quality)


def face(x):
    points = [landmark(x, .3) for _ in range(478)]
    points[10], points[152] = landmark(x, .2), landmark(x, .4)
    points[234], points[454] = landmark(x-.06, .3), landmark(x+.06, .3)
    return points


def pose(x):
    points = [landmark(x, .3) for _ in range(33)]
    points[11], points[12] = landmark(x-.12, .5), landmark(x+.12, .5)
    points[15], points[16] = landmark(x-.12, .7), landmark(x+.12, .7)
    return points


class SubjectTests(unittest.TestCase):
    def test_neutral_clothes_are_stable_under_small_color_cast(self):
        points = [(2,2),(18,2),(18,18),(2,18)]
        white = np.full((20,20,3),220,dtype=np.uint8)
        warm = white.copy()
        warm[:] = (195,205,220)
        np.testing.assert_array_equal(color_hist(white,points),color_hist(warm,points))

    def test_initial_multiple_people_wait(self):
        tracker = SubjectTracker()
        self.assertIsNone(tracker.choose([candidate(0,.3), candidate(1,.7)], 0)[0])
        self.assertIsNone(tracker.anchor)

    def test_detection_order_does_not_change_subject(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)], 0)
        selected, _ = tracker.choose([candidate(0,.7,1), candidate(1,.32)], 1)
        self.assertEqual(selected.face_index, 1)
        selected, _ = tracker.choose([candidate(0,.34), candidate(1,.65,1)], 2)
        self.assertEqual(selected.face_index, 0)

    def test_single_person_is_measured_despite_appearance_change_and_gap(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)], 0)
        self.assertIsNone(tracker.choose([], 1)[0])
        self.assertIsNotNone(tracker.choose([candidate(0,.3,1)], 2)[0])
        self.assertIsNotNone(tracker.choose([candidate(0,.3,2)], 50)[0])
        self.assertIsNotNone(tracker.choose([candidate(1,.31)], 51)[0])

    def test_multiple_newcomers_do_not_replace_missing_subject(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)],0)
        self.assertIsNone(tracker.choose([candidate(0,.3,1),candidate(1,.8,2)],1)[0])
        self.assertIsNotNone(tracker.choose([candidate(0,.31),candidate(1,.8,2)],2)[0])

    def test_overlap_pauses_and_separation_resumes(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)],0)
        selected, reason = tracker.choose([candidate(1,.3),candidate(0,.48,1)],1)
        self.assertIsNone(selected)
        self.assertIn('겹쳐',reason)
        self.assertEqual(tracker.last,0)
        self.assertIsNotNone(tracker.choose([candidate(1,.3),candidate(0,.8,1)],2)[0])

    def test_nearer_newcomer_pauses(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)],0)
        visitor = candidate(1,.9,1)
        visitor.scale = .4
        selected, reason = tracker.choose([candidate(0,.3),visitor],1)
        self.assertIsNone(selected)
        self.assertIn('가까이',reason)

    def test_hidden_second_face_does_not_become_solo(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)],0)
        self.assertIsNone(tracker.choose([candidate(0,.3)],1,people_count=2)[0])

    def test_body_overlap_pauses_even_with_separate_faces(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)],0)
        own, other = candidate(0,.3),candidate(1,.8,1)
        own.body_bounds = (.1,.4,.6,.8)
        other.body_bounds = (.4,.4,.9,.8)
        self.assertIsNone(tracker.choose([own,other],1)[0])

    def test_unmatched_body_in_multiple_people_pauses(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)],0)
        visitor = candidate(1,.8,1)
        visitor.pose_index = None
        self.assertIsNone(tracker.choose([candidate(0,.3),visitor],1)[0])

    def test_similar_overlapping_people_are_ambiguous(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.5)], 0)
        self.assertIsNone(tracker.choose([candidate(0,.49), candidate(1,.51)], 1)[0])
        self.assertEqual(tracker.last, 0)

    def test_probe_does_not_modify_identity(self):
        tracker = SubjectTracker()
        tracker.choose([candidate(0,.3)], 0)
        tracker.choose([candidate(1,.35)], 1, update=False)
        self.assertEqual(tracker.current.face_index, 0)
        self.assertEqual(tracker.last, 0)

    def test_independent_face_and_pose_order_is_matched(self):
        frame = np.full((480,640,3), 128, dtype=np.uint8)
        candidates = describe_subjects(frame, [face(.25), face(.75)], [pose(.75), pose(.25)])
        self.assertEqual([c.pose_index for c in candidates], [1,0])
        self.assertTrue(all(c.body_color is not None for c in candidates))

    def test_missing_or_ambiguous_body_does_not_borrow_pose(self):
        frame = np.full((480,640,3),128,dtype=np.uint8)
        candidates = describe_subjects(frame, [face(.25)], [pose(.75)])
        self.assertIsNone(candidates[0].pose_index)
        candidates = describe_subjects(frame, [face(.25)], [pose(.25),pose(.25)])
        self.assertIsNone(candidates[0].pose_index)

    def test_other_person_hand_is_excluded(self):
        poses = [pose(.25),pose(.75)]
        own = [landmark(.13,.7)]*21
        other = [landmark(.63,.7)]*21
        selected = subject_hands([other,own], poses, 0, .2)
        self.assertEqual(selected,[own])
        poses[1][15] = landmark(.13,.7)
        self.assertEqual(subject_hands([own],poses,0,.2),[])

    def test_pipeline_uses_matched_face_pose_mask_and_hands(self):
        class Model:
            def __init__(self, value):
                self.value = value
            def detect_for_video(self, image, timestamp):
                return self.value
        class Guard:
            def check(self, pose, face, mask, *args):
                self.mask = mask
                return pose, {}
        frame = np.zeros((480,640,3),dtype=np.uint8)
        frame[:,:320] = (40,40,200)
        frame[:,320:] = (200,40,40)
        target_pose, visitor_pose = pose(.25), pose(.75)
        own_hand, visitor_hand = [landmark(.13,.7)]*21, [landmark(.63,.7)]*21
        mask = np.ones((480,640),dtype=np.float32)
        p = SimpleNamespace(pose_landmarks=[target_pose],pose_world_landmarks=[target_pose],
                            segmentation_masks=[SimpleNamespace(numpy_view=lambda:mask)])
        f = SimpleNamespace(face_landmarks=[face(.25)],facial_transformation_matrixes=[np.eye(4)])
        models = LocalModels.__new__(LocalModels)
        models.models = {'pose':Model(p),'face':Model(f),'hands':Model(SimpleNamespace(hand_landmarks=[own_hand]))}
        models.mp = SimpleNamespace(Image=lambda **kwargs:None, ImageFormat=SimpleNamespace(SRGB=0))
        models.orientation_model = object()
        models.orientation = SimpleNamespace(turns=0,correct=lambda frame,*args:(frame,True,False))
        models.subject, models.shoulders, models.max_gap = SubjectTracker(), Guard(), 10
        initial = models.detect(frame,1)
        self.assertEqual(initial.view,'front')
        p.pose_landmarks = [target_pose,visitor_pose]
        p.pose_world_landmarks = [target_pose,visitor_pose]
        p.segmentation_masks.append(SimpleNamespace(numpy_view=lambda:np.zeros_like(mask)))
        f.face_landmarks = [face(.75),face(.25)]
        f.facial_transformation_matrixes = [np.eye(4),np.eye(4)]
        models.models['hands'].value.hand_landmarks = [visitor_hand,own_hand]
        result = models.detect(frame,2)
        self.assertEqual(result.view,'front')
        self.assertEqual(result.face,initial.face)
        self.assertEqual(result.pose,initial.pose)
        # Every detected hand may touch the selected user's face; ownership
        # filtering is intentionally independent from posture subject tracking.
        self.assertEqual(result.hands[1],initial.hands[0])
        self.assertEqual(len(result.hands),2)
        self.assertEqual(result.quality['people_detected'],2)
        np.testing.assert_array_equal(models.shoulders.mask,mask)
