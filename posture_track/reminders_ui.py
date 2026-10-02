"""Themed reminder page and schedule editor."""
from dataclasses import replace
from datetime import datetime
import tkinter as tk
from tkinter import ttk

from .reminders import new_reminder
from .ui_widgets import RoundedButton, RoundedCard, RoundedEntry, RoundedScrollbar, SoundSwitch, Switch, ThemedDropdown, style_titlebar

BG,PANEL,TEXT,MUTED = "#18191e","#25272e","#edf0f4","#a0a6b1"


class ReminderPage:
    def __init__(self,app,parent,book):
        self.app,self.book = app,book
        self.editor = None
        self.rows = {}
        host = ttk.Frame(parent,padding=(0,16))
        host.pack(fill="both",expand=True)
        header = ttk.Frame(host)
        header.pack(fill="x")
        ttk.Label(header,text="맞춤 알림",font=("Segoe UI",23)).pack(side="left")
        RoundedButton(header,text="알림 추가",command=self.edit,primary=True).pack(side="right")
        ttk.Label(host,text="정해진 시각 또는 원하는 간격으로 생활 알림을 받아보세요.",
                  style="Muted.TLabel").pack(anchor="w",pady=(5,16))
        self.message = tk.StringVar(value="소리를 꺼도 화면 알림은 표시됩니다. 소리는 알림마다 설정할 수 있어요.")
        ttk.Label(host,textvariable=self.message,style="Muted.TLabel",wraplength=850).pack(anchor="w",pady=(0,14))
        scrolling = ttk.Frame(host)
        scrolling.pack(fill="both",expand=True)
        self.canvas = tk.Canvas(scrolling,bg=BG,highlightthickness=0)
        scroll = self.scrollbar = RoundedScrollbar(scrolling,command=self.canvas.yview)
        scroll.pack(side="right",fill="y",padx=(6,0))
        self.canvas.pack(side="left",fill="both",expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.list = tk.Frame(self.canvas,bg=BG)
        window = self.canvas.create_window((0,0),window=self.list,anchor="nw")
        self.list.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda event:self.canvas.itemconfigure(window,width=event.width))
        app.root.bind("<MouseWheel>",self.scroll,add=True)
        self.render()
        app.root.after(1000,self.tick)

    def scroll(self,event):
        if self.app.notebook.select()==str(self.app.reminders_page):
            self.canvas.yview_scroll(-int(event.delta/120),"units")

    def render(self):
        for child in self.list.winfo_children():
            child.destroy()
        self.rows.clear()
        if not self.book.items:
            tk.Label(self.list,text="아직 알림이 없어요. ‘알림 추가’로 만들어 주세요.",bg=BG,fg=MUTED,
                     font=("Segoe UI",12),pady=36).pack(fill="x")
        for item in self.book.items:
            surface = RoundedCard(self.list,padding=20,radius=18)
            surface.pack(fill="x",pady=(0,12))
            card = surface.content
            top = tk.Frame(card,bg=PANEL)
            top.pack(fill="x")
            enabled = tk.BooleanVar(value=item.enabled)
            switch = Switch(top,text="알림 켜짐" if item.enabled else "알림 꺼짐",variable=enabled,
                            command=lambda identity=item.id,var=enabled:self.change(identity,enabled=var.get()),width=140)
            switch.pack(side="right")
            tk.Label(top,text=item.title,bg=PANEL,fg=TEXT,font=("Segoe UI Semibold",16),anchor="w").pack(side="left")
            tk.Label(card,text=item.description(),bg=PANEL,fg="#d0b28d",font=("Segoe UI",11),anchor="w").pack(fill="x",pady=(3,5))
            bottom = tk.Frame(card,bg=PANEL)
            bottom.pack(fill="x")
            next_text = ""
            if item.enabled and item.next_due:
                due = datetime.fromisoformat(item.next_due).astimezone()
                now = datetime.now().astimezone()
                next_text = "다음 알림 · "+(due.strftime("%H:%M") if due.date()==now.date() else due.strftime("%m월 %d일 %H:%M"))
            tk.Label(bottom,text=next_text,bg=PANEL,fg=MUTED,font=("Segoe UI",9),anchor="w").pack(side="left")
            RoundedButton(bottom,text="삭제",min_width=72,background=PANEL,command=lambda identity=item.id:self.remove(identity)).pack(side="right",padx=(6,0))
            RoundedButton(bottom,text="수정",min_width=72,background=PANEL,command=lambda identity=item.id:self.edit(identity)).pack(side="right",padx=(6,0))
            muted = tk.BooleanVar(value=item.muted)
            sound = SoundSwitch(bottom,muted=muted,compact=True,
                                command=lambda identity=item.id,var=muted:self.change(identity,muted=var.get()),width=170)
            sound.pack(side="right",padx=(10,10))
            self.rows[item.id] = {"enabled":enabled,"muted":muted,"sound":sound,"card":surface}

    def change(self,identity,**changes):
        original = next(item for item in self.book.items if item.id==identity)
        try:
            self.book.upsert(replace(original,**changes),datetime.now().astimezone())
            if not next(item for item in self.book.items if item.id==identity).enabled:
                self.app.notifications.pop("reminder:"+identity,None)
                self.app.refresh_notification()
            self.message.set("저장했어요.")
            self.render()
        except (OSError,ValueError) as exc:
            self.message.set(str(exc))
            self.render()

    def remove(self,identity):
        try:
            self.book.remove(identity)
            self.app.notifications.pop("reminder:"+identity,None)
            self.app.refresh_notification()
            self.message.set("알림을 삭제했어요.")
            self.render()
        except OSError as exc:
            self.message.set(str(exc))

    def tick(self):
        if self.app.shutting:
            return
        try:
            due = self.book.due(datetime.now().astimezone())
            for item in due:
                self.app.notify({"id":"reminder:"+item.id,"message":item.title,"detail":"",
                                 "muted":item.muted,"duration":12})
            if due:
                self.render()
        except (ValueError,OSError) as exc:
            self.message.set("알림 설정을 확인해 주세요: "+str(exc))
        self.app.root.after(1000,self.tick)

    def edit(self,identity=None):
        if self.editor and self.editor.winfo_exists():
            self.editor.lift()
            return
        item = next((item for item in self.book.items if item.id==identity),None) or new_reminder()
        popup = self.editor = tk.Toplevel(self.app.root)
        popup.title("알림 수정" if identity else "알림 추가")
        popup.configure(bg=BG)
        x = max(0,min(self.app.root.winfo_screenwidth()-500,self.app.root.winfo_x()+(self.app.root.winfo_width()-500)//2))
        y = max(0,min(self.app.root.winfo_screenheight()-510,self.app.root.winfo_y()+(self.app.root.winfo_height()-510)//2))
        popup.geometry(f"500x510+{x}+{y}")
        popup.resizable(False,False)
        popup.transient(self.app.root)
        style_titlebar(popup)
        host = tk.Frame(popup,bg=BG,padx=24,pady=20)
        host.pack(fill="both",expand=True)
        tk.Label(host,text="알림 수정" if identity else "새 알림",bg=BG,fg=TEXT,font=("Segoe UI Semibold",20),anchor="w").pack(fill="x",pady=(0,14))
        title = tk.StringVar(value=item.title)
        mode = tk.StringVar(value="반복 간격" if item.mode=="interval" else "매일 지정 시각")
        hour = tk.StringVar(value=str(item.interval_minutes//60))
        minute = tk.StringVar(value=str(item.interval_minutes%60))
        time = tk.StringVar(value=item.time)
        enabled,muted = tk.BooleanVar(value=item.enabled),tk.BooleanVar(value=item.muted)
        def entry(parent,variable,width=None):
            box = RoundedEntry(parent,variable,width=100 if width==5 else 132 if width else 280)
            return box,box.entry
        tk.Label(host,text="알림 이름",bg=BG,fg=MUTED,anchor="w").pack(fill="x")
        box,field = entry(host,title)
        box.pack(fill="x",pady=(4,12))
        tk.Label(host,text="언제 알려드릴까요?",bg=BG,fg=MUTED,anchor="w").pack(fill="x")
        dropdown = ThemedDropdown(host,mode,["반복 간격","매일 지정 시각"])
        dropdown.configure(bg=BG)
        dropdown.pack(fill="x",pady=(4,10))
        timing = tk.Frame(host,bg=BG,height=45)
        timing.pack(fill="x",pady=(0,10))
        intervals = tk.Frame(timing,bg=BG)
        box,_ = entry(intervals,hour,5)
        box.pack(side="left")
        tk.Label(intervals,text="시간",bg=BG,fg=MUTED).pack(side="left",padx=(8,16))
        box,_ = entry(intervals,minute,5)
        box.pack(side="left")
        tk.Label(intervals,text="분마다",bg=BG,fg=MUTED).pack(side="left",padx=8)
        daily = tk.Frame(timing,bg=BG)
        box,_ = entry(daily,time,8)
        box.pack(side="left")
        tk.Label(daily,text="24시간 형식 · 예: 09:00",bg=BG,fg=MUTED).pack(side="left",padx=12)
        def choose(_=None):
            intervals.pack_forget()
            daily.pack_forget()
            (intervals if mode.get()=="반복 간격" else daily).pack(fill="x")
        dropdown.bind("<<ComboboxSelected>>",choose)
        choose()
        Switch(host,text="알림 켜기",variable=enabled,command=lambda:None,background=BG).pack(fill="x")
        sound_switch = SoundSwitch(host,muted=muted,command=lambda:None,background=BG)
        sound_switch.pack(fill="x")
        error = tk.StringVar()
        tk.Label(host,textvariable=error,bg=BG,fg="#e59c9e",wraplength=440,justify="left",anchor="w").pack(fill="x",pady=(8,8))
        footer = tk.Frame(host,bg=BG)
        footer.pack(side="bottom",fill="x")
        def save():
            try:
                amount = item.interval_minutes
                if mode.get()=="반복 간격":
                    try:
                        hours,minutes = int(hour.get()),int(minute.get())
                    except ValueError:
                        raise ValueError("반복 간격은 숫자로 입력해 주세요.") from None
                    if not 0<=hours<=168 or not 0<=minutes<60:
                        raise ValueError("시간은 0~168, 분은 0~59로 입력해 주세요.")
                    amount = hours*60+minutes
                updated = replace(item,title=title.get(),mode="interval" if mode.get()=="반복 간격" else "daily",
                                  interval_minutes=amount,time=time.get().strip() if mode.get()=="매일 지정 시각" else item.time,
                                  enabled=enabled.get(),muted=muted.get())
                self.book.upsert(updated,datetime.now().astimezone())
                if not updated.enabled:
                    self.app.notifications.pop("reminder:"+updated.id,None)
                    self.app.refresh_notification()
                popup.destroy()
                self.message.set("저장했어요.")
                self.render()
            except (ValueError,OSError) as exc:
                error.set(str(exc) if str(exc) else "입력값을 확인해 주세요.")
        RoundedButton(footer,text="저장",command=save,primary=True).pack(side="right")
        RoundedButton(footer,text="취소",command=popup.destroy).pack(side="right",padx=8)
        popup.bind("<Escape>",lambda _:popup.destroy())
        # Expose the actual editor controls to the built-in smoke test.
        self.editor_fields = {"title":title,"mode":mode,"hour":hour,"minute":minute,"time":time,
                              "enabled":enabled,"muted":muted,"sound":sound_switch,"save":save,"choose":choose,"error":error}
        field.focus_set()
