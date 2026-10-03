from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .runtime import resource_root

ROOT = resource_root()
INTERVALS = {"Low": 5.0, "Mid": 2.0, "High": 0.5}
ALERT_DELAYS = {"10초":10,"20초":20,"1분":60,"2분":120,"5분":300,"10분":600,"20분":1200}
POSTURE_SENSITIVITY = {"standard": (.60, 2.5), "sensitive": (.475, 2.25)}


@dataclass(frozen=True)
class Target:
    id: str
    label: str
    metric: str
    threshold: float
    behavior: bool = False
    available: bool = True


TARGETS = (
    Target("forward_head", "머리가 앞으로 빠진 자세", "forward", 0.18),
    Target("slouch", "상체 구부정 · 어깨 말림", "upper_slouch", 1.0),
    Target("head_bend", "고개 숙임 · 젖힘", "pitch", 15.0),
    Target("lean", "머리 · 상체 한쪽 기울임", "roll", 10.0),
    Target("uneven_shoulders", "어깨 비대칭", "shoulder_angle", 3.5),
    Target("shrug", "양쪽 어깨 움츠림 (연구 중)", "head_gap", 0.15, available=False),
    Target("face_touch", "얼굴 만지기", "touch_distance", 0.06, behavior=True),
)


@dataclass
class Settings:
    camera: int = 0
    performance: str = "Mid"
    posture_sensitivity: str = "standard"
    alert_seconds: int = 20
    repeat_seconds: int = 600
    muted: bool = True
    audio_schema: int = 1
    version: int = 1
    enabled: dict[str, bool] = field(default_factory=lambda: {
        t.id: t.available for t in TARGETS
    })

    @property
    def interval(self) -> float:
        return INTERVALS[self.performance]

    @property
    def posture_limits(self) -> tuple[float, float]:
        return POSTURE_SENSITIVITY[self.posture_sensitivity]

    @classmethod
    def load(cls, path: Path) -> Settings:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        result = cls()
        if not isinstance(data, dict):
            return result
        def number(key, default):
            try:
                return int(data.get(key, default))
            except (TypeError, ValueError, OverflowError):
                return default
        result.camera = max(0, min(9, number("camera", 0)))
        result.performance = data.get("performance", "Mid")
        if not isinstance(result.performance, str) or result.performance not in INTERVALS:
            result.performance = "Mid"
        result.posture_sensitivity = "sensitive" if data.get("posture_sensitivity") == "sensitive" else "standard"
        requested_alert=number("alert_seconds",result.alert_seconds)
        result.alert_seconds=min(ALERT_DELAYS.values(),key=lambda seconds:abs(seconds-requested_alert))
        result.repeat_seconds = max(60, number("repeat_seconds", 600))
        # Old "muted" suppressed the whole popup; migrate to silent sound only.
        result.muted = data.get("muted") is not False if data.get("audio_schema")==1 else True
        result.version = max(1, number("version", 1))
        stored = data.get("enabled", {})
        if isinstance(stored, dict):
            for t in TARGETS:
                result.enabled[t.id] = bool(stored.get(t.id, result.enabled[t.id])) and t.available
        return result

    def save(self, path: Path) -> None:
        atomic_json(path, asdict(self))


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
