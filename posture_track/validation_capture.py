"""Explicit test-only local capture. No upload or model-service client."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from .config import atomic_json


def save_capture(directory: Path, frame, measurement: dict, report: dict) -> dict[str, str]:
    import cv2

    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise OSError("테스트 사진 인코딩 실패")
    payload = encoded.tobytes()
    target = directory / "captures" / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    photo = target / "raw.png"
    photo.write_bytes(payload)
    try:
        atomic_json(target / "measurement.json", {
            "schema": 1, "test_only": True, "image": "raw.png",
            "image_sha256": hashlib.sha256(payload).hexdigest(),
            "measurement": measurement, "trial": report,
            "note": "같은 추론 프레임의 원본 사진과 수치. 자동 외부 전송 없음. 한 장으로 지속 시간이나 의학적 진단을 확인할 수 없음.",
        })
    except Exception:
        photo.unlink(missing_ok=True)
        target.rmdir()
        raise
    return {"image": str(photo.relative_to(directory)),
            "measurement": str((target / "measurement.json").relative_to(directory))}
