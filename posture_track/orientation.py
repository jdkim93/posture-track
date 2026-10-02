"""Quarter-turn camera correction using upright face evidence."""
from __future__ import annotations

import numpy as np


def rotate_frame(frame, turns):
    """Counterclockwise quarter turns; contiguous storage for MediaPipe."""
    return np.ascontiguousarray(np.rot90(frame, turns))


def upright_score(result, shape):
    # Multiple subjects must never choose the camera orientation.
    if len(result.face_landmarks) != 1:
        return 0.0
    face = result.face_landmarks[0]
    if len(face) <= 152:
        return 0.0
    h, w = shape[:2]
    top, chin = face[10], face[152]
    vector = np.array([(chin.x - top.x) * w, (chin.y - top.y) * h])
    length = np.linalg.norm(vector)
    if not np.isfinite(length) or length < min(h, w) * .05:
        return 0.0
    score = float(vector[1] / length)
    return score if score >= .75 else 0.0


class CameraOrientation:
    def __init__(self):
        self.turns = 0
        self.candidate = None
        self.last = None

    def correct(self, frame, probe, now, max_gap):
        current = rotate_frame(frame, self.turns)
        result = probe(current)
        if getattr(result,"freeze_rotation",False):
            self.candidate = self.last = None
            return current, True, False
        if len(result.face_landmarks) > 1:
            self.candidate = self.last = None
            return current, False, False
        if upright_score(result, current.shape):
            self.candidate = self.last = None
            return current, True, False
        scores = []
        for turns in range(4):
            if turns == self.turns:
                continue
            candidate = rotate_frame(frame, turns)
            scores.append((upright_score(probe(candidate), candidate.shape), turns))
        scores.sort(reverse=True)
        # Ambiguous/missing evidence is unknown, not a posture measurement.
        if not scores or scores[0][0] == 0 or (len(scores) > 1 and scores[1][0] > 0):
            self.candidate = self.last = None
            return current, False, False
        turns = scores[0][1]
        if (self.candidate != turns or self.last is None or
                not 0 < now - self.last <= max_gap):
            self.candidate, self.last = turns, now
            return current, False, False
        self.turns = turns
        self.candidate = self.last = None
        return rotate_frame(frame, turns), True, True
