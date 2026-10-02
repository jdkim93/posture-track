"""Draw the geometry actually used by posture and proximity measurements."""
from __future__ import annotations

import numpy as np

from .vision import FACE_REGION, HAND_CHAINS, valid


def draw_measurement_guides(frame, obs):
    import cv2
    h, w = frame.shape[:2]
    face_color, body_color, hand_color = (104, 190, 235), (193, 220, 103), (150, 140, 242)

    def point(value):
        x, y = value[:2]
        if np.isfinite(x) and np.isfinite(y) and 0 <= x < w and 0 <= y < h:
            return int(x), int(y)
        return None

    def line(a, b, color, thickness=1):
        start, end = point(a), point(b)
        if start is not None and end is not None:
            cv2.line(frame, start, end, color, thickness, cv2.LINE_AA)

    if len(obs.face) > 454:
        # Head scale and orientation anchor used in extraction and rotation probe.
        line(obs.face[10], obs.face[152], face_color)
        if "touch_distance" in obs.metrics:
            points = [point(obs.face[i]) for i in FACE_REGION]
            if all(p is not None for p in points):
                hull = cv2.convexHull(np.asarray(points, dtype=np.int32))
                overlay = frame.copy()
                cv2.fillConvexPoly(overlay, hull, hand_color, cv2.LINE_AA)
                cv2.addWeighted(overlay, .12, frame, .88, 0, dst=frame)
                cv2.polylines(frame, [hull], True, hand_color, 1, cv2.LINE_AA)
    if "head_gap" in obs.metrics and all(valid(obs.pose, i, w, h) for i in (7, 8, 11, 12)):
        head = (np.asarray(obs.pose[7][:2]) + obs.pose[8][:2]) / 2
        shoulders = (np.asarray(obs.pose[11][:2]) + obs.pose[12][:2]) / 2
        line(head, shoulders, body_color)
        for center in (head, shoulders):
            p = point(center)
            if p:
                cv2.drawMarker(frame, p, body_color, cv2.MARKER_CROSS, 9, 1, cv2.LINE_AA)
    if "upper_span" in obs.metrics:
        if len(obs.face)>362:
            left_eye = (np.asarray(obs.face[33])+obs.face[133])/2
            right_eye = (np.asarray(obs.face[263])+obs.face[362])/2
            line(left_eye,right_eye,face_color)
        if 'upper_gap' in obs.metrics:
            for ear,shoulder in ((7,11),(8,12)):
                if valid(obs.pose,ear,w,h) and valid(obs.pose,shoulder,w,h):
                    line(obs.pose[ear],obs.pose[shoulder],body_color)
    if "forward_pixels" in obs.metrics:
        ear = int(obs.metrics["side_pair"])
        shoulder = 11 if ear == 7 else 12
        if all(valid(obs.pose, i, w, h) for i in (ear, shoulder)):
            e, s = obs.pose[ear], obs.pose[shoulder]
            line(e, (s[0], e[1]), face_color, 2)
            line((s[0], e[1]), s, body_color)
    for hand in obs.hands:
        if len(hand) != 21:
            continue
        for chain in HAND_CHAINS:
            for a, b in zip(chain, chain[1:]):
                line(hand[a], hand[b], hand_color)


def measurement_label(obs):
    parts = []
    for key, label in (("pitch", "머리 숙임"), ("roll", "머리 기울임"),
                       ("shoulder_angle", "어깨선")):
        value = obs.metrics.get(key)
        if value is not None and np.isfinite(value):
            if key == "shoulder_angle":
                value = (value + 90) % 180 - 90
            parts.append(f"{label} {value:+.1f}°")
    if "camera_rotation_degrees" in obs.quality:
        parts.append(f"영상 보정 {obs.quality['camera_rotation_degrees']}°")
    if obs.quality.get("subject_tracking") == "locked":
        people = obs.quality.get("people_detected", 1)
        parts.append(f"내 사용자 추적 · 화면에 {people}명")
    return " · ".join(parts)
