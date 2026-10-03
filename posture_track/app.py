from __future__ import annotations

import argparse
import copy
import queue
import threading
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT, TARGETS, Settings, ALERT_DELAYS
from .privacy import enforce_local_only
from .runtime import default_data_dir, acquire_instance

BG, PANEL, LINE = "#18191e", "#25272e", "#33363f"
TEXT, MUTED, GREEN, GOLD, RED = "#edf0f4", "#a0a6b1", "#a8c8e4", "#d0b28d", "#e59c9e"
VIEWS = {"front": "정면", "side_left": "좌측면", "side_right": "우측면",
         "oblique_left": "좌사선", "oblique_right": "우사선", "unknown": "확인 중"}
STATUSES = {"good": "기준 범위", "bad": "지속 이탈", "candidate": "이탈 확인 중",
            "recovering": "복귀 확인 중", "unknown": "판정 불가", "off": "꺼짐",
            "unsupported": "이 방향에서 측정 어려움", "uncalibrated": "내 자세 설정 필요",
            "research": "준비 중", "calibrating": "올바른 자세 등록 중", "disabled": "자세 감지 꺼짐"}


class App:
    def __init__(self, args):
        import tkinter as tk
        from tkinter import ttk
        from .worker import Worker
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PostureTrack.Local")
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
        self.tk, self.ttk, self.args = tk, ttk, args
        self.root = tk.Tk()
        if args.background:
            self.root.withdraw()
        self.root.title("Posture Track")
        from PIL import Image, ImageTk
        self.app_icon = ImageTk.PhotoImage(Image.open(ROOT / "assets" / "posture-track.png"))
        self.root.iconphoto(True, self.app_icon)
        self.root.iconbitmap(str(ROOT / "assets" / "posture-track.ico"))
        width = min(1220, self.root.winfo_screenwidth() - 80)
        height = min(930, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{width}x{height}+30+30")
        self.root.minsize(980, 740)
        self.root.configure(bg=BG)
        self.directory = Path(args.data_dir).resolve() if args.data_dir else default_data_dir(args.demo)
        self.settings = Settings.load(self.directory / "settings.json")
        from .cameras import connected_cameras
        try:
            self.cameras = connected_cameras()
        except OSError:
            self.cameras = []
        if self.cameras and self.settings.camera not in {device.index for device in self.cameras}:
            self.settings.camera = self.cameras[0].index
        self.worker = Worker(self.directory, copy.deepcopy(self.settings), args.demo, not args.release_alerts, args.validation_capture)
        self.photo = None
        self.tray = None
        self.ui_actions = queue.Queue()
        self.shutting = False
        self.chart_period = "week"
        self.detail_window = None
        self.notification_window = None
        self.notification_windows=[]
        self.monitor_setup=None
        self.latest_registration={}
        self.notifications = {}
        self.notification_sequence = 0
        from .reminders import ReminderBook
        self.reminder_book = ReminderBook(self.directory / "reminders.json")
        self.build_style()
        self.build_ui()
        from .onboarding import FirstUseGuide
        self.guide = FirstUseGuide(self)
        from .ui_widgets import style_titlebar
        self.titlebar_status = style_titlebar(self.root)
        # Paint the first guide before camera/model initialization can occupy
        # the interpreter during its cold imports.
        self.root.after(150,self.start_worker)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.after(80, self.poll)
        if self.cameras or args.demo:
            self.worker.submit("start")
        if args.background:
            self.root.after(0, self.hide)
        if args.ui_smoke:
            self.root.after(2500, self.check_ui_smoke)

    def build_style(self):
        s = self.ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("Card.TLabel", background=PANEL, foreground=TEXT)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        s.configure("TButton", background=LINE, foreground=TEXT, padding=(12, 8), borderwidth=0, font=("Segoe UI", 10))
        s.map("TButton", background=[("active", "#393d46")])
        s.configure("TNotebook", background=BG, borderwidth=0, padding=0,
                    bordercolor=BG, lightcolor=BG, darkcolor=BG)
        s.layout("TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        s.layout("TNotebook.Tab", [])
        s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(26, 12), font=("Segoe UI", 11, "bold"))
        s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
        s.configure("TCheckbutton", background=PANEL, foreground=TEXT, font=("Segoe UI", 11),
                    indicatorsize=16, indicatormargin=(0, 3, 8, 3))
        s.map("TCheckbutton", background=[("active", PANEL)], foreground=[("disabled", MUTED)])
        s.configure("TCombobox", fieldbackground=PANEL, background=LINE, foreground=TEXT, padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", TEXT)])
        s.configure("Vertical.TScrollbar", background=LINE, troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTED)

    def start_worker(self):
        if not self.shutting:
            self.worker.start()

    def build_ui(self):
        tk, ttk = self.tk, self.ttk
        from .ui_widgets import RoundedButton, RoundedCard, RoundedProgress, RoundedScrollbar, SoundSwitch, Switch
        shell = ttk.Frame(self.root, padding=(28, 18))
        shell.pack(fill="both", expand=True)
        top = ttk.Frame(shell)
        top.pack(fill="x", pady=(0, 18))
        from PIL import Image, ImageTk
        self.brand_icon = ImageTk.PhotoImage(Image.open(ROOT / "assets" / "posture-track.png").resize((34,34),Image.Resampling.LANCZOS))
        ttk.Label(top,image=self.brand_icon).pack(side="left",padx=(0,12))
        ttk.Label(top,text="Posture Track",foreground=TEXT,font=("Segoe UI Semibold",24)).pack(side="left")
        nav = ttk.Frame(shell)
        nav.pack(fill="x", pady=(0, 16))
        self.nav_buttons = []
        self.nav_images = []
        from PIL import Image, ImageDraw, ImageTk
        from .dashboard import font
        for title in ("자세 기록", "설정 · 카메라", "맞춤 알림"):
            variants = []
            for selected in (False, True):
                image = Image.new("RGB", (400, 96), BG)
                draw = ImageDraw.Draw(image)
                if selected:
                    draw.rounded_rectangle((2, 2, 398, 94), radius=46, fill="#2b333d")
                draw.text((200, 48), title, font=font(14),
                          fill=TEXT if selected else MUTED, anchor="mm")
                variants.append(ImageTk.PhotoImage(image.resize((200, 48), Image.Resampling.LANCZOS)))
            self.nav_images.append(variants)
            button = tk.Button(nav, image=variants[0], bg=BG, activebackground=BG,
                               bd=0, relief="flat", highlightthickness=0, cursor="hand2",
                               padx=0, pady=0, takefocus=True)
            button.pack(side="left", padx=(0, 8))
            self.nav_buttons.append(button)
            button.bind("<FocusIn>", lambda event: event.widget.configure(highlightthickness=1, highlightbackground="#657888"))
            button.bind("<FocusOut>", lambda event: event.widget.configure(highlightthickness=0))
        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill="both", expand=True)
        self.dashboard_page = ttk.Frame(self.notebook)
        self.settings_page = ttk.Frame(self.notebook)
        self.reminders_page = ttk.Frame(self.notebook)
        self.notebook.add(self.dashboard_page, text="자세 기록")
        self.notebook.add(self.settings_page, text="설정 · 카메라")
        self.notebook.add(self.reminders_page, text="맞춤 알림")
        self.nav_buttons[0].configure(command=lambda: self.notebook.select(self.dashboard_page))
        self.nav_buttons[1].configure(command=lambda: self.notebook.select(self.settings_page))
        self.nav_buttons[2].configure(command=lambda: self.notebook.select(self.reminders_page))
        self.notebook.bind("<<NotebookTabChanged>>", self.update_navigation)
        self.latest_stats = {}
        self.graph = tk.Canvas(self.dashboard_page, bg=BG, highlightthickness=0)
        self.graph.pack(fill="both", expand=True)
        self.graph.bind("<Configure>", lambda _: self.draw_graph(self.latest_stats))
        self.graph.bind("<Button-1>", self.click_graph)
        self.graph.bind("<Motion>", self.hover_graph)
        self.graph.bind("<Leave>", lambda _:self.set_graph_hover(None))
        self.score = tk.StringVar()
        self.behavior_summary = tk.StringVar()
        outer = ttk.Frame(self.settings_page, padding=(0, 16))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="카메라와 자세 설정", font=("Segoe UI", 23)).pack(side="left")
        RoundedButton(header,text="사용 안내",command=self.show_guide,min_width=86).pack(side="right")
        tag = "DEMO · 합성 관측 · 점수 저장 안 함" if self.args.demo else ""
        if self.args.validation_capture:
            tag = "TEST CAPTURE · 시험당 원본 사진 1장 로컬 저장"
        if tag:
            ttk.Label(header, text=tag, foreground=GREEN).pack(side="right")
        ttk.Label(outer, text="‘올바른 자세 등록’에서 내 화면들을 배치하고, 각 화면을 선택해 바라보는 자세를 등록하세요. 자주 사용하는 화면만 등록하면 됩니다.", style="Muted.TLabel", wraplength=900).grid(row=1, column=0, sticky="w", pady=(4, 17))
        toolbar = ttk.Frame(outer)
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self.observation_enabled = tk.BooleanVar(value=bool(self.cameras) or self.args.demo)
        self.observation_switch = Switch(toolbar, text="카메라 켜짐" if self.observation_enabled.get() else "카메라 꺼짐", variable=self.observation_enabled,
                                         command=self.toggle_observation,background=BG,width=170)
        self.observation_switch.configure(bg=BG, activebackground=BG)
        self.observation_switch.pack(side="left", padx=(0, 12))
        self.calibrate_button = RoundedButton(toolbar, text="올바른 자세 등록", command=self.open_monitor_setup, primary=True)
        self.calibrate_button.pack(side="left")
        self.message = tk.StringVar(value="어깨를 편하게 펴고 화면을 바라보며 ‘올바른 자세 등록’을 눌러 주세요.")
        messages=ttk.Frame(outer)
        messages.grid(row=3,column=0,sticky="ew",pady=(0,12))
        live_message=ttk.Label(messages,textvariable=self.message,wraplength=900,foreground=GOLD)
        live_message.pack(fill="x")
        self.registration_var=tk.StringVar(value="등록된 방향을 확인하고 있어요")
        self.registration_label=ttk.Label(messages,textvariable=self.registration_var,wraplength=900,style="Muted.TLabel",justify="left")
        self.registration_label.pack(fill="x",pady=(4,0))
        messages.bind("<Configure>",lambda event:[label.configure(wraplength=max(80,event.width-2)) for label in (live_message,self.registration_label)])
        body = ttk.Frame(outer)
        body.grid(row=4, column=0, sticky="nsew")
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 18))
        feedback_card = RoundedCard(left,padding=14,radius=18)
        feedback_card.pack(fill="x", pady=(0, 8))
        feedback = feedback_card.content
        self.feedback_title = tk.Label(feedback, text="카메라 연결 중", bg=PANEL, fg=MUTED,
                                       font=("Segoe UI", 12, "bold"), anchor="w")
        self.feedback_title.pack(fill="x")
        self.feedback_detail = tk.Label(feedback, text="얼굴과 어깨가 보이도록 앉아 주세요", bg=PANEL,
                                        fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=550)
        self.feedback_detail.pack(fill="x", pady=(3, 0))
        feedback.bind("<Configure>", lambda event: self.feedback_detail.configure(wraplength=max(80,event.width-2)),add=True)
        preview_card = RoundedCard(left,fill="#0b131d",padding=14,radius=18,auto_height=False)
        preview_card.configure(height=330)
        preview_card.pack(fill="both",expand=True)
        self.canvas = tk.Canvas(preview_card.content, bg="#0b131d", highlightthickness=0, width=600, height=302)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(350, 210, text="카메라 연결 중\n얼굴과 어깨가 보이도록 앉아 주세요", fill=MUTED, font=("Segoe UI", 16), justify="center")
        meta = ttk.Frame(left)
        meta.pack(fill="x", pady=10)
        self.view_var = tk.StringVar(value="바라보는 방향: 확인 중")
        self.state_var = tk.StringVar(value="판정 불가")
        self.latency_var = tk.StringVar(value="분석 결과 없음")
        ttk.Label(meta, textvariable=self.view_var).pack(side="left")
        ttk.Label(meta, textvariable=self.latency_var, style="Muted.TLabel").pack(side="right")
        self.progress = RoundedProgress(left)
        self.progress.pack(fill="x")
        ttk.Label(left, text="한 명이면 바로 측정합니다. 여러 명이면 기존 사용자를 따라가고, 겹치거나 다른 사람이 앞에 오면 잠시 멈춥니다.\n자세 변화는 위 상태 카드에 표시됩니다. 얼굴 만지기는 자세 점수와 별도로 기록합니다.", style="Muted.TLabel", wraplength=580).pack(anchor="w", pady=9)

        right_host = ttk.Frame(body, width=350)
        right_host.pack(side="right", fill="y")
        right_canvas = tk.Canvas(right_host, bg=BG, width=330, highlightthickness=0)
        self.settings_canvas = right_canvas
        right_scroll = self.settings_scrollbar = RoundedScrollbar(right_host,command=right_canvas.yview)
        right_scroll.pack(side="right", fill="y",padx=(6,0))
        right_canvas.pack(side="left", fill="both", expand=True)
        right_canvas.configure(yscrollcommand=right_scroll.set)
        right_card = RoundedCard(right_canvas,padding=20,radius=18)
        right = right_card.content
        right_window = right_canvas.create_window((0, 0), window=right_card, anchor="nw")
        right_card.bind("<Configure>", lambda _: right_canvas.configure(scrollregion=right_canvas.bbox("all")),add=True)
        right_canvas.bind("<Configure>", lambda event: right_canvas.itemconfigure(right_window, width=event.width))
        def scroll_panel(event):
            right_canvas.yview_scroll(-int(event.delta / 120), "units")
        self.root.bind("<MouseWheel>", lambda event: scroll_panel(event) if self.notebook.select()==str(self.settings_page) and event.x_root >= right_host.winfo_rootx() else None)
        ttk.Label(right, text="확인할 자세와 습관", style="Card.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 12))
        self.enabled, self.status_labels = {}, {}
        for target in TARGETS:
            var = tk.BooleanVar(value=self.settings.enabled[target.id])
            self.enabled[target.id] = var
            checkbox = Switch(right, text=target.label, variable=var, command=self.update_settings)
            checkbox.pack(fill="x")
            if not target.available:
                checkbox.state(["disabled"])
            label = ttk.Label(right, text="연구 중" if not target.available else "관측 대기", style="Card.TLabel", foreground=MUTED, wraplength=320, font=("Segoe UI", 8))
            label.pack(fill="x",anchor="w", padx=22, pady=(0, 4))
            label.configure(justify="left",anchor="w")
            label.bind("<Configure>",lambda event:event.widget.configure(wraplength=max(80,event.width-2)))
            self.status_labels[target.id] = label
        ttk.Label(right, text="자세 감지 민감도", style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 5))
        self.posture_sensitivity = tk.StringVar(value=self.settings.posture_sensitivity)
        self.sensitivity_combo = self.combo(right, self.posture_sensitivity, ["standard", "sensitive"],
                                           labels={"standard": "기본", "sensitive": "민감"})
        ttk.Label(right, text="민감은 더 작은 자세 변화도 확인합니다.", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(3, 0))
        ttk.Label(right, text="얼마나 자주 확인할까요?", style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 5))
        self.performance = tk.StringVar(value=self.settings.performance)
        self.combo(right, self.performance, ["Low", "Mid", "High"], labels={
            "Low": "5초마다 · 배터리 절약", "Mid": "2초마다 · 기본", "High": "0.5초마다 · 빠르게"})
        ttk.Label(right, text="같은 자세가 지속되면 알림", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(7, 0))
        self.alert = tk.StringVar(value=next(label for label,seconds in ALERT_DELAYS.items() if seconds==self.settings.alert_seconds))
        self.alert_combo=self.combo(right, self.alert, list(ALERT_DELAYS))
        ttk.Label(right, text="감지가 맞는지 테스트", style="Card.TLabel", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 3))
        ttk.Label(right, text="아래 자세를 고르고 10초간 유지해 주세요.", style="Card.TLabel", foreground=MUTED, wraplength=280).pack(anchor="w")
        available = [t for t in TARGETS if t.available]
        validation_choices = {"평소 자세 · 전체 항목 확인": ("reference", "good")}
        short_names = {"forward_head": "머리 전방 이동", "slouch": "상체 구부정 · 어깨 말림",
                       "head_bend": "고개 숙임·젖힘", "lean": "한쪽 기울임",
                       "uneven_shoulders": "어깨 비대칭", "face_touch": "얼굴 만지기"}
        for target in available:
            if target.behavior:
                continue
            bad = "얼굴 근접" if target.behavior else "이 자세로 테스트"
            validation_choices[f"{short_names[target.id]} — {bad}"] = (target.id, "bad")
        validation_choices["얼굴 만지기 — 근접 유지"] = ("face_touch", "bad", "consecutive_proximity")
        self.validation_case = tk.StringVar(value="평소 자세 · 전체 항목 확인")
        self.validation_combo = self.combo(right, self.validation_case, list(validation_choices), bind=False)
        def validate():
            self.worker.submit("validate", validation_choices[self.validation_case.get()])
        RoundedButton(right, text="10초 테스트 시작", command=validate, background=PANEL).pack(anchor="w", pady=5)
        self.camera = tk.StringVar(value=str(self.settings.camera) if self.cameras else "")
        ttk.Label(right, text="사용할 카메라", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(8, 0))
        self.camera_combo = self.combo(right, self.camera, [str(device.index) for device in self.cameras],
                                       labels={**{str(device.index): device.name for device in self.cameras},
                                               "": "연결된 카메라 없음"})
        RoundedButton(right,text="카메라 새로고침",command=self.refresh_cameras,background=PANEL).pack(anchor="w",pady=(3,4))
        self.muted = tk.BooleanVar(value=self.settings.muted)
        self.sound_switch = SoundSwitch(right,muted=self.muted,command=self.update_settings)
        self.sound_switch.pack(fill="x",pady=8)
        if self.args.demo:
            self.scenario = tk.StringVar(value="정상 · 정면")
            combo = self.combo(right, self.scenario, ["정상 · 정면", "고개 숙임 · 정면", "한쪽 기울임 · 정면", "정상 · 측면", "머리 전방 · 측면", "얼굴 만지기 · 정면", "부재 / 가림"], bind=False)
            combo.bind("<<ComboboxSelected>>", lambda _: self.worker.submit("scenario", self.scenario.get()))

        ttk.Label(left, textvariable=self.behavior_summary, style="Muted.TLabel", wraplength=580).pack(anchor="w")
        from .reminders_ui import ReminderPage
        self.reminder_ui = ReminderPage(self,self.reminders_page,self.reminder_book)
        self.notebook.select(self.dashboard_page)
        self.draw_graph({})

    def combo(self, parent, var, values, bind=True, labels=None):
        from .ui_widgets import ThemedDropdown
        combo = ThemedDropdown(parent, var, values, labels)
        combo.pack(fill="x", pady=3)
        if bind:
            combo.bind("<<ComboboxSelected>>", self.update_settings)
        return combo

    def show_guide(self):
        from .onboarding import FirstUseGuide
        self.guide.destroy()
        self.notebook.select(self.dashboard_page)
        self.guide=FirstUseGuide(self,force=True)

    def get_display_bounds(self):
        from .displays import display_bounds
        try:
            return display_bounds() or [(0,0,self.root.winfo_screenwidth(),self.root.winfo_screenheight())]
        except (OSError,AttributeError):
            return [(0,0,self.root.winfo_screenwidth(),self.root.winfo_screenheight())]

    def open_monitor_setup(self):
        from .monitor_setup import MonitorSetup
        if self.monitor_setup and self.monitor_setup.window.winfo_exists():
            self.monitor_setup.window.lift()
            return
        profiles=self.latest_registration.get("profiles",[])
        if not profiles:
            from .domain import Profiles
            profiles=[{"id":key,"name":profile.label or profile.view,"view":profile.view}
                      for key,profile in Profiles(self.directory/"profiles.json").items.items()]
        self.monitor_setup=MonitorSetup(self,self.get_display_bounds(),profiles)

    def toggle_observation(self):
        enabled = self.observation_enabled.get()
        if enabled and not self.cameras and not self.args.demo:
            self.refresh_cameras()
            if not self.cameras:
                enabled = False
                self.observation_enabled.set(False)
                self.message.set("연결된 카메라가 없습니다. 카메라 연결 후 목록을 새로고침해 주세요.")
        self.observation_switch.label = "카메라 켜짐" if enabled else "카메라 꺼짐"
        self.observation_switch.draw()
        self.worker.submit("start" if enabled else "pause")

    def update_settings(self, event=None):
        new = copy.deepcopy(self.settings)
        new.enabled = {k: v.get() for k, v in self.enabled.items()}
        new.performance = self.performance.get()
        new.posture_sensitivity = self.posture_sensitivity.get()
        new.camera = int(self.camera.get()) if self.camera.get() else self.settings.camera
        new.muted = self.muted.get()
        new.alert_seconds = ALERT_DELAYS[self.alert.get()]
        new.version += 1
        self.settings = new
        self.worker.submit("settings", copy.deepcopy(new))

    def refresh_cameras(self):
        from .cameras import connected_cameras
        try:
            devices = connected_cameras()
        except OSError as exc:
            self.message.set(str(exc))
            return
        previous = self.camera.get()
        self.cameras = devices
        values = [str(device.index) for device in devices]
        self.camera_combo.close()
        self.camera_combo.values = tuple(values)
        self.camera_combo.labels = {**{str(device.index): device.name for device in devices},
                                    "": "연결된 카메라 없음"}
        self.camera.set(previous if previous in values else values[0] if values else "")
        self.camera_combo.draw()
        if not devices and not self.args.demo:
            self.observation_enabled.set(False)
            self.toggle_observation()
            self.message.set("연결된 카메라가 없습니다. 연결 후 목록을 새로고침해 주세요.")
        elif self.camera.get() != previous:
            self.update_settings()

    def render(self, snapshot):
        import cv2
        from PIL import Image, ImageTk
        obs = snapshot.observation
        self.message.set(snapshot.message)
        self.state_var.set(STATUSES.get(snapshot.state, snapshot.state))
        from .feedback import posture_feedback
        title, detail, color = posture_feedback(snapshot.results or {}, obs, snapshot.calibration is not None)
        registration=snapshot.registration or {}
        self.latest_registration=registration
        saved=registration.get("saved_views",[])
        current=registration.get("current_view","unknown")
        current_name=VIEWS.get(current,current)
        profiles=registration.get("profiles",[])
        names=" · ".join(VIEWS.get(profile['name'],profile['name']) for profile in profiles) or "없음"
        matched=registration.get("matched_profile")
        match_name=registration.get("matched_name")
        status=VIEWS.get(match_name,match_name) if matched else "바라보는 화면 확인 중" if profiles else "등록한 화면 없음"
        summary=f"현재 자세 기준: {status}  |  등록한 화면: {names}"
        if registration.get("status")=="preparing":
            summary+=f"\n{registration.get('target_name','선택한 화면')}을 바라봐 주세요 · 준비 후 8~10초간 자세를 등록합니다"
        if registration.get("collecting_view"):
            summary+=f"\n{registration.get('target_name') or VIEWS.get(registration['collecting_view'],registration['collecting_view'])} 등록 중 · 다른 화면의 기준은 유지됩니다"
            if registration.get('waiting'):
                summary+=" · 안정된 표본 추가 확인 중"
        elif registration.get("status")=="error":
            summary+="\n등록 실패: "+registration.get("detail","")
            if any(result.status=="uncalibrated" for result in (snapshot.results or {}).values()):
                title,detail,color="자세 등록이 완료되지 않았어요",registration.get("detail","다시 등록해 주세요"),RED
        elif registration.get("status")=="saved":
            summary+=f"\n마지막 등록 완료: {registration.get('target_name') or VIEWS.get(registration.get('target_view'),registration.get('target_view'))}"
        if current!="unknown" and not matched and not profiles and registration.get("status") not in ("error","preparing") and snapshot.calibration is None:
            title="지금 보는 화면의 자세를 등록해 주세요"
            detail="‘올바른 자세 등록’에서 화면을 선택하세요. 4초의 준비 시간 후 그 화면을 바라보며 8~10초간 유지하면 저장됩니다."
        elif registration.get("screen_candidate") and snapshot.calibration is None:
            title="바라보는 화면을 확인하고 있어요"
            detail="화면 전환이 안정되면 그 화면에 등록한 자세를 기준으로 측정합니다."
            color=GOLD
        elif matched and snapshot.calibration is None:
            incomplete=[result.reason for result in (snapshot.results or {}).values() if result.status=="uncalibrated"]
            if incomplete:
                title,detail,color="방향 등록 완료 · 일부 자세 기준이 부족해요"," · ".join(dict.fromkeys(incomplete)),GOLD
        if registration.get("status")=="preparing":
            title="선택한 화면을 바라봐 주세요"
            detail=f"{registration.get('target_name','선택한 화면')} · 준비 시간이 끝나면 자동으로 등록을 시작합니다. 어깨를 편하게 펴고 잠시 유지하세요."
            color=GREEN
        elif registration.get('status')=='error':
            title=f"{registration.get('target_name') or '선택한 화면'}의 자세 등록을 완료하지 못했어요"
            detail=registration.get('detail','같은 화면을 바라보며 다시 등록해 주세요')
            color=RED
        elif registration.get('waiting') and registration.get('collecting_view'):
            title="안정된 자세를 조금 더 확인하고 있어요"
            detail="같은 화면을 바라보며 유지해 주세요. 표본이 모이면 자동으로 저장합니다."
            color=GOLD
        self.registration_var.set(summary)
        self.feedback_title.configure(text=title, fg=color)
        self.feedback_detail.configure(text=detail)
        self.progress.set(snapshot.calibration)
        self.guide.progress(snapshot.calibration is not None or (snapshot.registration or {}).get("status")=="preparing")
        if obs:
            self.view_var.set("바라보는 방향: " + VIEWS.get(obs.view, obs.view))
            import time
            age = max(0, time.monotonic() - obs.timestamp)
            self.latency_var.set(f"분석 {snapshot.analyzing_ms:.0f}ms · 결과 {age:.1f}초 전")
        else:
            self.view_var.set("바라보는 방향: 확인 중")
            self.latency_var.set("유효 분석 결과 없음")
        for target in TARGETS:
            result = (snapshot.results or {}).get(target.id)
            label = self.status_labels[target.id]
            if not result:
                label.configure(text="연구 중" if not target.available else "관측 대기", foreground=MUTED)
                continue
            text = STATUSES.get(result.status, result.status)
            if target.id == "face_touch":
                text = {"candidate": "근접 1회 · 다음 관측 확인", "bad": "만지기 추정 · 연속 근접 2회",
                        "good": "얼굴에서 떨어짐"}.get(result.status, text)
            if result.value is not None:
                text += f" · 변화 {result.value:.2f} / 기준 {result.limit:.2f}"
            if result.held:
                text += f" · {result.held:.0f}초"
            if result.reason and (result.status in ("unknown", "unsupported", "uncalibrated") or target.id in ('slouch','forward_head') and result.value is not None):
                text += "\n" + result.reason
            color = RED if result.status == "bad" else GREEN if result.status == "good" else MUTED
            label.configure(text=text, foreground=color)
        if snapshot.frame is not None:
            frame = snapshot.frame.copy()
            if obs:
                from .preview import draw_measurement_guides
                draw_measurement_guides(frame, obs)
                for a, b in ((7, 11), (8, 12), (11, 12), (11, 23), (12, 24)):
                    if len(obs.pose) > max(a, b) and min(obs.pose[a][2], obs.pose[b][2]) >= .65:
                        cv2.line(frame, tuple(map(int, obs.pose[a][:2])), tuple(map(int, obs.pose[b][:2])), (193, 220, 103), 2)
                for x, y, confidence in obs.pose:
                    if confidence >= .65:
                        cv2.circle(frame, (int(x), int(y)), 3, (193, 220, 103), -1)
                for index in (11, 12):
                    if len(obs.pose) > index and obs.pose[index][2] >= .75:
                        center = tuple(map(int, obs.pose[index][:2]))
                        cv2.circle(frame, center, 9, (100, 210, 255), 2)
                        cv2.circle(frame, center, 3, (100, 210, 255), -1)
                import math
                for shoulder in obs.quality.get("shoulders", {}).values():
                    if shoulder["accepted"]:
                        continue
                    x, y = shoulder["raw_point"][:2]
                    if math.isfinite(x) and math.isfinite(y) and 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                        x, y = int(x), int(y)
                        cv2.line(frame, (x-6, y-6), (x+6, y+6), (110, 110, 245), 2)
                        cv2.line(frame, (x-6, y+6), (x+6, y-6), (110, 110, 245), 2)
                for i in (10, 152, 61, 291, 234, 454):
                    if len(obs.face) > i:
                        cv2.circle(frame, tuple(map(int, obs.face[i])), 3, (104, 190, 235), -1)
                for hand in obs.hands:
                    for x, y in hand:
                        cv2.circle(frame, (int(x), int(y)), 3, (150, 140, 242), -1)
            if not self.args.demo:
                frame = cv2.flip(frame, 1)
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            image.thumbnail((max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())))
            from PIL import ImageDraw
            mask = Image.new("L",(image.width*2,image.height*2),0)
            ImageDraw.Draw(mask).rounded_rectangle((0,0,mask.width-1,mask.height-1),radius=20,fill=255)
            image.putalpha(mask.resize(image.size,Image.Resampling.LANCZOS))
            self.photo = ImageTk.PhotoImage(image)
            self.canvas.delete("all")
            self.canvas.create_image(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, image=self.photo)
            if obs:
                from .preview import measurement_label
                label = measurement_label(obs)
                legend = "민트: 자세 · 골드: 얼굴 기준 · 보라: 손/근접 영역 · 빨강 ×: 제외된 어깨"
                text = self.canvas.create_text(14, 12, anchor="nw", text=legend + ("\n" + label if label else ""),
                                              width=max(80, self.canvas.winfo_width() - 28),
                                              fill="#edf0f4", font=("Segoe UI", 9))
                box = self.canvas.bbox(text)
                if box:
                    x1,y1,x2,y2 = box[0]-6,box[1]-4,box[2]+6,box[3]+4
                    r=8
                    panel = self.canvas.create_polygon(x1+r,y1,x2-r,y1,x2,y1,x2,y1+r,
                        x2,y2-r,x2,y2,x2-r,y2,x1+r,y2,x1,y2,x1,y2-r,x1,y1+r,x1,y1,
                        smooth=True,fill=BG,outline="")
                    self.canvas.tag_raise(text, panel)
        else:
            self.canvas.delete("all")
            self.canvas.create_text(self.canvas.winfo_width()/2, self.canvas.winfo_height()/2, text=snapshot.message, width=550, fill=MUTED, font=("Segoe UI", 13))
        if snapshot.stats is not None:
            self.latest_stats = snapshot.stats
            good, bad = snapshot.stats["today_good"], snapshot.stats["today_bad"]
            total = good + bad
            value = f"{100 * good / total:.0f}" if total else "—"
            quality = " · 관측 부족" if 0 < total < 1800 else ""
            weekly = snapshot.stats.get("week")
            week = f"{weekly:.0f}" if weekly is not None else "—"
            prefix = "DEMO · 실제 기록 없음" if self.args.demo else "오늘 점수"
            self.score.set(f"{prefix} {value}{quality}  |  유효 관측 {total / 60:.1f}분  |  주간 평균 {week}")
            self.behavior_summary.set(f"얼굴 만지기 · 확인된 구간 {snapshot.stats.get('touch_episodes', 0)}회 / {snapshot.stats.get('touch_seconds', 0):.0f}초 · 자세 점수와 별도")
            self.draw_graph(snapshot.stats)

    def update_navigation(self, event=None):
        selected = self.notebook.index(self.notebook.select())
        for index, button in enumerate(self.nav_buttons):
            button.configure(image=self.nav_images[index][index == selected])
        if hasattr(self,"guide"):
            self.guide.tab_changed()

    def draw_graph(self, stats):
        from PIL import ImageTk
        from .dashboard import render_dashboard
        width, height = max(800, self.graph.winfo_width()), max(560, self.graph.winfo_height())
        hover = getattr(self,"graph_hover",None)
        key = (width, height, repr(stats), date.today(), self.args.demo, self.chart_period,hover)
        if getattr(self, "dashboard_key", None) == key:
            return
        self.dashboard_key = key
        image = render_dashboard(width, height, stats, self.args.demo, self.chart_period,hover)
        self.dashboard_photo = ImageTk.PhotoImage(image)
        self.graph.delete("all")
        self.graph.create_image(0, 0, anchor="nw", image=self.dashboard_photo)

    def graph_region(self, x, y):
        from .dashboard import dashboard_hit
        return dashboard_hit(self.graph.winfo_width(),self.graph.winfo_height(),self.latest_stats,self.chart_period,x,y)

    def hover_graph(self,event):
        self.set_graph_hover(self.graph_region(event.x,event.y))

    def set_graph_hover(self,region):
        self.graph.configure(cursor="hand2" if region else "")
        if getattr(self,"graph_hover",None)!=region:
            self.graph_hover=region
            self.draw_graph(self.latest_stats)

    def click_graph(self, event):
        region = self.graph_region(event.x,event.y)
        if region in ("switch_week","switch_month"):
            self.chart_period = region.removeprefix("switch_")
            self.graph_hover = None
            self.draw_graph(self.latest_stats)
        elif region:
            self.show_record_details(self.chart_period if region=="period" else region)

    def show_record_details(self, period):
        from datetime import datetime
        from .dashboard import format_duration
        tk = self.tk
        title = {"today":"오늘","week":"이번 주","month":"이번 달"}.get(period,
                 "주간" if period.startswith("range_week:") else "하루")
        data = self.latest_stats.get("periods",{}).get(period,{})
        if not data and ":" in period:
            selected = date.fromisoformat(period.split(":",1)[1])
            last = selected+timedelta(days=6-selected.weekday()) if period.startswith("range_week:") else selected
            data = {"start":selected.isoformat(),"end":last.isoformat()}
        if self.detail_window and self.detail_window.winfo_exists():
            self.detail_window.destroy()
        popup = self.detail_window = tk.Toplevel(self.root)
        popup.title(title+" 자세 상세 기록")
        popup.configure(bg=BG)
        popup.geometry("650x610")
        popup.minsize(580,570)
        popup.transient(self.root)
        from .ui_widgets import style_titlebar
        style_titlebar(popup)
        host = tk.Frame(popup,bg=BG,padx=24,pady=22)
        host.pack(fill="both",expand=True)
        tk.Label(host,text=title+" 자세 상세",bg=BG,fg=TEXT,font=("Segoe UI",20),anchor="w").pack(fill="x")
        dates = data.get("start","—")+" ~ "+data.get("end","—")
        tk.Label(host,text=dates,bg=BG,fg=MUTED,font=("Segoe UI",10),anchor="w").pack(fill="x",pady=(3,14))
        summary = tk.Frame(host,bg=PANEL,padx=14,pady=14)
        summary.pack(fill="x",pady=(0,16))
        score = data.get("score") if not self.args.demo else None
        score_text = f"{score:.0f} / 100" if score is not None else "기록 부족"
        tk.Label(summary,text="자세 점수  "+score_text,bg=PANEL,fg=GREEN,font=("Segoe UI",15,"bold"),anchor="w").pack(fill="x")
        tk.Label(summary,text=f"정상 {format_duration(data.get('good',0))}   ·   이탈 {format_duration(data.get('bad',0))}",
                 bg=PANEL,fg=TEXT,font=("Segoe UI",10),anchor="w").pack(fill="x",pady=(7,0))
        table = tk.Frame(host,bg=BG)
        table.pack(fill="x")
        table.columnconfigure(0,weight=1)
        for column,label in enumerate(("자세 / 습관","이탈 지속 시간")):
            tk.Label(table,text=label,bg=BG,fg=MUTED,font=("Segoe UI",10),anchor="w" if column==0 else "e",
                     padx=10,pady=8).grid(row=0,column=column,sticky="ew")
        since = data.get("details_since")
        covered = bool(since and since[:10] <= data.get("end",""))
        for row,target in enumerate((target for target in TARGETS if target.available),1):
            record = data.get("targets",{}).get(target.id,{})
            available = target.behavior or covered
            values = (target.label+(" · 별도 기록" if target.behavior else ""),
                      format_duration(record.get("seconds",0)) if available else "—")
            for column,value in enumerate(values):
                tk.Label(table,text=value,bg=PANEL if row%2 else BG,fg=TEXT if column==0 else GOLD,
                         font=("Segoe UI",10),anchor="w" if column==0 else "e",padx=10,pady=9).grid(row=row,column=column,sticky="ew")
        notes = ["확인된 자세 이탈 시간을 항목별로 합산합니다. 동시에 발생한 항목은 각각 기록합니다.",
                 "얼굴 만지기는 자세 점수와 별도로 기록합니다."]
        if since:
            notes.append("항목별 시간은 "+datetime.fromisoformat(since).strftime("%m월 %d일 %H:%M")+"부터 기록합니다. 그 이전 점수는 유지됩니다.")
        else:
            notes.append("이전 기록에는 항목별 이탈 정보가 없습니다. 새 기록부터 집계합니다.")
        notes.append("주간·월간 점수는 하루 30분 이상 측정한 날의 관측 시간을 합산합니다." if period!="today" and not period.startswith("day:") else
                     "오늘 30분 미만 측정한 점수는 잠정 점수입니다.")
        tk.Label(host,text="\n".join(notes),bg=BG,fg=MUTED,font=("Segoe UI",9),justify="left",wraplength=590,
                 anchor="w").pack(fill="x",pady=(14,0))
        popup.bind("<Escape>",lambda _:popup.destroy())

    def poll(self):
        if self.shutting:
            return
        while True:
            try:
                action = self.ui_actions.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self.show()
            elif action == "quit":
                self.close()
                return
            else:
                if action in ("start", "pause"):
                    self.observation_enabled.set(action == "start")
                    self.observation_switch.label = "카메라 켜짐" if action == "start" else "카메라 꺼짐"
                    self.observation_switch.draw()
                self.worker.submit(action)
        try:
            self.render(self.worker.snapshots.get_nowait())
        except queue.Empty:
            pass
        while True:
            try:
                kind, message = self.worker.events.get_nowait()
            except queue.Empty:
                break
            if kind == "alert":
                self.notify(message)
            elif kind == "alert_clear":
                self.notifications.pop(message,None)
                self.refresh_notification()
            elif kind == "calibration_saved":
                self.message.set(message)
                self.guide.registered()
            elif kind=='registration_failed':
                self.message.set(message)
                self.notify({'id':'registration:failed','message':'올바른 자세 등록 실패',
                             'detail':message,'muted':True,'duration':8})
            elif kind in ("monitor_deleted","monitor_delete_failed"):
                setup=getattr(self,"monitor_setup",None)
                if setup is not None and setup.window.winfo_exists():
                    if kind=="monitor_deleted":
                        setup.deleted(message)
                    else:
                        setup.deleting=False
                self.message.set("화면과 등록한 자세를 삭제했습니다" if kind=="monitor_deleted" else message)
            else:
                self.message.set(message)
        self.root.after(80, self.poll)

    def notify(self, message):
        if isinstance(message,str):
            message = {"id":"posture","message":message,"detail":"정상 자세가 확인되면 알림이 사라져요"}
        message = dict(message)
        self.notification_sequence += 1
        message["token"] = self.notification_sequence
        self.notifications[message["id"]] = message
        self.refresh_notification()
        if not message.get("muted",self.settings.muted):
            try:
                import winsound
                winsound.PlaySound("SystemNotification",winsound.SND_ALIAS|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            except (ImportError,RuntimeError):
                pass
        if message.get("duration"):
            self.root.after(round(message["duration"]*1000),lambda:self.expire_notification(message["id"],message["token"]))

    def expire_notification(self,identity,token):
        if self.notifications.get(identity,{}).get("token")==token:
            self.notifications.pop(identity,None)
            self.refresh_notification()

    def dismiss_notification(self):
        self.notifications.clear()
        self.refresh_notification()

    def refresh_notification(self):
        for window in self.notification_windows:
            if window.winfo_exists():
                window.destroy()
        self.notification_windows=[]
        self.notification_window = None
        if not self.notifications or self.shutting:
            return
        from PIL import Image, ImageDraw, ImageTk
        from tkinter import font as tkfont
        tk = self.tk
        transparent = "#010203"
        messages = list(self.notifications.values())
        titles = {"posture":"자세를 바로잡아 주세요","touch":"손을 얼굴에서 내려 주세요"}
        if set(self.notifications)=={"posture","touch"}:
            title = "자세를 바로잡고 손을 내려 주세요"
        else:
            title = titles.get(messages[-1]["id"],messages[-1]["message"])
            if len(messages)>1:
                title += f" · 외 {len(messages)-1}개"
        title_font = tkfont.Font(family="Segoe UI",size=10)
        self.notification_title_font = title_font
        width = min(max(220,title_font.measure(title)+56),360,self.root.winfo_screenwidth()-48)
        while title and title_font.measure(title)>width-56:
            title = title[:-2]+"…" if title.endswith("…") else title[:-1]+"…"
        height = 40
        background = Image.new("RGB",(width*2,height*2),transparent)
        draw = ImageDraw.Draw(background)
        bounds = (3,3,width*2-4,height*2-4)
        # Softer rectangle corners, without an outline around the notification.
        mask = Image.new("L",background.size)
        ImageDraw.Draw(mask).rounded_rectangle(bounds,radius=20,fill=255)
        gradient = Image.new("RGB",background.size)
        gradient_draw = ImageDraw.Draw(gradient)
        for yy in range(height*2):
            t = yy/max(1,height*2-1)
            color = tuple(round(a+(b-a)*t) for a,b in zip((42,61,76),(32,47,60)))
            gradient_draw.line((0,yy,width*2,yy),fill=color)
        background.paste(gradient,(0,0),mask)
        self.notification_photo = ImageTk.PhotoImage(background.resize((width,height),Image.Resampling.LANCZOS))
        from .displays import popup_positions
        positions=popup_positions(self.get_display_bounds(),width,height)
        for x,y in positions:
            popup=tk.Toplevel(self.root)
            popup.title("Posture Track")
            popup.overrideredirect(True)
            popup.configure(bg=transparent)
            popup.attributes("-topmost",True)
            popup.attributes("-transparentcolor",transparent)
            popup.geometry(f"{width}x{height}+{x}+{y}")
            self.notification_windows.append(popup)
            canvas=tk.Canvas(popup,width=width,height=height,bg=transparent,highlightthickness=0)
            canvas.pack()
            canvas.create_image(0,0,image=self.notification_photo,anchor="nw")
            canvas.create_oval(16,17,22,23,fill="#d0b28d",outline="")
            canvas.create_text(32,20,text=title,fill="#e4eaf0",font=title_font,anchor="w")
            canvas.create_text(width-16,20,text="×",fill="#8596a3",font=("Segoe UI",11),tags="dismiss")
            canvas.tag_bind("dismiss","<Button-1>",lambda _:self.dismiss_notification())
            canvas.tag_bind("dismiss","<Enter>",lambda _,canvas=canvas:canvas.configure(cursor="hand2"))
            canvas.tag_bind("dismiss","<Leave>",lambda _,canvas=canvas:canvas.configure(cursor=""))
        self.notification_window=self.notification_windows[0] if self.notification_windows else None

    def hide(self):
        if self.tray is None:
            try:
                import pystray
                from PIL import Image, ImageDraw
                icon = Image.open(ROOT / "assets" / "posture-track.png").convert("RGBA")
                self.tray = pystray.Icon("PostureTrack", icon, "Posture Track", pystray.Menu(
                    pystray.MenuItem("카메라 화면 열기", lambda *_: self.ui_actions.put("show"), default=True),
                    pystray.MenuItem("카메라 끄기", lambda *_: self.ui_actions.put("pause")),
                    pystray.MenuItem("카메라 켜기", lambda *_: self.ui_actions.put("start")),
                    pystray.MenuItem("종료", lambda *_: self.ui_actions.put("quit")),
                ))
                threading.Thread(target=self.tray.run, daemon=True).start()
            except Exception as exc:
                self.message.set(f"트레이를 사용할 수 없어 창을 유지합니다: {exc}")
                return
        self.worker.submit("preview", False)
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.worker.submit("preview", True)

    def check_ui_smoke(self):
        # Inspect our own Tk widgets only; never capture desktop pixels.
        try:
            self.root.update_idletasks()
            choices = tuple(self.validation_combo["values"])
            assert self.alert_combo.values==tuple(ALERT_DELAYS)
            assert self.alert.get() in ALERT_DELAYS
            assert self.sensitivity_combo.values == ('standard', 'sensitive')
            assert self.posture_sensitivity.get() == self.settings.posture_sensitivity
            assert len(choices) == 2 + sum(t.available and not t.behavior for t in TARGETS)
            assert self.validation_case.get() == "평소 자세 · 전체 항목 확인"
            assert len(self.notebook.tabs()) == 3
            assert self.notebook.select() == str(self.dashboard_page)
            assert self.graph.winfo_width() > 100
            self.notebook.select(self.settings_page)
            self.root.update_idletasks()
            assert self.canvas.winfo_width() > 100 and self.canvas.winfo_height() > 100
            assert self.settings_canvas.winfo_width() > 100
            from types import SimpleNamespace
            from .ui_widgets import RoundedScrollbar
            for canvas,scrollbar in ((self.settings_canvas,self.settings_scrollbar),
                                     (self.reminder_ui.canvas,self.reminder_ui.scrollbar)):
                assert isinstance(scrollbar,RoundedScrollbar)
                self.notebook.select(self.settings_page if canvas is self.settings_canvas else self.reminders_page)
                self.root.update_idletasks()
                original_region = canvas.cget("scrollregion")
                canvas.configure(scrollregion=(0,0,canvas.winfo_width(),canvas.winfo_height()*3))
                canvas.yview_moveto(0)
                self.root.update_idletasks()
                top,bottom,_,_ = scrollbar.bounds()
                y=(top+bottom)/2
                scrollbar.press(SimpleNamespace(y=y))
                scrollbar.drag(SimpleNamespace(y=y+70))
                assert canvas.yview()[0]>0
                scrollbar.release(SimpleNamespace(y=y+70))
                canvas.yview_moveto(0)
                self.root.update_idletasks()
                canvas.configure(scrollregion=(0,0,canvas.winfo_width(),canvas.winfo_height()*3))
                scrollbar.set(*canvas.yview())
                scrollbar.press(SimpleNamespace(y=scrollbar.bounds()[1]+10))
                assert canvas.yview()[0]>0
                canvas.configure(scrollregion=original_region)
                canvas.yview_moveto(0)
            self.notebook.select(self.settings_page)
            self.root.update_idletasks()
            status_label = self.status_labels["slouch"]
            status_label.configure(text="판정 불가\n카메라와의 거리가 달라 어깨 자세를 다시 확인하고 있어요")
            self.root.update_idletasks()
            assert float(status_label.cget("wraplength"))<=status_label.winfo_width()
            from tkinter import font as tkfont
            assert status_label.winfo_height()>=tkfont.Font(font=status_label.cget("font")).metrics("linespace")*3
            assert self.camera_combo.values == tuple(str(device.index) for device in self.cameras)
            import tempfile
            previous_directory=self.directory
            previous_registration=self.latest_registration
            previous_submit=self.worker.submit
            submitted=[]
            try:
                with tempfile.TemporaryDirectory() as folder:
                    self.directory=Path(folder)
                    self.latest_registration={}
                    self.open_monitor_setup()
                    self.root.update_idletasks()
                    setup=self.monitor_setup
                    selected=setup.selected
                    x,y=selected['x']*setup.canvas.winfo_width(),selected['y']*setup.canvas.winfo_height()
                    setup.press(SimpleNamespace(x=x,y=y))
                    setup.drag(SimpleNamespace(x=x+40,y=y+20))
                    setup.release(SimpleNamespace())
                    setup.name.set('더 왼쪽 작업 화면')
                    setup.kind.set('laptop')
                    setup.change_kind()
                    assert setup.selected['name']=='더 왼쪽 작업 화면'
                    assert setup.selected['kind']=='laptop'
                    before=len(setup.layout.nodes)
                    setup.add()
                    assert len(setup.layout.nodes)==before+1
                    target_id=setup.selected['id']
                    self.worker.submit=lambda action,value=None:submitted.append((action,value))
                    setup.delete_selected()
                    assert submitted[-1]==('monitor_delete',{'profile_id':target_id})
                    setup.deleted(target_id)
                    assert len(setup.layout.nodes)==before
                    assert setup.selected['id']!=target_id
                    # Deleting the last card leaves an empty workspace which
                    # can immediately accept a new screen.
                    for node in list(setup.layout.nodes):
                        setup.deleted(node['id'])
                    assert setup.selected is None
                    setup.register()
                    setup.add()
                    target_id=setup.selected['id']
                    setup.register()
                    assert submitted[-1][0]=='calibrate_prepare'
                    assert submitted[-1][1]['profile_id']==target_id
            finally:
                self.directory=previous_directory
                self.latest_registration=previous_registration
                self.worker.submit=previous_submit
            assert self.sound_switch.sound_enabled.get()==(not self.muted.get())
            assert ("소리 꺼짐" if self.muted.get() else "소리 켜짐") in self.sound_switch.label
            from .dashboard import font
            assert font(12).getlength(self.sound_switch.label)<=self.sound_switch.width*2-104
            self.validation_combo.open()
            self.root.update_idletasks()
            assert self.validation_combo.popup.winfo_exists()
            assert len(self.validation_combo.rows) == len(choices)
            assert self.validation_combo.rows[0].cget("foreground") == "#a8c8e4"
            self.validation_combo.highlight(1)
            self.validation_combo.select(1)
            assert self.validation_case.get() == choices[1]
            assert self.validation_combo.popup is None
            self.validation_case.set(choices[0])
            self.validation_combo.open()
            self.root.update_idletasks()
            self.validation_combo.popup.focus_force()
            self.root.update()
            self.validation_combo.popup.event_generate("<Escape>")
            self.root.update()
            assert self.validation_combo.popup is None
            assert self.root.grab_current() is None
            self.show_record_details("today")
            self.root.update_idletasks()
            assert self.detail_window.winfo_exists()
            self.detail_window.destroy()
            from .dashboard import dashboard_regions
            from types import SimpleNamespace
            regions = dashboard_regions(self.graph.winfo_width(),self.graph.winfo_height())
            for period in ("week","month"):
                left,top,right,bottom = regions[period]
                self.click_graph(SimpleNamespace(x=(left+right)/2,y=(top+bottom)/2))
                self.root.update_idletasks()
                assert self.detail_window.winfo_exists()
                self.detail_window.destroy()
            assert self.root.protocol("WM_DELETE_WINDOW").endswith("hide")
            self.notebook.select(self.reminders_page)
            self.root.update_idletasks()
            assert len(self.reminder_ui.rows)==len(self.reminder_book.items)
            for row in self.reminder_ui.rows.values():
                assert row["card"].winfo_height()>100
                assert row["card"].winfo_height()>=row["card"].content.winfo_reqheight()+40
            existing_ids = {item.id for item in self.reminder_book.items}
            self.reminder_ui.edit()
            fields = self.reminder_ui.editor_fields
            assert fields["muted"].get()
            assert "소리 꺼짐" in fields["sound"].label
            fields["sound"].invoke()
            assert not fields["muted"].get() and "소리 켜짐" in fields["sound"].label
            fields["sound"].invoke()
            assert fields["muted"].get() and "소리 꺼짐" in fields["sound"].label
            fields["title"].set("UI 예약 검사")
            fields["mode"].set("매일 지정 시각")
            fields["choose"]()
            fields["time"].set("25:99")
            fields["save"]()
            assert self.reminder_ui.editor.winfo_exists() and fields["error"].get()
            fields["time"].set("10:30")
            fields["enabled"].set(False)
            fields["save"]()
            added = next(item for item in self.reminder_book.items if item.id not in existing_ids)
            assert added.mode=="daily" and added.time=="10:30" and added.muted and not added.enabled
            self.reminder_ui.edit(added.id)
            fields = self.reminder_ui.editor_fields
            fields["mode"].set("반복 간격")
            fields["choose"]()
            fields["hour"].set("3")
            fields["minute"].set("15")
            fields["save"]()
            assert next(item for item in self.reminder_book.items if item.id==added.id).interval_minutes==195
            self.reminder_ui.remove(added.id)
            assert {item.id for item in self.reminder_book.items}==existing_ids
            self.notify({"id":"reminder:ui","message":"물 마시기","detail":"","duration":12,"muted":True})
            assert self.notification_window.winfo_exists()
            token = self.notifications["reminder:ui"]["token"]
            self.expire_notification("reminder:ui",token-1)
            assert "reminder:ui" in self.notifications
            self.expire_notification("reminder:ui",token)
            assert self.notification_window is None
            original_bounds=self.get_display_bounds
            self.get_display_bounds=lambda:[(0,0,1920,1080),(-1920,0,0,1080),(0,-1080,1920,0)]
            try:
                for kind in ('posture','touch','reminder:multi','registration:failed'):
                    self.notify({"id":kind,"message":"화면 알림 테스트","muted":True})
                    self.root.update_idletasks()
                    assert len(self.notification_windows)==3
                    popup_width=self.notification_window.winfo_width()
                    from .displays import popup_positions
                    assert [(window.winfo_x(),window.winfo_y()) for window in self.notification_windows]==popup_positions(self.get_display_bounds(),popup_width)
                    windows=list(self.notification_windows)
                    self.dismiss_notification()
                    assert not self.notification_windows
                    assert all(not window.winfo_exists() for window in windows)
            finally:
                self.get_display_bounds=original_bounds
            self.notify({"id":"posture","message":"자세를 편안하게 바로잡아 주세요","detail":"머리 기울임 · 어깨 높이"})
            self.root.update_idletasks()
            assert self.notification_window.winfo_exists()
            assert self.notification_window.winfo_y() == 24
            assert abs(self.notification_window.winfo_x()-(self.root.winfo_screenwidth()-self.notification_window.winfo_width())//2)<=1
            self.notifications.pop("posture")
            self.refresh_notification()
            assert self.notification_window is None
            self.notebook.select(self.dashboard_page)
            self.root.geometry("980x740")
            self.root.update_idletasks()
            self.draw_graph({"today_good": 900, "today_bad": 300,
                             "days": [(date.today().isoformat(), 900, 300)], "week": None})
            assert len(self.graph.find_all()) == 1
            assert self.dashboard_photo.width() >= 800
            self.draw_graph({})
            from .onboarding import FirstUseGuide
            self.guide.destroy()
            self.guide=FirstUseGuide(self,force=True)
            first_guide=[]
            self.root.after(0,lambda:first_guide.append(self.guide.card is not None))
            self.root.update()
            assert first_guide==[True]  # Display precedes later timers, without waiting for idle.
            self.root.update_idletasks()
            assert self.guide.stage=="camera" and self.guide.card.winfo_exists()
            assert self.guide.ring is None
            assert self.guide.card.attributes("-transparentcolor")==self.guide.card.key
            assert self.guide.card.surface.beak_x>0
            assert self.guide.card.winfo_height()>100
            self.notebook.select(self.settings_page)
            self.root.update()
            assert self.guide.stage=="register"
            self.guide.progress(True)
            assert self.guide.ring is None
            self.guide.progress(False)
            assert self.guide.stage=="register"  # A failed/cancelled registration cannot advance.
            self.guide.registered()
            assert self.guide.stage=="sensitivity"
            self.root.update()
            assert self.guide.target is self.nav_buttons[1]
            self.guide.next()
            assert self.guide.stage=="records"
            self.notebook.select(self.dashboard_page)
            self.root.update()
            self.guide.next()
            assert self.guide.stage=="reminders"
            self.notebook.select(self.reminders_page)
            self.root.update()
            self.guide.finish()
            assert self.guide.stage=="done" and self.guide.card is None and self.guide.ring is None
            self.guide.destroy()
            print(f"PASS: demo UI initialized; {len(choices)} validation choices; common reference selected; no screenshot", flush=True)
        finally:
            self.close()

    def close(self):
        if self.shutting:
            return
        self.shutting = True
        self.worker.submit("stop")
        if self.tray:
            self.tray.stop()
        self.finish_close()

    def finish_close(self):
        if self.worker.is_alive():
            self.root.after(100, self.finish_close)
        else:
            self.root.destroy()

    def run(self):
        errors = []
        if self.args.ui_smoke:
            def smoke_exception(kind, error, traceback):
                errors.append(error)
                self.close()
            self.root.report_callback_exception = smoke_exception
        self.root.mainloop()
        if errors:
            raise RuntimeError("UI smoke check failed") from errors[0]


def main():
    parser = argparse.ArgumentParser(description="Posture Track local observation prototype")
    parser.add_argument("--demo", action="store_true", help="Synthetic observations; no webcam or real score writes")
    parser.add_argument("--dev-alerts", action="store_true", help="Explicit development mode: 10-second alerts")
    parser.add_argument("--release-alerts", action="store_true", help="Release timing: minimum 5 minutes; default prototype uses 10 seconds")
    parser.add_argument("--validation-capture", action="store_true", help="Explicit test-only: save one raw frame and matching measurements per completed trial locally")
    parser.add_argument("--data-dir", help="Local settings and records directory")
    parser.add_argument("--ui-smoke", action="store_true", help="Demo UI widget check then exit; no screenshots; requires --demo")
    parser.add_argument("--background", action="store_true", help="Start in the system tray at Windows sign-in")
    parser.add_argument("--self-check", metavar="REPORT", help="Verify bundled assets and models offline, write a JSON report, then exit")
    args = parser.parse_args()
    if args.ui_smoke and not args.demo:
        parser.error("--ui-smoke requires --demo; it never captures a webcam or screen")
    if args.release_alerts and args.dev_alerts:
        parser.error("--release-alerts and --dev-alerts cannot be combined")
    if args.validation_capture and (args.demo or args.release_alerts or args.ui_smoke):
        parser.error("--validation-capture requires real-camera test mode")
    enforce_local_only()
    if args.self_check:
        import json
        import numpy as np
        from .vision import LocalModels
        for name in ("posture-track.ico", "posture-track.png"):
            assert (ROOT / "assets" / name).is_file(), name
        models = LocalModels(ROOT / "models")
        try:
            models.ensure(hands=True)
            observation = models.detect(np.zeros((480, 640, 3), dtype=np.uint8), 1.0)
            assert not observation.pose and not observation.face and not observation.hands
        finally:
            models.close()
        Path(args.self_check).write_text(json.dumps({"ok": True, "resources": str(ROOT), "data": str(default_data_dir())}), encoding="utf-8")
        return
    import sys
    if getattr(sys, "frozen", False) and not args.demo and not acquire_instance():
        if not args.background:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "이미 실행 중입니다. 작업 표시줄의 트레이 아이콘에서 창을 열어 주세요.", "Posture Track", 64)
        return
    App(args).run()
