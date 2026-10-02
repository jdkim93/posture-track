from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .domain import Baseline, Observation
from .shoulders import ShoulderGuard
from .orientation import CameraOrientation, rotate_frame
from .subjects import SubjectTracker, describe_subjects


# MediaPipe's FACE_LANDMARKS_FACE_OVAL: include forehead as well as cheeks/chin.
FACE_REGION = (10,338,297,332,284,251,389,356,454,323,361,288,397,365,379,378,
               400,377,152,148,176,149,150,136,172,58,132,93,234,127,162,21,54,103,67,109)
HAND_CHAINS = ((1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12),
               (13, 14, 15, 16), (17, 18, 19, 20), (0, 5, 9, 13, 17))


def valid(pose, i, w, h):
    if i >= len(pose):
        return False
    x, y, quality = pose[i]
    return all(math.isfinite(v) for v in (x, y, quality)) and quality >= 0.65 and 0 <= x < w and 0 <= y < h


def wrist_anchor(pose, i, w, h):
    if valid(pose, i, w, h):
        return np.asarray(pose[i][:2]), False
    if i >= len(pose):
        return None
    x, y, confidence = pose[i]
    # A small projection error at the boundary is not equivalent to a lost hand.
    # Boundary anchors additionally require an in-frame Hand-model wrist below.
    if (all(math.isfinite(v) for v in (x, y, confidence)) and confidence >= .85
            and -.03 * w <= x < 1.03 * w and -.03 * h <= y < 1.03 * h):
        return np.asarray((x, y)), True
    return None


def angles(rotation):
    r = np.asarray(rotation, dtype=float)
    pitch = math.degrees(math.atan2(-r[1, 2], math.hypot(r[0, 2], r[2, 2])))
    yaw = math.degrees(math.atan2(r[0, 2], r[2, 2]))
    roll = math.degrees(math.atan2(r[1, 0], r[1, 1]))
    return pitch, yaw, roll


def classify_view(yaw, body_yaw):
    # Monitor direction follows the face. A seated user can turn their head
    # towards a second screen while keeping both shoulders facing the camera.
    if body_yaw is None or not math.isfinite(yaw) or not math.isfinite(body_yaw):
        return "unknown"
    amount = abs(yaw)
    if amount < 25:
        return "front"
    side = "right" if yaw >= 0 else "left"
    return ("side_" if amount >= 60 else "oblique_") + side


def extract(timestamp, pose, face, hands, rotation, world, shape, baseline=None,view_override=None):
    h, w = shape[:2]
    obs = Observation(timestamp, pose=pose, face=face, hands=hands, rotation=rotation,world=world)
    from .screen_tracking import eye_direction_features
    obs.metrics.update(eye_direction_features(face,shape))
    yaw = None
    if rotation is not None:
        pitch, yaw, roll = angles(rotation)
        absolute_pitch = pitch
        body_yaw = None
        if valid(pose, 11, w, h) and valid(pose, 12, w, h) and len(world) > 12:
            delta = np.asarray(world[12]) - np.asarray(world[11])
            body_yaw = math.degrees(math.atan2(abs(delta[2]), abs(delta[0])))
        # A genuinely visible near ear and shoulder permits tentative side use.
        if body_yaw is None and abs(yaw) >= 60:
            visible = [i for i in (11, 12) if valid(pose, i, w, h)]
            if len(visible) == 1:
                body_yaw = abs(yaw)
        obs.view = classify_view(yaw, body_yaw)
        if view_override is not None:
            obs.view=view_override
        obs.metrics["view_yaw"] = yaw
        obs.metrics["view_pitch"] = absolute_pitch
        if baseline is not None and baseline.rotation is not None:
            relative = np.asarray(baseline.rotation).T @ np.asarray(rotation)
            pitch, _, roll = angles(relative)
            obs.metrics["relative_rotation"] = 1.0
        obs.metrics["pitch"] = pitch
        from .upper_body import upper_body_metrics
        obs.metrics.update(upper_body_metrics(pose,face,world,shape,obs.view,absolute_pitch,yaw))
        if obs.view == "front" or obs.view.startswith("oblique"):
            obs.metrics["roll"] = roll

    if obs.view == "front" or obs.view.startswith("oblique"):
        if valid(pose, 11, w, h) and valid(pose, 12, w, h):
            left, right = np.asarray(pose[11][:2]), np.asarray(pose[12][:2])
            span = np.linalg.norm(right - left)
            if span > w * 0.08:
                obs.metrics["shoulder_angle"] = math.degrees(math.atan2(*(right - left)[::-1]))
                if valid(pose, 7, w, h) and valid(pose, 8, w, h):
                    head = (np.asarray(pose[7][:2]) + np.asarray(pose[8][:2])) / 2
                    obs.metrics["head_gap"] = (((left + right) / 2)[1] - head[1]) / span
        obs.reasons["forward"] = "정면·사선 목 전방 이동은 몸통 방향과 귀·어깨 위치를 함께 비교합니다"
    elif obs.view.startswith("side"):
        pairs = [(7, 11, 23), (8, 12, 24)]
        usable = [p for p in pairs if valid(pose, p[0], w, h) and valid(pose, p[1], w, h)]
        if usable and valid(pose, 0, w, h):
            ear, shoulder, hip = max(usable, key=lambda p: min(pose[p[0]][2], pose[p[1]][2]))
            e, s = np.asarray(pose[ear][:2]), np.asarray(pose[shoulder][:2])
            nose = np.asarray(pose[0][:2])
            if abs(nose[0] - e[0]) > 5 and len(face) > 454:
                direction = 1 if nose[0] > e[0] else -1
                scale = float(np.linalg.norm(np.asarray(face[10]) - np.asarray(face[152])))
                if scale > h * 0.05:
                    obs.metrics["side_scale"] = scale
                    obs.metrics["side_pair"] = float(ear)
                    obs.metrics["forward_pixels"] = float(direction * (e[0] - s[0]))
                    obs.metrics["forward"] = obs.metrics["forward_pixels"] / scale
                    if valid(pose, hip, w, h) and pose[hip][1] - s[1] > h * .08:
                        t = np.asarray(pose[hip][:2])
                        obs.metrics["torso_pitch"] = math.degrees(math.atan2(direction * (s[0] - t[0]), t[1] - s[1]))
        obs.reasons["shoulder_angle"] = "측면에서는 양쪽 어깨 비대칭 평가를 지원하지 않습니다"
        obs.reasons["roll"] = "측면에서는 좌우 기울임 평가를 지원하지 않습니다"
    obs.reasons["torso_pitch"] = "실제로 보이는 어깨와 엉덩이가 필요합니다"

    if len(face) > 454 and hands:
        # Visible face outline; hand ownership and shoulder visibility are not
        # prerequisites for measuring overlap with the selected face.
        region = np.asarray([face[i] for i in FACE_REGION], dtype=np.float32)
        size = float(np.linalg.norm(np.asarray(face[10]) - np.asarray(face[152])))
        if size > h * 0.05 and np.all(np.isfinite(region)) and all(0<=x<w and 0<=y<h for x,y in region):
            import cv2
            hull = cv2.convexHull(region)
            # Include finger segments: a fingertip can be hidden at the mouth.
            samples = []
            visible_wrists = [anchor for i in (15, 16) if (anchor := wrist_anchor(pose, i, w, h)) is not None]
            for hand in hands:
                if len(hand) != 21:
                    continue
                hand_wrist = np.asarray(hand[0])
                matches = [(wrist, edge) for wrist, edge in visible_wrists
                           if (not edge or (0 <= hand_wrist[0] < w and 0 <= hand_wrist[1] < h))
                           and np.linalg.norm(hand_wrist - wrist) <= size * .8]
                wrist_visible=np.all(np.isfinite(hand_wrist)) and 0<=hand_wrist[0]<w and 0<=hand_wrist[1]<h
                partial=not wrist_visible
                hand_samples=[]
                # Only genuinely in-frame endpoints contribute. An inferred
                # offscreen wrist must never draw a line through the face.
                for chain in HAND_CHAINS[:5] if partial else HAND_CHAINS:
                    for a, b in zip(chain, chain[1:]):
                        pair=np.asarray([hand[a],hand[b]],dtype=float)
                        if not np.all(np.isfinite(pair)) or not all(0<=x<w and 0<=y<h for x,y in pair):
                            continue
                        length=float(np.linalg.norm(pair[1]-pair[0]))
                        if partial and not max(2,size*.01)<length<size*.45:
                            continue
                        hand_samples.extend(np.linspace(pair[0],pair[1],5))
                if partial:
                    if not hand_samples:
                        continue
                    obs.quality['finger_only_association']=True
                else:
                    obs.quality["wrist_boundary_association"] = obs.quality.get("wrist_boundary_association", False) or any(edge for _, edge in matches)
                samples.extend(hand_samples)
            if samples:
                distances = [max(0.0, -cv2.pointPolygonTest(hull, tuple(map(float, p)), True)) for p in samples]
                obs.metrics["touch_distance"] = min(distances) / size
    obs.reasons["touch_distance"] = "손/얼굴의 유효 관측이 필요합니다. 손 검출 실패는 복귀가 아닙니다"
    return obs


class LocalModels:
    def __init__(self, directory: Path):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision
        self.mp, self.vision, self.base = mp, vision, BaseOptions
        self.directory = directory
        self.models = {}
        self.shoulders = ShoulderGuard()
        self.max_gap = 10.0
        self.orientation = CameraOrientation()
        self.orientation_model = None
        self.corrected_frame = None
        self.subject = SubjectTracker()
        self.multiple_people = False
        self.multi_last_seen = None
        try:
            self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("로컬 모델 manifest가 없습니다. 개발 준비 도구 tools/prepare_models.py를 먼저 실행하세요.")
        self.verified = set()

    def path(self, name):
        path = self.directory / name
        try:
            expected = self.manifest[name]["sha256"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, KeyError):
            raise RuntimeError(f"로컬 모델이 없습니다: {name}. 앱은 자동 다운로드하지 않습니다.")
        if digest != expected:
            raise RuntimeError(f"모델 무결성 검사 실패: {name}")
        return str(path)

    def ensure(self, pose=True, face=True, hands=False):
        desired = {"pose": pose, "face": face, "hands": hands}
        for key, on in desired.items():
            if not on and key in self.models:
                self.models.pop(key).close()
            if on and key not in self.models:
                v, base = self.vision, self.base
                if key == "pose":
                    options = v.PoseLandmarkerOptions(base_options=base(model_asset_path=self.path("pose_landmarker_full.task")),
                        running_mode=v.RunningMode.VIDEO, num_poses=4, output_segmentation_masks=True)
                    model = v.PoseLandmarker.create_from_options(options)
                elif key == "face":
                    options = v.FaceLandmarkerOptions(base_options=base(model_asset_path=self.path("face_landmarker.task")),
                        running_mode=v.RunningMode.VIDEO, num_faces=4, output_facial_transformation_matrixes=True)
                    model = v.FaceLandmarker.create_from_options(options)
                else:
                    options = v.HandLandmarkerOptions(base_options=base(model_asset_path=self.path("hand_landmarker.task")),
                        running_mode=v.RunningMode.VIDEO, num_hands=4)
                    model = v.HandLandmarker.create_from_options(options)
                self.models[key] = model

    def detect(self, frame, now, baseline=None):
        import cv2
        if self.orientation_model is None:
            options = self.vision.FaceLandmarkerOptions(
                base_options=self.base(model_asset_path=self.path("face_landmarker.task")),
                running_mode=self.vision.RunningMode.IMAGE, num_faces=4)
            self.orientation_model = self.vision.FaceLandmarker.create_from_options(options)
        current_probe = {"people":0}
        def probe(candidate):
            image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,
                                  data=cv2.cvtColor(candidate, cv2.COLOR_BGR2RGB))
            result = self.orientation_model.detect(image)
            if np.array_equal(candidate, rotate_frame(frame, self.orientation.turns)):
                current_probe["people"] = len(result.face_landmarks)
                if len(result.face_landmarks)>1 or getattr(self,"multiple_people",False):
                    from types import SimpleNamespace
                    # Continue inference in the established axes so subject
                    # overlap/occlusion can pause independently of rotation.
                    return SimpleNamespace(face_landmarks=result.face_landmarks,freeze_rotation=True)
            return result
        frame, ready, changed = self.orientation.correct(frame, probe, now, self.max_gap)
        self.corrected_frame = frame
        if not ready:
            quality = {"camera_rotation_degrees": self.orientation.turns * 90}
            return Observation(now, reasons={"subject": "카메라 영상 방향 확인 중 · 얼굴이 보이도록 조정하세요"}, quality=quality)
        if changed:
            # VIDEO trackers and shoulder history use the previous image axes.
            desired = {key: key in self.models for key in ("pose", "face", "hands")}
            for model in self.models.values():
                model.close()
            self.models.clear()
            self.shoulders = ShoulderGuard()
            self.ensure(**desired)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        millis = int(now * 1000)
        values = {k: m.detect_for_video(image, millis) for k, m in self.models.items()}
        p, f, hand = values.get("pose"), values.get("face"), values.get("hands")
        h, w = frame.shape[:2]
        faces = f.face_landmarks if f else []
        poses = p.pose_landmarks if p else []
        people_count = max(len(faces),len(poses),current_probe["people"])
        if people_count>1:
            self.multiple_people, self.multi_last_seen = True, now
        elif len(faces)==1 and len(poses)==1:
            self.multiple_people = False
        elif getattr(self,"multi_last_seen",None) is not None and now-self.multi_last_seen>max(3,self.max_gap):
            self.multiple_people = False
        candidates = describe_subjects(frame, faces, poses)
        selected, reason = self.subject.choose(candidates, now, self.max_gap,
                                               people_count=people_count)
        if selected is None:
            return Observation(now, reasons={"subject": reason}, quality={
                "camera_rotation_degrees": self.orientation.turns * 90,
                "subject_tracking": "waiting", "people_detected": people_count})
        pi, fi = selected.pose_index, selected.face_index
        pose = [(x.x * w, x.y * h, min(x.visibility or 0, x.presence or 0)) for x in poses[pi]] if pi is not None else []
        world = [(x.x, x.y, x.z) for x in p.pose_world_landmarks[pi]] if pi is not None and pi < len(p.pose_world_landmarks) else []
        face = [(x.x * w, x.y * h) for x in faces[fi]]
        rotation = None
        if f and fi < len(f.facial_transformation_matrixes):
            u, _, vt = np.linalg.svd(np.asarray(f.facial_transformation_matrixes[fi])[:3, :3])
            correction = np.diag([1, 1, np.linalg.det(u @ vt)])
            rotation = (u @ correction @ vt).tolist()
        groups = hand.hand_landmarks if hand else []
        hands = [[(x.x * w, x.y * h) for x in group] for group in groups]
        mask = p.segmentation_masks[pi].numpy_view() if pi is not None and p.segmentation_masks and pi < len(p.segmentation_masks) else None
        pose, quality = self.shoulders.check(pose, face, mask, frame.shape, now, self.max_gap)
        obs = extract(now, pose, face, hands, rotation, world, frame.shape, baseline)
        obs.quality["camera_rotation_degrees"] = self.orientation.turns * 90
        obs.quality["subject_tracking"] = "locked"
        obs.quality["people_detected"] = people_count
        obs.quality["shoulders"] = quality
        rejected = [v["reason"] for v in quality.values() if not v["accepted"]]
        if rejected:
            message = " · ".join(dict.fromkeys(rejected))
            obs.reasons["shoulder_angle"] = message
            obs.reasons["torso_pitch"] = message
            obs.reasons["forward"] = message
            if obs.view == "unknown":
                obs.reasons["subject"] = message
        return obs

    def close(self):
        if self.orientation_model is not None:
            self.orientation_model.close()
            self.orientation_model = None
        for model in self.models.values():
            model.close()
        self.models.clear()
