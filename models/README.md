# 로컬 모델

개발 준비 단계에서 `python tools/prepare_models.py`를 명시적으로 실행한다.
Google의 버전 1 Pose Full/Lite, Face, Hand 모델을 받아 파일별 SHA256을 manifest.json에 기록한다. 실제 앱의 자세 추론에는 Pose Full을 사용한다.
앱은 이 다운로드 도구를 호출하지 않고, manifest와 실제 모델의 해시를 확인한다.
모델 누락/변경 시 분석 시작을 거절하고 로컬 오류를 안내한다.

이 manifest는 다운로드한 파일을 고정하는 무결성 기록이며 공급자의 서명 검증은 아니다.
배포본에는 모델 및 manifest를 함께 포함해야 한다. 재다운로드 도구 실행으로 manifest를
갱신하는 작업은 개발자가 관리하며 실행 중 자동 갱신은 하지 않는다.
