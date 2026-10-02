from __future__ import annotations

import queue
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from .config import ROOT, TARGETS, Settings, atomic_json
from .validation import CAPTURE_AT, TRIAL_INTERVAL, TRIAL_SECONDS, ReferenceTrial, Trial
from .domain import AlertTimer, Calibration, Evaluator, Observation, Profiles, Result, overall
from .storage import Recorder
from .alerts import AlertRecovery


@dataclass
class Snapshot:
    frame: object = None
    observation: Observation | None = None
    results: dict[str, Result] | None = None
    message: str = "시작을 눌러 카메라를 연결하세요"
    state: str = "unknown"
    stats: dict | None = None
    analyzing_ms: float = 0
    calibration: float | None = None
    registration: dict | None = None


class Worker(threading.Thread):
    def __init__(self, directory: Path, settings: Settings, demo=False, dev=False, capture_trials=False):
        super().__init__(daemon=True)
        self.directory, self.settings, self.demo, self.dev = directory, settings, demo, dev
        if capture_trials and (demo or not dev):
            raise ValueError("원본 사진 저장은 실제 카메라 테스트 모드에서만 가능합니다")
        self.capture_trials = capture_trials
        self.trial_capture = None
        self.commands = queue.Queue()
        self.snapshots = queue.Queue(maxsize=1)
        self.events = queue.Queue()
        self.running = False
        self.preview = True
        self.scenario = "정상 · 정면"
        self.stop_requested = False
        self.trial = None
        self.validation_reports = []
        self.calibration = None
        self.calibration_pending = {}
        self.calibration_session = False
        self.registration_outcome = {}
        self.registration_request=None
        self.registration_target={}
        self.current_profile=None
        from .screen_tracking import ScreenTracker
        self.screen_tracker=ScreenTracker()
        self.evaluator = Evaluator()
        self.alerts = {"posture": AlertTimer(), "touch": AlertTimer()}
        self.alert_recovery = AlertRecovery()
        self.cap = self.models = None
        self.last_obs = None
        self.last_snapshot = Snapshot()
        self.view_candidate = None
        self.view_started = 0
        self.view_count = 0
        self.view = "unknown"
        self.next_analysis = 0
        self.dimensions = (640, 480)

    def submit(self, action, value=None):
        self.commands.put((action, value))

    def publish(self, snapshot):
        registration=self.registration_info()
        if snapshot.observation is not None:
            registration["current_view"]=snapshot.observation.view
        snapshot = replace(snapshot,registration=registration)
        self.last_snapshot = snapshot
        try:
            self.snapshots.get_nowait()
        except queue.Empty:
            pass
        self.snapshots.put_nowait(snapshot)

    def reset(self):
        self.trial_capture = None
        if self.trial is not None:
            self.events.put(("info", "조건 변경으로 검증 수집을 취소했습니다"))
            self.trial = None
        self.evaluator.reset()
        for kind in self.alert_recovery.reset():
            self.events.put(("alert_clear",kind))
        for timer in self.alerts.values():
            timer.reset()
        self.recorder.reset()
        self.last_obs = None
        self.next_analysis = 0

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.models is not None:
            self.models.close()
            self.models = None
        self.view = "unknown"
        self.view_candidate = None
        self.view_count = 0
        self.calibration = None
        self.calibration_pending.clear()
        self.calibration_session = False
        self.registration_request=None
        self.current_profile=None
        self.screen_tracker.reset()
        self.reset()

    def signature(self):
        w, h = self.dimensions
        return f"camera:{self.settings.camera}:{w}x{h}:features-v3:pose-full-seg:mediapipe-0.10.32"

    def registration_info(self):
        profiles=getattr(self,"profiles",None)
        saved=[profile.view for profile in profiles.items.values()
               if profile.camera_signature==self.signature()] if profiles else []
        entries=[{"id":key,"name":profile.label or profile.view,"view":profile.view,
                  "eye_ready":all(metric in profile.values for metric in ("screen_eye_span","screen_nose_offset"))}
                 for key,profile in profiles.items.items() if profile.camera_signature==self.signature()] if profiles else []
        return {"saved_views":saved,"profiles":entries,"current_view":self.view,
                "screen_candidate":self.screen_tracker.candidate,
                "matched_profile":self.current_profile.profile_id or self.current_profile.view if self.current_profile else None,
                "matched_name":self.current_profile.label or self.current_profile.view if self.current_profile else None,
                "collecting_view":self.calibration.view if self.calibration else None,
                **self.registration_outcome}

    def advance_registration(self,now,view):
        if self.registration_request is None:
            return
        deadline,target=self.registration_request
        if now<deadline:
            return
        if view!="unknown":
            self.registration_request=None
            self.registration_target=target
            self.registration_outcome={"status":"collecting","target_view":view,"target_name":target.get("label","")}
            self.calibration_pending.clear()
            self.calibration_session=True
            self.calibration=Calibration(now,view)
            self.reset()
        elif now>=deadline+8:
            self.registration_request=None
            self.registration_outcome={"status":"error","detail":"바라보는 방향을 확인하지 못했어요. 선택한 화면을 바라보며 얼굴과 어깨가 보이도록 다시 등록해 주세요."}
            self.events.put(("error",self.registration_outcome["detail"]))
            self.events.put(("registration_failed",self.registration_outcome["detail"]))

    def handle_commands(self):
        while True:
            try:
                action, value = self.commands.get_nowait()
            except queue.Empty:
                break
            if action == "stop":
                self.stop_requested = True
                self.running = False
            elif action == "start":
                self.running = True
                self.next_analysis = 0
            elif action == "pause":
                self.running = False
                self.calibration = None
                self.calibration_session = False
                self.reset()
                self.release()
                self.publish(Snapshot(message="관측 꺼짐 · 카메라 해제"))
            elif action == "preview":
                self.preview = bool(value)
            elif action == "settings":
                self.registration_request=None
                self.calibration = None
                self.calibration_pending.clear()
                self.calibration_session = False
                old_camera = self.settings.camera
                try:
                    value.save(self.directory / "settings.json")
                    self.settings = value
                    self.reset()
                    if self.settings.camera != old_camera:
                        self.release()
                except OSError as exc:
                    self.events.put(("error", f"설정 저장 실패: {exc}"))
            elif action == "profile_rename":
                profile=self.profiles.items.get(value.get("profile_id"))
                if profile is not None and profile.label!=value.get("label"):
                    updated=replace(profile,profile_id=value["profile_id"],label=value["label"])
                    try:
                        self.profiles.save(updated)
                    except OSError as exc:
                        self.events.put(("error",f"화면 이름 저장 실패: {exc}"))
            elif action == "monitor_delete":
                identity=value.get("profile_id")
                from .monitor_setup import MonitorLayout
                layout=MonitorLayout(self.directory/"monitor-layout.json",[],seed=False)
                original=list(layout.nodes)
                try:
                    layout.remove(identity)
                    try:
                        self.profiles.delete(identity)
                    except OSError:
                        layout.nodes=original
                        layout.save()
                        raise
                    if (self.registration_request and self.registration_request[1].get("profile_id")==identity) or self.registration_target.get("profile_id")==identity:
                        self.registration_request=None
                        self.calibration=None
                        self.calibration_session=False
                        self.registration_target={}
                        self.registration_outcome={}
                    self.calibration_pending.pop(identity,None)
                    self.current_profile=None
                    self.screen_tracker.reset()
                    self.reset()
                    self.publish(Snapshot(message="화면과 등록한 자세를 삭제했습니다"))
                    self.events.put(("monitor_deleted",identity))
                except OSError as exc:
                    self.events.put(("monitor_delete_failed",f"화면 삭제 실패: {exc}"))
            elif action == "calibrate_prepare":
                if not self.running:
                    self.registration_outcome={"status":"error","detail":"카메라를 켠 뒤 화면 자세를 등록해 주세요."}
                    self.events.put(("error",self.registration_outcome["detail"]))
                    self.events.put(("registration_failed",self.registration_outcome["detail"]))
                else:
                    self.calibration=None
                    self.calibration_session=False
                    self.registration_request=(time.monotonic()+4,dict(value))
                    self.registration_outcome={"status":"preparing","target_name":value.get("label","")}
                    self.reset()
            elif action == "calibrate":
                if not self.running or self.view == "unknown" or self.view_candidate!=self.view:
                    message="등록을 시작하지 못했어요. 카메라를 켜고 등록할 모니터를 바라봐 주세요. 방향이 확인되면 다시 눌러 주세요."
                    self.registration_outcome={"status":"error","detail":message}
                    self.events.put(("error",message))
                    self.events.put(("registration_failed",message))
                else:
                    self.registration_request=None
                    self.registration_target={}
                    self.registration_outcome={"status":"collecting","target_view":self.view}
                    self.calibration_pending.clear()
                    self.calibration_session = True
                    self.calibration = Calibration(time.monotonic(), self.view)
                    self.reset()
            elif action == "calibration_save":
                if self.calibration is not None:
                    self.events.put(("error", "현재 방향 수집이 끝난 뒤 저장하세요."))
                elif self.calibration_pending:
                    try:
                        self.profiles.save_many(list(self.calibration_pending.values()))
                        self.calibration_pending.clear()
                        self.calibration_session = False
                        self.reset()
                        self.events.put(("info", "업무 방향 보정 저장 완료"))
                    except OSError as exc:
                        self.events.put(("error", f"보정 저장 실패: {exc}"))
            elif action == "calibration_cancel":
                self.registration_request=None
                self.calibration = None
                self.calibration_pending.clear()
                self.calibration_session = False
                self.reset()
                self.events.put(("info", "보정 취소 · 기존 기준 유지"))
            elif action == "validate":
                target, expected = value[:2]
                condition = value[2] if len(value) > 2 else ""
                if not self.running or self.view == "unknown" or self.calibration_session:
                    self.events.put(("error", "보정을 저장하고 안정된 방향에서 검증하세요."))
                elif target == "reference" and not any(self.settings.enabled[t.id] for t in TARGETS if t.available and not t.behavior):
                    self.events.put(("error", "검증할 자세 감지 항목을 먼저 켜세요."))
                elif target != "reference" and (not self.settings.enabled.get(target) or expected not in ("good", "bad")):
                    self.events.put(("error", "검증할 감지 항목을 먼저 켜세요."))
                elif self.trial is None:
                    self.reset()
                    if target == "reference":
                        targets = [t.id for t in TARGETS if t.available and self.settings.enabled[t.id]]
                        behaviors = [t.id for t in TARGETS if t.behavior]
                        self.trial = ReferenceTrial(time.monotonic(), self.view, self.settings.version, targets, behaviors)
                    else:
                        self.trial = Trial(target, expected, time.monotonic(), self.view, self.settings.version)
                    self.trial.condition = condition
            elif action == "scenario":
                self.scenario = value
                self.reset()

    def advance_calibration(self,obs):
        self.calibration.add(obs)
        elapsed=obs.timestamp-self.calibration.start
        if elapsed<Calibration.DURATION:
            return min(.95,elapsed/Calibration.DURATION*.95)
        try:
            profile=self.calibration.finish(self.signature())
        except ValueError as exc:
            if elapsed<Calibration.MAX_DURATION:
                self.calibration.samples=[sample for sample in self.calibration.samples if sample.timestamp>=obs.timestamp-Calibration.DURATION]
                self.registration_outcome['waiting']=str(exc)
                return .95
            self.complete_calibration()
        else:
            self.complete_calibration(profile)
        return None

    def complete_calibration(self,profile=None):
        try:
            if profile is None:
                profile = self.calibration.finish(self.signature())
            profile=replace(profile,profile_id=self.registration_target.get("profile_id",""),label=self.registration_target.get("label",""))
            self.profiles.save(profile)
            self.registration_outcome={"status":"saved","target_view":profile.view,"target_name":profile.label}
            self.events.put(("calibration_saved", f"{profile.label or '이 방향'}의 올바른 자세를 저장했습니다. 다른 화면의 기준도 유지됩니다."))
        except (ValueError, OSError) as exc:
            self.registration_outcome={"status":"error","target_view":self.calibration.view,
                                       "target_name":self.registration_target.get("label",""),"detail":str(exc)}
            self.events.put(("error", str(exc)))
            self.events.put(("registration_failed", str(exc)))
        finally:
            self.calibration = None
            self.calibration_session = False
            self.reset()

    def stable_view(self, observed, now, yaw=None):
        if observed!="unknown" and yaw is not None:
            import math
            if math.isfinite(yaw):
                amount=abs(yaw)
                same_side=(self.view.endswith("right") and yaw>=0) or (self.view.endswith("left") and yaw<0)
                if ((self.view=="front" and amount<29)
                        or (self.view.startswith("oblique") and same_side and 21<=amount<60)
                        or (self.view.startswith("side") and same_side and amount>=60)):
                    observed=self.view
        if observed == "unknown":
            self.view_candidate, self.view_count = None, 0
            self.view="unknown"
            self.view = "unknown"
            return "unknown"
        if observed != self.view_candidate:
            self.view_candidate, self.view_started, self.view_count = observed, now, 1
        else:
            self.view_count += 1
        if self.view_count >= 2 and now - self.view_started >= 2:
            self.view = observed
            return observed
        return "unknown" if observed != self.view else self.view

    def demo_frame(self, now):
        import cv2
        import numpy as np
        frame = np.full((480, 640, 3), (39, 30, 20), dtype=np.uint8)
        cv2.circle(frame, (320, 140), 65, (170, 145, 100), 2)
        cv2.line(frame, (320, 210), (320, 405), (170, 145, 100), 3)
        cv2.line(frame, (205, 240), (435, 240), (170, 145, 100), 3)
        cv2.putText(frame, "DEMO - synthetic observations", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, .7, (200, 210, 230), 1)
        scenario = self.scenario
        if "부재" in scenario:
            return frame, Observation(now)
        view = "side_right" if "측면" in scenario else "front"
        metrics = {"roll": 0, "pitch": 0, "shoulder_angle": 0, "head_gap": .7}
        metrics.update(upper_gap=.7,upper_span=3.0,upper_scale=150,upper_eye_scale=75,upper_pitch=0,upper_yaw=0,upper_depth=-.2)
        if view.startswith("side"):
            metrics = {"pitch": 0, "forward": .1, "forward_pixels": 15, "side_scale": 150, "torso_pitch": 0}
        if "숙임" in scenario:
            metrics["pitch"] = 30
        if "기울임" in scenario:
            metrics["roll"] = 22
        if "전방" in scenario:
            metrics["forward_pixels"], metrics["forward"] = 65, 65 / 150
        if "얼굴 만지기" in scenario:
            metrics["touch_distance"] = 0.01
        pose = [(0, 0, 0)] * 33
        pose[11], pose[12] = (205, 240, 1), (435, 240, 1)
        return frame, Observation(now, view, metrics, pose=pose)

    def run(self):
        try:
            self.profiles = Profiles(self.directory / "profiles.json")
            import json
            report_path = self.directory / "validation.json"
            if report_path.exists():
                try:
                    existing = json.loads(report_path.read_text(encoding="utf-8"))
                    if isinstance(existing, dict) and isinstance(existing.get("trials"), list):
                        self.validation_reports = existing["trials"]
                except (OSError, ValueError):
                    raise RuntimeError("기존 검증 보고서를 읽을 수 없습니다. 파일을 확인하세요.")
            self.recorder = Recorder(self.directory / "records.sqlite3")
        except Exception as exc:
            self.publish(Snapshot(message=f"로컬 기록 초기화 실패: {exc}"))
            self.events.put(("error", f"로컬 기록 초기화 실패: {exc}"))
            return
        try:
            import cv2
            from .vision import LocalModels, angles
            while not self.stop_requested:
                self.handle_commands()
                if self.stop_requested:
                    break
                if not self.running:
                    time.sleep(.03)
                    continue
                if not self.preview and not any(self.settings.enabled.values()):
                    self.release()
                    self.publish(Snapshot(message="모든 감지가 꺼져 있습니다 · 카메라 해제", state="disabled"))
                    time.sleep(.1)
                    continue
                now = time.monotonic()
                if not self.preview and now < self.next_analysis:
                    time.sleep(.03)
                    continue
                try:
                    if self.demo:
                        frame, demo_obs = self.demo_frame(now)
                    else:
                        if self.cap is None:
                            self.cap = cv2.VideoCapture(self.settings.camera, cv2.CAP_DSHOW)
                            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                            if not self.cap.isOpened():
                                raise RuntimeError("웹캠 접근 실패 · 카메라 번호/권한/다른 앱의 점유를 확인하세요.")
                        ok, frame = self.cap.read()
                        if not ok:
                            raise RuntimeError("웹캠 프레임 수집 실패 · 다시 시작을 눌러 연결하세요.")
                    self.dimensions = (frame.shape[1], frame.shape[0])
                    needs_analysis = any(self.settings.enabled.values()) or self.calibration is not None or self.registration_request is not None
                    if not needs_analysis and self.models is not None:
                        self.models.close()
                        self.models = None
                    if now >= self.next_analysis and needs_analysis:
                        began = time.monotonic()
                        analysis_settings = replace(self.settings, performance="High") if self.trial is not None or self.calibration is not None or self.registration_request is not None else self.settings
                        settings_version = self.settings.version
                        if self.demo:
                            obs = demo_obs
                        else:
                            if self.models is None:
                                self.models = LocalModels(ROOT / "models")
                            self.models.max_gap = analysis_settings.interval * 2
                            self.models.ensure(hands=self.settings.enabled["face_touch"] and self.calibration is None)
                            obs = self.models.detect(frame, now)
                            frame = self.models.corrected_frame
                        # Treat results older than the freshness bound as invalid.
                        elapsed = time.monotonic() - began
                        if elapsed > max(2, analysis_settings.interval * 2):
                            obs = Observation(now, reasons={"subject": "분석 지연으로 오래된 결과를 폐기했습니다"})
                        self.handle_commands()
                        if not self.running or self.stop_requested:
                            continue
                        if settings_version != self.settings.version:
                            continue
                        obs.view = self.stable_view(obs.view, now,obs.metrics.get("view_yaw"))
                        self.advance_registration(now,obs.view)
                        baseline = self.screen_tracker.update(self.profiles,obs,self.signature())
                        self.current_profile=baseline
                        if baseline is not None and not self.demo and self.calibration is None and self.registration_request is None:
                            # Direction selection precedes posture geometry. Use
                            # the chosen reference's feature family even when a
                            # raw angle crosses an arbitrary front/side boundary.
                            from .vision import extract
                            original_quality=obs.quality
                            obs=extract(now,obs.pose,obs.face,obs.hands,obs.rotation,obs.world,frame.shape,view_override=baseline.view)
                            obs.quality.update(original_quality)
                        if baseline is not None and not self.demo and self.calibration is None:
                            if baseline.rotation is not None and obs.rotation is not None:
                                import numpy as np
                                relative = np.asarray(baseline.rotation).T @ np.asarray(obs.rotation)
                                pitch, _, roll = angles(relative)
                                obs.metrics["pitch"] = pitch
                                if "roll" in obs.metrics:
                                    obs.metrics["roll"] = roll
                                obs.metrics["relative_rotation"] = 1
                        progress = None
                        if self.calibration is not None:
                            progress = self.advance_calibration(obs)
                            results = {t.id: Result("calibrating") for t in TARGETS}
                            state = "unknown"
                        elif self.calibration_session or self.registration_request is not None:
                            results = {t.id: Result("calibrating") for t in TARGETS}
                            state = "unknown"
                        else:
                            if baseline is None and self.screen_tracker.current is not None and self.screen_tracker.candidate is not None:
                                results=self.evaluator.suspend_screen_transition(obs,analysis_settings)
                            else:
                                results = self.evaluator.evaluate(obs, baseline, analysis_settings,
                                                                  fast_recovery=self.alert_recovery.fast(now))
                            state = overall(results, self.settings)
                        validating = self.trial is not None
                        if self.trial is not None:
                            try:
                                self.trial.observe(now, obs.view, self.settings.version, results)
                                if self.capture_trials and self.trial_capture is None and now - self.trial.start >= CAPTURE_AT:
                                    self.trial_capture = (frame.copy(), {
                                        "captured_at": datetime.now().astimezone().isoformat(),
                                        "seconds_from_trial_start": now - self.trial.start,
                                        "analysis_ms": elapsed * 1000,
                                        "camera_signature": self.signature(),
                                        "observation": asdict(obs),
                                        "baseline": asdict(baseline) if baseline else None,
                                        "results": {k: asdict(v) for k, v in results.items()},
                                        "settings": asdict(self.settings),
                                        "validation_analysis_interval": analysis_settings.interval,
                                    })
                                if now - self.trial.start >= TRIAL_SECONDS:
                                    report = self.trial.report()
                                    if self.capture_trials:
                                        if self.trial_capture is None:
                                            raise ValueError("테스트 사진을 확보하지 못했습니다")
                                        from .validation_capture import save_capture
                                        photo, measurement = self.trial_capture
                                        report["capture"] = save_capture(self.directory, photo, measurement, report)
                                    updated = self.validation_reports + [report]
                                    atomic_json(self.directory / "validation.json", {"schema": 1, "trials": updated})
                                    self.validation_reports = updated
                                    self.trial = None
                                    self.trial_capture = None
                                    self.events.put(("info", "검증 완료 · 표본 일치율/판정 가능 비율을 로컬 validation.json에 저장했습니다"))
                            except (ValueError, OSError) as exc:
                                self.trial = None
                                self.trial_capture = None
                                self.events.put(("error", str(exc)))
                        wall = datetime.now().astimezone()
                        touch = results["face_touch"].status == "bad"
                        self.recorder.update(now, wall, state, obs.view, self.settings.version,
                                             self.settings.interval * 2, touch, allow_write=not self.demo and not validating,
                                             results=results)
                        if not self.calibration_session and self.registration_request is None and not validating:
                            ready_bad = state == "bad" and not any(r.status == "recovering" for r in results.values())
                            screen_pending=baseline is None and self.screen_tracker.current is not None and self.screen_tracker.candidate is not None
                            if screen_pending:
                                self.alerts['posture'].suspend(now)
                            if not screen_pending and self.alerts["posture"].update(ready_bad, now, self.settings):
                                reasons = [t.label for t in TARGETS if not t.behavior and results[t.id].status == "bad"]
                                self.alert_recovery.trigger("posture",now)
                                self.events.put(("alert", {"id":"posture","message":"자세를 편안하게 바로잡아 주세요","detail":" · ".join(reasons)}))
                            if self.alerts["touch"].update(touch, now, self.settings):
                                self.alert_recovery.trigger("touch",now)
                                self.events.put(("alert", {"id":"touch","message":"손을 얼굴에서 잠시 내려 주세요","detail":"얼굴 가까이에 손이 오래 머물고 있어요"}))
                            for kind in self.alert_recovery.update(now,state,results):
                                self.events.put(("alert_clear",kind))
                        if validating:
                            self.recorder.reset()
                            for timer in self.alerts.values():
                                timer.reset()
                        stats = self.recorder.summary(wall)
                        message = ("올바른 자세 등록 중 · 어깨를 편하게 펴고 화면을 바라봐 주세요" if self.calibration else
                                   "바라보는 화면 확인 중 · 자세 측정을 잠시 멈춥니다" if self.screen_tracker.candidate is not None else
                                   "내 자세 설정이 필요합니다 · ‘올바른 자세 등록’을 눌러 주세요" if baseline is None else
                                   "자세를 확인하고 있어요 · 등록한 내 자세와 비교합니다")
                        if self.calibration_session:
                            message = (f"올바른 자세 등록 중 · 그대로 앉아 주세요 · {max(0, Calibration.DURATION - (now - self.calibration.start)):.0f}초 남음" if self.calibration else
                                       "내 자세를 저장하고 있어요")
                            if self.calibration and self.registration_outcome.get('waiting'):
                                message="안정된 자세를 조금 더 확인하고 있어요 · 같은 화면을 바라봐 주세요"
                        if self.registration_request is not None:
                            message=f"{self.registration_outcome.get('target_name','선택한 화면')}을 바라봐 주세요 · {max(0,self.registration_request[0]-now):.0f}초 뒤 등록 시작"
                        if obs.view == "unknown":
                            message = obs.reasons.get("subject", "바라보는 방향 확인 중 · 얼굴과 어깨가 보이도록 앉아 주세요")
                        if self.trial is not None:
                            message = f"감지 테스트 중 · 선택한 자세를 유지해 주세요 · {max(0, TRIAL_SECONDS - (now - self.trial.start)):.0f}초 남음"
                        self.last_obs = obs
                        self.publish(Snapshot(frame, obs, results, message, state, stats, elapsed * 1000, progress))
                        self.next_analysis = now + (.3 if self.calibration_session or self.registration_request is not None or self.screen_tracker.candidate is not None else TRIAL_INTERVAL if self.trial is not None else self.alert_recovery.interval(now,self.settings.interval))
                    elif self.preview:
                        latest = self.last_snapshot
                        if self.last_obs is not None:
                            # Keep image and landmarks from the SAME inference frame.
                            # New live frames with old landmarks look like tracking errors.
                            self.publish(Snapshot(latest.frame, latest.observation, latest.results, latest.message,
                                                  latest.state, latest.stats, latest.analyzing_ms, latest.calibration))
                        else:
                            self.publish(Snapshot(frame, message="분석 대기 · 감지가 켜져 있으면 다음 분석 프레임을 표시합니다"))
                    time.sleep(.05)
                except Exception as exc:
                    self.running = False
                    self.release()
                    self.publish(Snapshot(message=f"오류: {exc}"))
                    self.events.put(("error", str(exc)))
        except Exception as exc:
            self.events.put(("error", f"실행 환경 오류: {exc}"))
        finally:
            self.release()
            self.recorder.close()
