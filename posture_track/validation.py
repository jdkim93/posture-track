"""Local, user-labelled trials. Reports contain counts, never images or landmarks."""
from dataclasses import dataclass, field
import math
import statistics
from .domain import Result

TRIAL_SECONDS = 10.0
SETTLE_SECONDS = 5.0
TRIAL_INTERVAL = 0.5
CAPTURE_AT = 7.5


@dataclass
class Trial:
    target: str
    expected: str
    start: float
    view: str
    version: int
    counts: dict[str, int] = field(default_factory=dict)
    first_match: float | None = None
    deviations: list[float] = field(default_factory=list)
    thresholds: list[float] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    condition: str = ""

    def observe(self, now: float, view: str, version: int, results: dict[str, Result]):
        if view != self.view or version != self.version:
            raise ValueError("검증 중 방향/설정이 바뀌었습니다. 같은 조건에서 다시 검증하세요.")
        status = results[self.target].status
        # Ignore the first 5 seconds while the temporal filter settles.
        if now - self.start >= SETTLE_SECONDS:
            self.status_counts[status] = self.status_counts.get(status, 0) + 1
            key = status if status in ("good", "bad") else "unknown"
            self.counts[key] = self.counts.get(key, 0) + 1
            result = results[self.target]
            if result.value is not None and math.isfinite(result.value):
                self.deviations.append(result.value)
            if result.limit is not None and math.isfinite(result.limit):
                self.thresholds.append(result.limit)
            if key == self.expected and self.first_match is None:
                self.first_match = now - self.start

    def report(self):
        decided = self.counts.get("good", 0) + self.counts.get("bad", 0)
        total = sum(self.counts.values())
        return {"target": self.target, "user_label": self.expected, "view": self.view,
                "counts": self.counts, "coverage": decided / total if total else None,
                "status_counts": self.status_counts,
                "condition": self.condition,
                "agreement": self.counts.get(self.expected, 0) / decided if decided else None,
                "first_match_seconds_from_start": self.first_match,
                "deviation_summary": {"min": min(self.deviations), "median": statistics.median(self.deviations),
                                      "max": max(self.deviations)} if self.deviations else None,
                "threshold_median": statistics.median(self.thresholds) if self.thresholds else None,
                "timing": {"planned_seconds": TRIAL_SECONDS, "settle_seconds": SETTLE_SECONDS,
                           "analysis_interval_seconds": TRIAL_INTERVAL},
                "note": "사용자 표기 대비 표본 일치율; 임상 정확도나 독립 표본 precision/recall이 아님"}


class ReferenceTrial(Trial):
    """One normal posture interval, with separate results for every enabled posture."""
    def __init__(self, start, view, version, targets, behaviors=()):
        super().__init__("reference", "good", start, view, version)
        self.items = {target: Trial(target, "good", start, view, version) for target in targets}
        self.behaviors = set(behaviors)

    def observe(self, now, view, version, results):
        for trial in self.items.values():
            trial.observe(now, view, version, results)
        statuses = [results[k].status for k in self.items if k not in self.behaviors and results[k].status != "unsupported"]
        status = "unknown"
        if any(s in ("bad", "recovering") for s in statuses):
            status = "bad"
        elif statuses and all(s == "good" for s in statuses):
            status = "good"
        super().observe(now, view, version, {"reference": Result(status)})

    def report(self):
        result = super().report()
        result["per_target"] = {key: trial.report() for key, trial in self.items.items()}
        result["note"] += " · 미지원 항목은 전체 판정에서 제외하고 항목별 판정 불가로 기록"
        return result
