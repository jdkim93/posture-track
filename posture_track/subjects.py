"""Session-local subject continuity, without names or persisted face data."""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np


@dataclass
class Candidate:
    face_index: int
    pose_index: int | None
    center: np.ndarray
    scale: float
    face_color: np.ndarray
    body_color: np.ndarray | None
    body_bounds: tuple | None = None


def color_hist(frame, points):
    import cv2
    h, w = frame.shape[:2]
    points = np.asarray(points, dtype=float)
    if len(points) < 3 or not np.all(np.isfinite(points)):
        return None
    points = np.rint(points).astype(np.int32)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(points), 255)
    if cv2.countNonZero(mask) < 25:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Hue is unstable for white/gray clothes and weakly saturated highlights.
    # Treat those pixels as neutral so lighting does not invent a new identity.
    neutral = hsv[:, :, 1] < 40
    hsv[neutral, 0] = 0
    hsv[neutral, 1] = 0
    hist = cv2.calcHist([hsv], [0, 1], mask, [16, 8], [0, 180, 0, 256]).flatten()
    return hist / max(float(hist.sum()), 1)


def describe_subjects(frame, faces, poses):
    h, w = frame.shape[:2]
    candidates = []
    for index, face in enumerate(faces):
        if len(face) <= 454:
            continue
        points = np.asarray([(p.x * w, p.y * h) for p in face])
        if not np.all(np.isfinite(points)):
            continue
        center = (points[234] + points[454]) / 2
        scale = float(np.linalg.norm(points[10] - points[152]))
        if scale < min(h, w) * .05:
            continue
        hist = color_hist(frame, points[[10, 234, 152, 454]])
        if hist is None:
            continue
        candidates.append(Candidate(index, None, center / (w, h), scale / min(w, h), hist, None))
    # Associate the independent face/pose outputs by head position, never index.
    distances = np.full((len(candidates), len(poses)), np.inf)
    for ci, candidate in enumerate(candidates):
        for pi, pose in enumerate(poses):
            head = [(p.x, p.y) for p in pose[:11]
                    if min(p.visibility or 0, p.presence or 0) >= .65]
            if head:
                delta = (np.mean(head, axis=0) - candidate.center) * (w, h)
                distances[ci, pi] = np.linalg.norm(delta) / (candidate.scale * min(w, h))
    for ci, candidate in enumerate(candidates):
        if not len(poses):
            continue
        pi = int(np.argmin(distances[ci]))
        row = np.sort(distances[ci])
        if (distances[ci, pi] > .9 or int(np.argmin(distances[:, pi])) != ci or
                (len(row) > 1 and row[1] - row[0] < .2)):
            continue
        candidate.pose_index = pi
        pose = poses[pi]
        if len(pose) > 24:
            a, b = pose[11], pose[12]
            if min(a.visibility or 0, a.presence or 0, b.visibility or 0, b.presence or 0) >= .65:
                left, right = np.array((a.x * w, a.y * h)), np.array((b.x * w, b.y * h))
                span = np.linalg.norm(right - left)
                # Sample the shirt just below the shoulders, away from faces.
                drop = np.array((0, min(span * .65, h * .25)))
                inset = (right - left) * .15
                candidate.body_color = color_hist(frame, [left + inset, right - inset,
                                                          right - inset + drop, left + inset + drop])
                candidate.body_bounds = (min(left[0], right[0]) / w, min(left[1], right[1]) / h,
                                         max(left[0], right[0]) / w,
                                         min(h, max(left[1], right[1]) + drop[1]) / h)
    return candidates


class SubjectTracker:
    def __init__(self):
        self.anchor = None
        self.current = None
        self.last = None
        self.diagnostics = []

    @staticmethod
    def appearance(a, b):
        import cv2
        face = cv2.compareHist(a.face_color.astype(np.float32), b.face_color.astype(np.float32),
                               cv2.HISTCMP_BHATTACHARYYA)
        if a.body_color is not None and b.body_color is not None:
            body = cv2.compareHist(a.body_color.astype(np.float32), b.body_color.astype(np.float32),
                                   cv2.HISTCMP_BHATTACHARYYA)
            return .4 * face + .6 * body
        return face

    def choose(self, candidates, now, max_gap=10, update=True, people_count=None):
        diagnostics = []
        people_count = len(candidates) if people_count is None else people_count
        solo = people_count == 1 and len(candidates) == 1
        if solo:
            selected = candidates[0]
        elif self.anchor is None:
            if len(candidates) != 1 or candidates[0].pose_index is None or people_count > 1:
                return None, "처음에는 혼자 카메라 앞에 앉아 주세요"
            selected = candidates[0]
        else:
            if len(candidates) < people_count:
                return None, "측정 잠시 멈춤 · 여러 사람의 얼굴이 모두 보일 때 다시 확인합니다"
            if any(candidate.pose_index is None for candidate in candidates):
                return None, "측정 잠시 멈춤 · 여러 사람의 몸이 겹치거나 구분하기 어려워요"
            scores = []
            for candidate in candidates:
                distance = float(np.linalg.norm(candidate.center - self.current.center))
                distance /= max(candidate.scale, self.current.scale)
                appearance = self.appearance(self.anchor, candidate)
                scale_ratio = candidate.scale / self.current.scale
                # Keep the appearance reference fixed: a nearby newcomer must
                # not gradually replace the original subject's identity.
                stale = self.last is None or now - self.last > max_gap
                diagnostics.append({"face_index": candidate.face_index,
                                    "appearance": round(float(appearance), 3),
                                    "distance": round(distance, 3),
                                    "scale_ratio": round(scale_ratio, 3), "stale": stale})
                if (appearance > (.25 if stale else .42) or distance > (1.0 if stale else 1.6)
                        or not .55 < scale_ratio < 1.8):
                    continue
                scores.append((appearance * 2 + distance * .35, candidate))
            scores.sort(key=lambda item: item[0])
            if update:
                self.diagnostics = diagnostics
            if not scores or (len(scores) > 1 and scores[1][0] - scores[0][0] < .25):
                return None, "기존 사용자를 찾는 중 · 다른 사람으로 바꾸지 않고 기다립니다"
            selected = scores[0][1]
            for other in candidates:
                if other is selected:
                    continue
                overlap = np.linalg.norm(other.center - selected.center) < .6 * (other.scale + selected.scale)
                if other.body_bounds is not None and selected.body_bounds is not None:
                    a, b = selected.body_bounds, other.body_bounds
                    area = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
                    smallest = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
                    overlap |= smallest > 0 and area / smallest > .15
                if overlap:
                    return None, "측정 잠시 멈춤 · 두 사람이 겹쳐 보여요. 떨어지면 다시 측정합니다"
                if other.scale > selected.scale * 1.2:
                    return None, "측정 잠시 멈춤 · 다른 사람이 카메라에 더 가까이 있어요"
        if update:
            if self.anchor is None or solo:
                self.anchor = selected
            self.current, self.last = selected, now
            self.diagnostics = diagnostics
        return selected, ""


def subject_hands(hands, poses, selected_pose, face_scale):
    """Reject hands whose wrist is closer to another detected person's wrist."""
    if selected_pose is None:
        return []
    def wrists(pose):
        return [np.array((pose[i].x, pose[i].y)) for i in (15, 16)
                if len(pose) > i and min(pose[i].visibility or 0, pose[i].presence or 0) >= .65]
    own = wrists(poses[selected_pose])
    rivals = [w for i, pose in enumerate(poses) if i != selected_pose for w in wrists(pose)]
    selected = []
    for hand in hands:
        if not hand or not own:
            continue
        wrist = np.array((hand[0].x, hand[0].y))
        near = min(np.linalg.norm(wrist - w) for w in own)
        other = min((np.linalg.norm(wrist - w) for w in rivals), default=math.inf)
        if near + face_scale * .1 < other:
            selected.append(hand)
    return selected
