"""Readable live feedback built from the actual evaluated results."""
from .config import TARGETS


def posture_feedback(results, observation=None, calibrating=False):
    names = {t.id: t.label for t in TARGETS}
    active = {key: value for key, value in results.items()
              if key in names and key != "face_touch" and value.status not in ("off", "research")}
    if calibrating:
        return "올바른 자세 등록 중", "어깨를 편하게 펴고 화면을 바라보며 잠시 유지해 주세요", "#a8c8e4"
    if observation and observation.quality.get("subject_tracking") == "waiting":
        return "측정 잠시 멈춤", observation.reasons.get("subject", "사용자가 구분되면 다시 측정합니다"), "#d0b28d"
    for status, title, color in (("bad", "자세 이탈 감지", "#e59c9e"),
                                 ("recovering", "자세가 돌아오는 중", "#d0b28d"),
                                 ("candidate", "자세 변화 확인 중", "#d0b28d")):
        matching = [names[key] for key, value in active.items() if value.status == status]
        if matching:
            return title, " · ".join(matching), color
    if any(value.status == "uncalibrated" for value in active.values()):
        return "먼저 내 자세를 등록해 주세요", "위의 ‘올바른 자세 등록’을 누르면 자동으로 저장됩니다", "#d0b28d"
    touch = results.get("face_touch")
    if touch and touch.status == "bad":
        return "얼굴 만지기 추정", "손이 얼굴 근처에 연속해서 보여요 · 자세 점수와는 별도입니다", "#d0b28d"
    good = [names[key] for key, value in active.items() if value.status == "good"]
    unknown = [names[key] for key, value in active.items() if value.status == "unknown"]
    if good and not unknown:
        return "등록한 자세 범위예요", "지금 측정 가능한 자세 항목이 기준 범위 안에 있어요", "#a8c8e4"
    if good:
        return "일부 자세를 확인하고 있어요", "잘 보이지 않는 항목: " + " · ".join(unknown), "#d0b28d"
    if active or (observation and observation.view == "unknown"):
        return "얼굴과 어깨를 확인하고 있어요", "얼굴과 어깨가 보이도록 앉아 주세요", "#a0a6b1"
    return "자세 감지가 꺼져 있어요", "오른쪽에서 확인할 자세를 켜 주세요", "#a0a6b1"
