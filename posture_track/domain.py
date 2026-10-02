from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import TARGETS, Settings, Target, atomic_json


@dataclass
class Observation:
    timestamp: float
    view: str = "unknown"
    metrics: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    pose: list[tuple[float, float, float]] = field(default_factory=list)
    face: list[tuple[float, float]] = field(default_factory=list)
    hands: list[list[tuple[float, float]]] = field(default_factory=list)
    rotation: list[list[float]] | None = None
    quality: dict = field(default_factory=dict)
    world: list = field(default_factory=list)


@dataclass
class Baseline:
    view: str
    values: dict[str, float]
    noise: dict[str, float]
    rotation: list[list[float]] | None = None
    camera_signature: str = ""
    profile_id: str = ""
    label: str = ""


class Profiles:
    def __init__(self, path: Path):
        self.path = path
        self.items: dict[str, Baseline] = {}
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") in (1,2):
                for key, value in data.get("profiles", {}).items():
                    self.items[key] = Baseline(**value)
        except (OSError, ValueError, TypeError, AttributeError):
            self.items = {}

    def save(self, baseline: Baseline) -> None:
        self.save_many([baseline])

    def save_many(self, baselines: list[Baseline]) -> None:
        updated = {**self.items, **{b.profile_id or b.view: b for b in baselines}}
        atomic_json(self.path, {"schema": 2, "profiles": {k: asdict(v) for k, v in updated.items()}})
        self.items = updated

    def delete(self, identity):
        updated = {key: value for key,value in self.items.items() if key != identity}
        atomic_json(self.path, {"schema": 2, "profiles": {k: asdict(v) for k,v in updated.items()}})
        self.items = updated

    def select(self,observation,signature,previous=None):
        yaw=observation.metrics.get("view_yaw",observation.metrics.get("upper_yaw"))
        pitch=observation.metrics.get("view_pitch",observation.metrics.get("upper_pitch"))
        candidates=[]
        for key,profile in self.items.items():
            if profile.camera_signature!=signature:
                continue
            angle=profile.values.get("view_yaw",profile.values.get("upper_yaw"))
            if angle is None and profile.rotation is not None:
                angle=math.degrees(math.atan2(profile.rotation[0][2],profile.rotation[2][2]))
            if yaw is not None and angle is not None and math.isfinite(yaw) and math.isfinite(angle):
                distance=abs(yaw-angle)
                if math.isfinite(distance):
                    candidates.append((distance,key,profile))
            elif observation.view==profile.view:
                candidates.append((0,key,profile))
        if not candidates or (observation.view=="unknown" and yaw is None):
            return None
        # Posture pitch must not choose a horizontally different reference.
        # Use it only among screens whose registered horizontal directions
        # coincide, where vertical placement is otherwise indistinguishable.
        nearest=min(candidates,key=lambda item:item[0])
        nearest_yaw=nearest[2].values.get("view_yaw",nearest[2].values.get("upper_yaw"))
        if pitch is not None and math.isfinite(pitch) and nearest_yaw is not None:
            scored=[]
            for distance,key,profile in candidates:
                base_yaw=profile.values.get("view_yaw",profile.values.get("upper_yaw"))
                base_pitch=profile.values.get("view_pitch",profile.values.get("upper_pitch"))
                if base_yaw is not None and abs(base_yaw-nearest_yaw)<=3 and base_pitch is not None and math.isfinite(base_pitch):
                    distance=math.hypot(distance,.2*(pitch-base_pitch))
                scored.append((distance,key,profile))
            # Do not apply pitch to a lone horizontally distinct candidate.
            same_yaw=sum(abs(profile.values.get("view_yaw",profile.values.get("upper_yaw",float('inf')))-nearest_yaw)<=3 for _,_,profile in candidates)
            if same_yaw>1:
                candidates=scored
        eye_keys=("screen_eye_span","screen_nose_offset")
        # Compare the same evidence across candidates. Existing registrations
        # without eye data continue using yaw until explicitly re-registered.
        use_eyes=all(key in observation.metrics and math.isfinite(observation.metrics[key]) for key in eye_keys) and all(
            all(key in profile.values for key in eye_keys) for _,_,profile in candidates)
        if use_eyes:
            scored=[]
            for distance,key,profile in candidates:
                span=abs(observation.metrics[eye_keys[0]]-profile.values[eye_keys[0]])/max(.025,4*profile.noise.get(eye_keys[0],0))
                nose=abs(observation.metrics[eye_keys[1]]-profile.values[eye_keys[1]])/max(.035,4*profile.noise.get(eye_keys[1],0))
                # Eye geometry is supplementary: projection changes during
                # slouching must not outweigh a clear head direction match.
                scored.append((distance+min(2, .5*span+nose),key,profile))
            candidates=scored
            if not candidates:
                return None
        candidates.sort(key=lambda item:item[0])
        for distance,key,profile in candidates:
            if key==previous and distance<=candidates[0][0]+3:
                return profile
        return candidates[0][2]


class Calibration:
    DURATION=8
    MAX_DURATION=10
    SETTLE=.6
    MIN_SAMPLES=15
    MIN_SPAN=5
    def __init__(self, start: float, view: str):
        self.start = start
        self.view = view
        self.samples: list[Observation] = []

    def add(self, obs: Observation) -> None:
        if obs.view == self.view and len(obs.metrics) >= 2 and obs.timestamp >= self.start + self.SETTLE:
            if self.samples and obs.timestamp - self.samples[-1].timestamp > 1:
                self.samples.clear()
            self.samples.append(obs)

    def finish(self, signature: str) -> Baseline:
        if len(self.samples) < self.MIN_SAMPLES or self.samples[-1].timestamp - self.samples[0].timestamp < self.MIN_SPAN:
            raise ValueError("자세를 충분히 읽지 못했습니다. 같은 화면을 바라보며 ‘올바른 자세 등록’을 다시 눌러 주세요.")
        keys = set.union(*(set(s.metrics) for s in self.samples))
        keys -= {"touch_distance", "forward", "relative_rotation"}
        values, noise = {}, {}
        for key in keys:
            points = [s.metrics[key] for s in self.samples if key in s.metrics and math.isfinite(s.metrics[key])]
            if len(points) < max(self.MIN_SAMPLES, math.ceil(len(self.samples) * .8)):
                continue
            if key == "side_pair" and len(set(points)) != 1:
                raise ValueError("등록 중 바라보는 방향이 바뀌었습니다. 같은 화면을 보며 다시 등록해 주세요.")
            if key == "shoulder_angle":
                anchor = points[0]
                points = [anchor + line_delta(x, anchor) for x in points]
            median = statistics.median(points)
            mad = statistics.median(abs(x - median) for x in points) * 1.4826
            limit = 5.0 if key in ("roll", "pitch", "shoulder_angle", "torso_pitch", "upper_pitch", "upper_yaw", "upper_body_yaw", "view_yaw", "view_pitch") else 0.08
            if key=="upper_span":
                limit=max(limit,abs(median)*.04)
            ordered=sorted(points)
            spread=ordered[math.ceil((len(ordered)-1)*.9)]-ordered[math.floor((len(ordered)-1)*.1)]
            if key not in ("side_scale", "forward_pixels", "side_pair", "upper_scale", "upper_eye_scale") and (mad > limit or spread>3*limit):
                if key in ("upper_depth","head_gap"):
                    continue  # Optional model depth must not reject a stable visible reference.
                part={"upper_span":"얼굴 대비 어깨 폭","upper_gap":"목과 어깨의 간격",
                      "shoulder_angle":"양쪽 어깨 높이","view_yaw":"바라보는 방향",
                      "upper_yaw":"바라보는 방향","pitch":"머리 각도","view_pitch":"머리 각도",
                      "upper_pitch":"머리 각도","roll":"머리 기울임",
                      "screen_eye_span":"눈과 얼굴의 비율","screen_nose_offset":"얼굴 방향"}.get(key,"자세")
                raise ValueError(f"{part} 변화가 커서 기준을 저장하지 못했어요. 같은 화면을 바라보며 잠시 자세를 유지해 주세요.")
            values[key], noise[key] = median, mad
        if "forward_pixels" in values and "side_scale" in values:
            scale = values["side_scale"]
            if scale > 0:
                values["forward"] = values["forward_pixels"] / scale
                noise["forward"] = noise["forward_pixels"] / scale
        if not {"roll", "forward"}.intersection(values) and not ("pitch" in values and "view_yaw" in values):
            raise ValueError("얼굴/귀/어깨가 충분히 보이지 않습니다.")
        rotations = [s.rotation for s in self.samples if s.rotation is not None]
        rotation = None
        if rotations:
            import numpy as np
            u, _, vt = np.linalg.svd(np.mean(rotations, axis=0))
            correction = np.diag([1, 1, np.linalg.det(u @ vt)])
            rotation = (u @ correction @ vt).tolist()
        return Baseline(self.view, values, noise, rotation, signature)


def line_delta(a: float, b: float) -> float:
    return (a - b + 90) % 180 - 90


@dataclass
class Result:
    status: str
    value: float | None = None
    limit: float | None = None
    reason: str = ""
    held: float = 0.0


class Temporal:
    def __init__(self):
        self.reset()

    def reset(self):
        self.last: float | None = None
        self.filtered: float | None = None
        self.bad = False
        self.candidate: float | None = None
        self.count = 0
        self.bad_since: float | None = None

    def update(self, value: float, enter: float, now: float, max_gap: float, lower=False, fast_recovery=False,
               response_seconds=2, hold_seconds=3) -> Result:
        if self.last is not None and (now <= self.last or now - self.last > max_gap):
            self.reset()
        dt = now - self.last if self.last is not None else 0
        recovery = fast_recovery and self.bad
        alpha = 1 - math.exp(-dt / (.25 if recovery else response_seconds)) if self.last is not None else 1
        self.filtered = value if self.filtered is None else self.filtered + alpha * (value - self.filtered)
        self.last = now
        exit_limit = enter * (1.4 if lower else 0.65)
        outside = self.filtered < enter if lower else self.filtered > enter
        recovered = self.filtered > exit_limit if lower else self.filtered < exit_limit
        changing = recovered if self.bad else outside
        if changing:
            if self.candidate is None:
                self.candidate, self.count = now, 1
            else:
                self.count += 1
            if self.count >= 2 and now - self.candidate >= (.4 if recovery else hold_seconds):
                self.bad = not self.bad
                self.bad_since = now if self.bad else None
                self.candidate, self.count = None, 0
        else:
            self.candidate, self.count = None, 0
        status = "bad" if self.bad else "good"
        if self.candidate is not None:
            status = "recovering" if self.bad else "candidate"
        held = now - self.bad_since if self.bad_since is not None else 0
        return Result(status, self.filtered, enter, held=held)


class ConsecutiveProximity:
    """Two distinct, consecutive near observations confirm face-touch behavior."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.last = self.value = self.bad_since = None
        self.count = 0

    def update(self, value, enter, now, max_gap):
        if not math.isfinite(value) or not math.isfinite(now):
            self.reset()
            return Result("unknown")
        if self.last is not None and now == self.last:
            status = "bad" if self.count >= 2 else "candidate" if self.count else "good"
            return Result(status, self.value, enter, held=now-self.bad_since if self.bad_since is not None else 0)
        if self.last is not None and (now < self.last or now - self.last > max_gap):
            self.reset()
        self.last, self.value = now, value
        if value >= enter:
            self.count = 0
            self.bad_since = None
            return Result("good", value, enter)
        self.count = min(2, self.count + 1)
        if self.count == 1:
            return Result("candidate", value, enter)
        if self.bad_since is None:
            self.bad_since = now
        return Result("bad", value, enter, held=now - self.bad_since)


class Evaluator:
    def __init__(self):
        self.states = {t.id: ConsecutiveProximity() if t.behavior else Temporal() for t in TARGETS}
        self.context = None
        self.suspended_at = self.last_observation = None

    def reset(self):
        for state in self.states.values():
            state.reset()
        self.context = None
        self.suspended_at = self.last_observation = None

    def suspend_screen_transition(self, obs, settings):
        if self.suspended_at is None:
            self.suspended_at = self.last_observation if self.last_observation is not None else obs.timestamp
        results={t.id: Result("off" if not settings.enabled[t.id] else "research" if not t.available else "unknown",
                             reason="바라보는 화면 확인 중") for t in TARGETS}
        for target in TARGETS:
            if not target.behavior:
                continue
            state=self.states[target.id]
            value=obs.metrics.get(target.metric)
            if settings.enabled[target.id] and value is not None and math.isfinite(value):
                results[target.id]=state.update(value,target.threshold,obs.timestamp,settings.interval*2)
                results[target.id].reason="손·손가락과 얼굴 영역의 겹침을 연속 확인합니다"
            else:
                state.reset()
        return results

    def evaluate(self, obs: Observation, baseline: Baseline | None, settings: Settings, fast_recovery=False) -> dict[str, Result]:
        context = (obs.view, settings.version, id(baseline))
        if context != self.context:
            if self.context is not None and self.context[1]==settings.version:
                # Face touch belongs to the visible face/hand sequence, not to
                # a posture view or monitor registration.
                for target in TARGETS:
                    if not target.behavior:
                        self.states[target.id].reset()
                self.suspended_at=self.last_observation=None
            else:
                self.reset()
            self.context = context
        elif self.suspended_at is not None:
            duration=obs.timestamp-self.suspended_at
            if 0<=duration<=2:
                for target in TARGETS:
                    if target.behavior:
                        continue
                    state=self.states[target.id]
                    for field in ("last","candidate","bad_since"):
                        value=getattr(state,field)
                        if value is not None:
                            shifted=value+duration
                            if field=="last":
                                shifted=min(shifted,obs.timestamp-1e-6)
                            setattr(state,field,shifted)
            else:
                self.reset()
                self.context=context
            self.suspended_at=None
        self.last_observation=obs.timestamp
        results = {}
        for t in TARGETS:
            state = self.states[t.id]
            if not t.available:
                result = Result("research", reason="측정 타당성 검증 후 제공")
            elif not settings.enabled[t.id]:
                result = Result("off")
            elif obs.view == "unknown" and not t.behavior:
                result = Result("unknown", reason="사용자와 바라보는 방향을 확인하고 있어요")
            elif not t.behavior and baseline is None:
                result = Result("uncalibrated", reason="이 방향을 보며 ‘올바른 자세 등록’을 눌러 주세요")
            elif t.id=='forward_head' and not obs.view.startswith('side'):
                from .upper_body import forward_neck_change
                deviation,reason,needs_baseline=forward_neck_change(obs.metrics,baseline,settings.posture_sensitivity=='sensitive')
                if deviation is None:
                    result=Result('uncalibrated' if needs_baseline else 'unknown',reason=reason)
                else:
                    result=state.update(deviation,1,obs.timestamp,settings.interval*2,fast_recovery=fast_recovery,
                                        response_seconds=.8,hold_seconds=2)
                    result.reason=reason
            elif t.id == "slouch":
                if obs.view.startswith("side"):
                    # Preserve the existing side/full-body rule only when hips
                    # really are visible; upper-body-only side views are unsupported.
                    if "torso_pitch" in obs.metrics and "torso_pitch" in baseline.values:
                        deviation = obs.metrics["torso_pitch"]-baseline.values["torso_pitch"]
                        if math.isfinite(deviation):
                            factor, noise_factor = settings.posture_limits
                            result = state.update(deviation, max(12*factor,noise_factor*baseline.noise.get("torso_pitch",0)),obs.timestamp,settings.interval*2,fast_recovery=fast_recovery)
                            result.reason = "실제로 보이는 어깨·엉덩이 각도 변화"
                        else:
                            result = Result("unknown",reason="유효하지 않은 상체 측정값")
                    else:
                        result = Result("unsupported",reason="상체만 보일 때 어깨 말림은 정면·사선에서 확인합니다")
                else:
                    from .upper_body import upper_body_change
                    deviation,reason,needs_baseline = upper_body_change(obs.metrics,baseline,settings.posture_sensitivity=='sensitive')
                    if deviation is None:
                        result = Result("uncalibrated" if needs_baseline else "unknown",reason=reason)
                    else:
                        result = state.update(deviation,t.threshold,obs.timestamp,settings.interval*2,fast_recovery=fast_recovery,
                                              response_seconds=.8,hold_seconds=2)
                        result.reason = reason
            elif t.metric not in obs.metrics:
                unsupported = ((t.id in ("forward_head", "slouch") and not obs.view.startswith("side"))
                               or (t.id in ("uneven_shoulders", "lean") and obs.view.startswith("side")))
                result = Result("unsupported" if unsupported else "unknown",
                                reason=obs.reasons.get(t.metric, "필요한 부위/측정 근거가 부족합니다"))
            elif not math.isfinite(obs.metrics[t.metric]):
                result = Result("unknown", reason="유효하지 않은 측정값")
            elif t.behavior:
                result = state.update(obs.metrics[t.metric], t.threshold, obs.timestamp, settings.interval * 2)
                result.reason = "손이 얼굴 근처에 연속 두 번 보여 만지기로 추정합니다"
            elif t.metric not in baseline.values:
                result = Result("unknown", reason="필요한 지표를 확보하도록 이 방향을 다시 보정하세요")
            else:
                value = obs.metrics[t.metric]
                base = baseline.values[t.metric]
                if t.metric in ("pitch", "roll") and obs.metrics.get("relative_rotation"):
                    base = 0.0
                if t.id == "forward_head":
                    if baseline.values.get("side_pair") != obs.metrics.get("side_pair"):
                        results[t.id] = Result("unknown", reason="보정 때와 다른 귀/어깨를 관측하고 있습니다")
                        state.reset()
                        continue
                    scale = baseline.values.get("side_scale", 0)
                    current_scale = obs.metrics.get("side_scale", 0)
                    if not scale or not (0.75 < current_scale / scale < 1.25):
                        results[t.id] = Result("unknown", reason="거리/머리 크기가 보정 때와 달라 재확인 필요")
                        state.reset()
                        continue
                    value = obs.metrics["forward_pixels"] / scale
                if t.metric == "shoulder_angle":
                    deviation = abs(line_delta(value, base))
                else:
                    deviation = value - base
                    if t.id not in ("forward_head", "slouch"):
                        deviation = abs(deviation)
                factor, noise_factor = settings.posture_limits
                limit = max(t.threshold*factor, noise_factor*baseline.noise.get(t.metric, 0))
                result = state.update(deviation, limit, obs.timestamp, settings.interval * 2, fast_recovery=fast_recovery)
                result.reason = "등록한 내 자세와 비교한 결과"
            if result.status in ("research", "off", "unknown", "unsupported", "uncalibrated"):
                state.reset()
            results[t.id] = result
        return results


def overall(results: dict[str, Result], settings: Settings) -> str:
    active = [results[t.id].status for t in TARGETS if not t.behavior and t.available and settings.enabled[t.id]]
    if not active:
        return "disabled"
    supported = [s for s in active if s != "unsupported"]
    if not supported:
        return "unknown"
    if any(s in ("bad", "recovering") for s in supported):
        return "bad"
    if all(s == "good" for s in supported):
        return "good"
    return "unknown"


class AlertTimer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.started = self.last = self.sent = None
        self.suspended_at=None

    def suspend(self, now):
        if self.last is not None and self.suspended_at is None:
            self.suspended_at=self.last

    def update(self, is_bad: bool, now: float, settings: Settings) -> bool:
        if self.suspended_at is not None:
            duration=now-self.suspended_at
            if 0<=duration<=2:
                for field in ("started","last","sent"):
                    value=getattr(self,field)
                    if value is not None:
                        setattr(self,field,value+duration)
            else:
                self.reset()
            self.suspended_at=None
        if not is_bad or (self.last is not None and now - self.last > settings.interval * 2):
            self.reset()
        if not is_bad:
            return False
        if self.started is None:
            self.started = now
        self.last = now
        if now - self.started < settings.alert_seconds:
            return False
        if self.sent is not None and now - self.sent < settings.repeat_seconds:
            return False
        self.sent = now
        return True
