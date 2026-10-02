"""Non-modal first-use guidance anchored to existing controls."""
import json
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from .config import atomic_json
from .domain import Profiles
from .ui_widgets import RoundedButton, RoundedCard


class BubbleSurface(RoundedCard):
    def fit(self,event):
        height=self.content.winfo_reqheight()+self.padding*2+10
        if int(self.cget("height"))!=height:
            self.configure(height=height)

    def draw(self,event):
        width,height=max(1,event.width),max(1,event.height)
        self.itemconfigure(self.window,width=max(1,width-self.padding*2))
        self.coords(self.window,self.padding,self.padding+10)
        shape=Image.new("RGBA",(width*4,height*4),(0,0,0,0))
        draw=ImageDraw.Draw(shape)
        draw.rounded_rectangle((4,40,width*4-5,height*4-5),radius=64,fill=self.fill,
                               outline="#414d5b",width=4)
        x=max(24,min(width-24,getattr(self,"beak_x",width//2)))*4
        draw.polygon(((x-32,44),(x,4),(x+32,44)),fill=self.fill)
        draw.line(((x-32,40),(x,4),(x+32,40)),fill="#414d5b",width=4)
        shape=shape.resize((width,height),Image.Resampling.LANCZOS)
        # Exact color-key corners expose any underlying card, video or graph.
        background=Image.new("RGB",shape.size,self.background)
        colors=Image.alpha_composite(Image.new("RGBA",shape.size,self.fill),shape).convert("RGB")
        background.paste(colors,mask=shape.getchannel("A").point(lambda a:255 if a>=128 else 0))
        self.photo=ImageTk.PhotoImage(background)
        self.delete("background")
        self.create_image(0,0,image=self.photo,anchor="nw",tags="background")
        self.tag_lower("background")


class GuideBubble(tk.Toplevel):
    """An owned teaching popover with a pointer and truly clear corners."""
    def __init__(self,root):
        super().__init__(root,takefocus=False)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(root)
        self.key="#ff00ff"
        self.configure(bg=self.key)
        self.attributes("-transparentcolor",self.key)
        self.surface=BubbleSurface(self,background=self.key,fill="#2b333d",padding=16,radius=16)
        self.surface.configure(width=356)
        self.surface.pack(fill="both",expand=True)
        self.content=self.surface.content
        self.target=None
        self.content.bind("<Configure>",lambda _:self.after(0,self.follow),add=True)

    def follow(self,target=None):
        if target is not None:
            self.target=target
        if not self.winfo_exists() or self.target is None:
            return
        target=self.target
        if not target.winfo_viewable():
            self.withdraw()
            return
        root=self.master
        width=356
        x=max(root.winfo_rootx()+12,min(target.winfo_rootx(),root.winfo_rootx()+root.winfo_width()-width-12))
        y=target.winfo_rooty()+target.winfo_height()+8
        self.surface.beak_x=target.winfo_rootx()+target.winfo_width()/2-x
        height=int(self.surface.cget("height"))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.surface.draw(type("Size",(),{"width":width,"height":height})())


class FirstUseGuide:
    def __init__(self,app,force=False):
        self.app,self.root = app,app.root
        self.path = app.directory / "onboarding.json"
        try:
            saved=json.loads(self.path.read_text(encoding="utf-8"))
            saved=saved if isinstance(saved,dict) else {}
        except (OSError,ValueError):
            saved={}
        registered=bool(Profiles(app.directory / "profiles.json").items)
        self.has_registration=registered
        self.stage = saved.get("stage")
        if self.stage not in ("camera","register","sensitivity","records","reminders","done"):
            self.stage = "done" if registered or app.args.demo else "camera"
        if force:
            self.stage="camera"
        self.force=force
        self.card=self.ring=None
        self.registering=False
        self.target=None
        self.closed=False
        self.layout_binding=self.root.bind("<Configure>",self.layout,add=True)
        self.map_binding=self.root.bind("<Map>",self.layout,add=True)
        self.unmap_binding=self.root.bind("<Unmap>",self.layout,add=True)
        # A busy preview may never reach idle, and an idle callback during
        # initial geometry can run before the target button has been mapped.
        self.root.after(0,self.show)

    def save(self):
        if not self.force:
            try:
                atomic_json(self.path,{"version":1,"stage":self.stage})
            except OSError:
                pass

    def tab_changed(self):
        if self.stage=="camera" and self.app.notebook.select()==str(self.app.settings_page):
            self.stage="register"
            self.save()
        self.show()

    def registered(self):
        if self.stage in ("camera","register"):
            self.has_registration=True
            self.stage="sensitivity"
            self.registering=False
            self.save()
            self.show()

    def progress(self,active):
        if self.stage=="register" and self.registering!=active:
            self.registering=active
            self.show()

    def next(self):
        self.stage={"sensitivity":"records","records":"reminders"}.get(self.stage,"done")
        self.save()
        self.show()

    def finish(self):
        self.stage="done"
        self.save()
        self.show()

    def show(self):
        if self.closed:
            return
        for widget in (self.card,self.ring):
            if widget:
                widget.destroy()
        self.card=self.ring=None
        if self.stage=="done":
            return
        selected=self.app.notebook.select()
        action=None
        if self.stage=="camera":
            title,detail="1 / 5 · 카메라부터 준비해요","위의 ‘설정 · 카메라’를 눌러 주세요. 얼굴과 양쪽 어깨 윗부분의 점이 화면 안에 보이도록 앉아 주세요."
            target=self.app.nav_buttons[1]
        elif self.stage=="register":
            title="2 / 5 · 화면마다 자세를 등록해요"
            if selected!=str(self.app.settings_page):
                detail="‘설정 · 카메라’로 돌아가 올바른 자세를 등록해 주세요."
                target=self.app.nav_buttons[1]
            else:
                target=self.app.calibrate_button
                detail=("등록 중이에요. 어깨를 편하게 펴고 화면을 보며 잠시 유지해 주세요."
                        if self.registering else "‘올바른 자세 등록’에서 화면을 추가하고 드래그해 배치하세요. 화면을 클릭하고 등록을 누른 뒤, 평소 앉는 몸통 방향을 유지하며 그 화면을 바라봐 주세요.\n\n4초 준비 후 8~10초간 유지하면 저장돼요. 사용하는 화면마다 등록하세요. 실패하면 사유가 표시돼요. 같은 화면을 다시 등록하면 그 화면의 기준만 갱신되고, 삭제하면 기준 자세도 함께 지워져요.")
                if self.has_registration and not self.registering:
                    action=("다음",self.registered)
        elif self.stage=="sensitivity":
            title="3 / 5 · 나에게 맞게 감지해요"
            if selected==str(self.app.settings_page):
                target=self.app.nav_buttons[1]
                detail="‘자세 감지 민감도’에서 기본 또는 민감을 선택하세요. 민감은 더 작은 자세 변화에도 반응해요. 선택한 설정은 저장되며 얼굴 만지기에는 적용되지 않아요.\n\n확인 주기와 알림까지의 유지 시간은 따로 정할 수 있어요. 위 상태 카드에서 판정을 확인하고, ‘10초 테스트 시작’으로 점검해 보세요.\n\n알림은 연결된 모든 모니터 상단에 표시되고, 자세를 바로잡으면 자동으로 사라져요. 소리는 기본으로 꺼져 있어요."
                action=("다음",self.next)
            else:
                target=self.app.nav_buttons[1]
                detail="‘설정 · 카메라’에서 감지 민감도와 알림 설정을 살펴보세요."
        elif self.stage=="records":
            title="4 / 5 · 자세 변화를 확인해요"
            target=self.app.nav_buttons[0]
            if selected==str(self.app.dashboard_page):
                detail="오늘·주간·월간 점수를 볼 수 있어요. 점수 카드를 누르면 해당 기간에 어떤 자세가 얼마나 지속됐는지 확인할 수 있어요.\n\n주간 카드의 하루 막대나 월간 카드의 주별 막대를 누르면 해당 하루 또는 주의 상세 기록이 열려요. 얼굴 만지기는 자세 점수와 별도로 기록해요."
                action=("다음",self.next)
            else:
                detail="등록했어요! ‘자세 기록’을 눌러 점수와 기록을 확인해 보세요."
        else:
            title="5 / 5 · 생활 알림을 설정해요"
            target=self.app.nav_buttons[2]
            if selected==str(self.app.reminders_page):
                detail="‘알림 추가’에서 정해진 시각 또는 반복 간격을 선택하세요. 물 마시기 2시간·스트레칭 1시간 예시는 꺼져 있어요. 사용할 알림의 스위치를 켜 주세요.\n\n소리는 기본으로 꺼져 있고 알림마다 켤 수 있어요. 창을 X로 닫아도 트레이에서 계속 실행되며, 완전히 종료하면 알림이 멈춰요."
                action=("시작하기",self.finish)
            else:
                detail="마지막으로 ‘맞춤 알림’을 눌러 생활 알림도 살펴보세요."
        self.target=target
        self.card=GuideBubble(self.root)
        inner=self.card.content
        tk.Label(inner,text=title,bg="#2b333d",fg="#d0b28d",font=("Segoe UI",10,"bold"),anchor="w").pack(fill="x")
        tk.Label(inner,text=detail,bg="#2b333d",fg="#edf0f4",font=("Segoe UI",10),
                 wraplength=320,justify="left",anchor="w").pack(fill="x",pady=(7,10))
        footer=tk.Frame(inner,bg="#2b333d")
        footer.pack(fill="x")
        if action:
            RoundedButton(footer,text=action[0],command=action[1],primary=True,background="#2b333d",min_width=82).pack(side="right")
        tk.Button(footer,text="안내 닫기",command=self.finish,bg="#2b333d",fg="#a0a6b1",
                  activebackground="#2b333d",activeforeground="#edf0f4",bd=0,
                  font=("Segoe UI",9),cursor="hand2").pack(side="left",pady=10)
        self.layout()

    def layout(self,event=None):
        if event is not None and event.widget not in (self.root,self.target):
            return
        if not self.card or not self.target:
            return
        self.card.follow(self.target)

    def destroy(self):
        self.closed=True
        self.root.unbind("<Configure>",self.layout_binding)
        self.root.unbind("<Map>",self.map_binding)
        self.root.unbind("<Unmap>",self.unmap_binding)
        for widget in (self.card,self.ring):
            if widget:
                widget.destroy()
        self.card=self.ring=None
