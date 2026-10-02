"""Conservative shoulder validity checks; never move landmarks to clothing edges."""
from __future__ import annotations

import math

import numpy as np


class ShoulderGuard:
    def __init__(self):
        self.history = {}
        self.candidates = {}
        self.boundary_candidates = {}

    def check(self, pose, face, mask, shape, now, max_gap=10):
        h, w = shape[:2]
        checked = list(pose)
        diagnostics = {}
        if len(face) <= 454:
            anchor, scale = None, None
        else:
            anchor = (np.asarray(face[234]) + np.asarray(face[454])) / 2
            scale = float(np.linalg.norm(np.asarray(face[10]) - np.asarray(face[152])))
            if not np.all(np.isfinite(anchor)) or not math.isfinite(scale) or scale < h * .05:
                anchor, scale = None, None
        foreground = np.asarray(mask).squeeze() if mask is not None else None
        if foreground is not None and (foreground.ndim != 2 or not np.all(np.isfinite(foreground))):
            foreground = None
        for index in (11, 12):
            if index >= len(pose):
                self.history.pop(index, None)
                self.candidates.pop(index, None)
                self.boundary_candidates.pop(index, None)
                continue
            x, y, confidence = pose[index]
            reason, probability = "", None
            boundary = (all(math.isfinite(v) for v in (x, y)) and
                        (min(x, w - 1 - x) < w * .05 or min(y, h - 1 - y) < h * .05))
            if not all(math.isfinite(v) for v in (x, y, confidence)) or not (0 <= x < w and 0 <= y < h):
                reason = "어깨가 화면 밖이거나 유효하지 않습니다"
            elif confidence < .65:
                reason = "어깨 특징점 신뢰도가 부족합니다"
            elif anchor is None:
                reason = "얼굴-어깨 위치 관계를 확인할 수 없습니다"
            elif y < anchor[1] - scale * .25 or np.linalg.norm(np.asarray((x, y)) - anchor) > scale * 4:
                reason = "얼굴-어깨 위치 관계가 비정상적입니다"
            elif foreground is None:
                reason = "사람 영역을 확인할 수 없습니다"
            else:
                mh, mw = foreground.shape
                mx, my = min(mw - 1, int(x / w * mw)), min(mh - 1, int(y / h * mh))
                radius = max(1, int(scale / h * mh * .02))
                probability = float(np.mean(foreground[max(0, my-radius):min(mh, my+radius+1),
                                                       max(0, mx-radius):min(mw, mx+radius+1)]))
                if probability < .5:
                    reason = "어깨 점이 사람 영역과 맞지 않습니다"
            # Shoulder-top joints do not require visible arms or torso. Reduced
            # confidence requires a second distinct, consistent observation;
            # never clamp an out-of-frame model projection onto the border.
            if not reason and confidence < .85:
                position = (np.asarray((x, y)) - anchor) / scale
                candidate = self.boundary_candidates.get(index)
                if (candidate is None or now <= candidate[0] or now - candidate[0] > max_gap
                        or np.linalg.norm(position - candidate[1]) > .10):
                    self.boundary_candidates[index] = (now, position)
                    reason = "어깨 윗부분의 점을 연속 관측으로 확인하고 있습니다"
                else:
                    self.boundary_candidates[index] = (now, position)
            else:
                self.boundary_candidates.pop(index, None)
            if not reason:
                position = (np.asarray((x, y)) - anchor) / scale
                previous = self.history.get(index)
                if previous and (now <= previous[0] or now - previous[0] > max_gap):
                    self.history.pop(index, None)
                    self.candidates.pop(index, None)
                    previous = None
                if previous and np.linalg.norm(position - previous[1]) > .18:
                    candidate = self.candidates.get(index)
                    if candidate and np.linalg.norm(position - candidate[1]) <= .10 and now - candidate[0] >= 1:
                        self.candidates.pop(index, None)
                    else:
                        if candidate is None or np.linalg.norm(position - candidate[1]) > .10:
                            self.candidates[index] = (now, position)
                        reason = "어깨 위치의 급격한 변화를 재확인하고 있습니다"
                if not reason:
                    self.history[index] = (now, position)
                    self.candidates.pop(index, None)
            if reason:
                checked[index] = (x, y, 0.0)
                if "급격한" not in reason:
                    self.history.pop(index, None)
                    self.candidates.pop(index, None)
            diagnostics[str(index)] = {"raw_point": [x, y, confidence], "accepted": not bool(reason),
                                       "foreground_probability": probability, "reason": reason,
                                       "boundary": boundary, "partial": boundary and not bool(reason)}
        return checked, diagnostics
