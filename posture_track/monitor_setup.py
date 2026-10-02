"""A draggable, per-screen posture registration workspace."""
import json
import uuid
import tkinter as tk
from .config import atomic_json
from .ui_widgets import RoundedButton, RoundedEntry, ThemedDropdown, style_titlebar

BG,PANEL,TEXT,MUTED="#18191e","#25272e","#edf0f4","#a0a6b1"
VIEW_NAMES={"front":"정면","oblique_left":"왼쪽 사선","oblique_right":"오른쪽 사선","side_left":"왼쪽 측면","side_right":"오른쪽 측면"}


class MonitorLayout:
    def __init__(self,path,bounds,profiles=(),seed=True):
        self.path=path
        data=None
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
            nodes=data.get("screens",[]) if isinstance(data,dict) else []
        except (OSError,ValueError):
            nodes=[]
        self.nodes=[]
        for node in nodes if isinstance(nodes,list) else []:
            try:
                if not isinstance(node,dict) or not isinstance(node["id"],str):
                    continue
                self.nodes.append({"id":node["id"],"name":str(node.get("name","화면"))[:32],
                    "kind":"laptop" if node.get("kind")=="laptop" else "monitor",
                    "x":min(.9,max(.1,float(node["x"]))),"y":min(.85,max(.15,float(node["y"])))})
            except (KeyError,TypeError,ValueError):
                continue
        if not self.nodes and seed and not isinstance(data,dict):
            count=max(1,len(bounds),len(profiles))
            left=min((r[0] for r in bounds),default=0)
            top=min((r[1] for r in bounds),default=0)
            right=max((r[2] for r in bounds),default=1)
            bottom=max((r[3] for r in bounds),default=1)
            for index in range(count):
                profile=profiles[index] if index<len(profiles) else None
                rectangle=bounds[index] if index<len(bounds) else None
                x=.15+.7*((rectangle[0]+rectangle[2])/2-left)/max(1,right-left) if rectangle else (index+1)/(count+1)
                y=.2+.6*((rectangle[1]+rectangle[3])/2-top)/max(1,bottom-top) if rectangle else .5
                self.nodes.append({"id":profile["id"] if profile else uuid.uuid4().hex,
                    "name":profile["name"] if profile and profile["name"] not in VIEW_NAMES else ("주 화면" if index==0 else f"보조 화면 {index}"),
                    "kind":"monitor","x":x,"y":y})

    def save(self):
        atomic_json(self.path,{"version":1,"screens":self.nodes})

    def add(self):
        node={"id":uuid.uuid4().hex,"name":f"화면 {len(self.nodes)+1}","kind":"monitor","x":.5,"y":.72}
        self.nodes.append(node)
        self.save()
        return node

    def remove(self,identity):
        self.nodes=[node for node in self.nodes if node['id']!=identity]
        self.save()


class MonitorSetup:
    def __init__(self,app,bounds,profiles):
        self.app=app
        self.registered={profile["id"] for profile in profiles}
        self.eye_ready={profile["id"] for profile in profiles if profile.get("eye_ready")}
        self.layout=MonitorLayout(app.directory/"monitor-layout.json",bounds,profiles)
        self.selected=self.layout.nodes[0] if self.layout.nodes else None
        self.deleting=False
        self.dragging=None
        self.window=tk.Toplevel(app.root)
        self.window.title("화면 배치 · 자세 등록")
        self.window.transient(app.root)
        self.window.configure(bg=BG)
        center_x=app.root.winfo_rootx()+app.root.winfo_width()//2
        center_y=app.root.winfo_rooty()+app.root.winfo_height()//2
        rectangle=next((r for r in bounds if r[0]<=center_x<r[2] and r[1]<=center_y<r[3]),(0,0,app.root.winfo_screenwidth(),app.root.winfo_screenheight()))
        x=max(rectangle[0],min(center_x-425,rectangle[2]-850))
        y=max(rectangle[1],min(center_y-325,rectangle[3]-650))
        self.window.geometry(f"850x650+{x}+{y}")
        self.window.minsize(740,620)
        host=tk.Frame(self.window,bg=BG,padx=24,pady=20)
        host.pack(fill="both",expand=True)
        tk.Label(host,text="내 화면 배치",bg=BG,fg=TEXT,font=("Segoe UI",21,"bold"),anchor="w").pack(fill="x")
        tk.Label(host,text="화면을 드래그해 실제 배치처럼 놓으세요. 등록할 화면을 클릭하고 그 화면을 바라보는 자세를 저장하세요.",
                 bg=BG,fg=MUTED,font=("Segoe UI",10),wraplength=760,justify="left",anchor="w").pack(fill="x",pady=(5,12))
        self.canvas=tk.Canvas(host,bg="#20232a",highlightthickness=0,height=275,cursor="hand2")
        self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<Configure>",lambda _:self.draw())
        self.canvas.bind("<Button-1>",self.press)
        self.canvas.bind("<B1-Motion>",self.drag)
        self.canvas.bind("<ButtonRelease-1>",self.release)
        row=tk.Frame(host,bg=BG)
        row.pack(fill="x",pady=(12,8))
        RoundedButton(row,"화면 추가",self.add,min_width=90).pack(side="right")
        tk.Label(row,text="선택한 화면",bg=BG,fg=MUTED,font=("Segoe UI",10)).pack(side="left")
        self.name=tk.StringVar(value=self.selected["name"] if self.selected else "")
        RoundedEntry(row,self.name,width=240).pack(side="left",padx=12)
        self.name.trace_add("write",self.rename)
        self.kind=tk.StringVar(value=self.selected["kind"] if self.selected else "monitor")
        kind=ThemedDropdown(row,self.kind,["monitor","laptop"],labels={"monitor":"모니터","laptop":"노트북"})
        kind.configure(bg=BG,width=120)
        kind.pack(side="left")
        kind.bind("<<ComboboxSelected>>",self.change_kind)
        self.status=tk.StringVar()
        tk.Label(host,textvariable=self.status,bg=BG,fg="#d0b28d",font=("Segoe UI",10),anchor="w").pack(fill="x",pady=(1,7))
        tk.Label(host,text="4초의 준비 시간 후, 평소 앉는 몸통 방향을 유지하고 선택한 화면을 바라보며 8~10초간 유지하세요. 어깨는 편하게 펴 주세요.\n완료 시 자동 저장되고, 실패하면 사유가 표시됩니다. 화면마다 머리 방향과 몸통·목 위치 기준을 따로 저장합니다.",
                 bg=BG,fg=MUTED,font=("Segoe UI",9),wraplength=760,justify="left",anchor="w").pack(fill="x")
        footer=tk.Frame(host,bg=BG)
        footer.pack(fill="x",pady=(12,0))
        self.register_button=RoundedButton(footer,"선택한 화면 자세 등록",self.register,primary=True)
        self.register_button.pack(side="right")
        RoundedButton(footer,"닫기",self.window.destroy,min_width=82).pack(side="left")
        RoundedButton(footer,"선택한 화면 삭제",self.delete_selected,min_width=130).pack(side="left",padx=10)
        style_titlebar(self.window)
        self.draw()
        self.window.after(200,self.update_status)

    def update_status(self):
        if not self.window.winfo_exists():
            return
        profiles=self.app.latest_registration.get("profiles",[])
        self.registered={profile["id"] for profile in profiles}
        self.eye_ready={profile["id"] for profile in profiles if profile.get("eye_ready")}
        if self.deleting:
            self.window.after(500,self.update_status)
            return
        if self.selected is None:
            self.status.set("화면 추가를 눌러 새 화면을 등록하세요")
            self.draw()
            self.window.after(500,self.update_status)
            return
        self.status.set(f"{self.selected['name']} · "+("등록 완료 · 다시 등록하면 이 화면의 기준만 갱신돼요" if self.selected["id"] in self.registered else "아직 자세가 등록되지 않았어요"))
        if self.selected['id'] in self.registered and self.selected['id'] not in self.eye_ready:
            self.status.set(f"{self.selected['name']} · 기존 기준 유지 · 다시 등록하면 눈 방향 정보도 함께 저장돼요")
        self.draw()
        self.window.after(500,self.update_status)

    def draw(self):
        self.canvas.delete("all")
        width,height=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        for x in range(20,width,24):
            for y in range(20,height,24):
                self.canvas.create_oval(x,y,x+1,y+1,fill="#30353f",outline="")
        self.boxes={}
        for node in self.layout.nodes:
            x,y=node["x"]*width,node["y"]*height
            x=max(78,min(width-78,x)); y=max(54,min(height-54,y))
            left,top,right,bottom=x-70,y-43,x+70,y+43
            self.boxes[node["id"]]=(left,top,right,bottom)
            selected=node is self.selected
            self.canvas.create_polygon(left+8,top,right-8,top,right,top,right,top+8,right,bottom-8,right,bottom,right-8,bottom,left+8,bottom,left,bottom,left,bottom-8,left,top+8,left,top,
                smooth=True,fill="#344456" if selected else PANEL,outline="#a8c8e4" if selected else "#46505e",width=2 if selected else 1)
            self.canvas.create_rectangle(x-18,bottom+2,x+18,bottom+5,fill="#677589",outline="")
            if node["kind"]=="laptop":
                self.canvas.create_line(left-6,bottom+5,right+6,bottom+5,fill="#a8c8e4",width=4)
            label=node["name"]
            if len(label)>12:
                label=label[:11]+"…"
            self.canvas.create_text(x,y-10,text=label,fill=TEXT,font=("Segoe UI",11,"bold"))
            self.canvas.create_text(x,y+17,text="등록 완료" if node["id"] in self.registered else "클릭하여 등록",fill="#d0b28d" if node["id"] in self.registered else MUTED,font=("Segoe UI",9))

    def press(self,event):
        if self.deleting:
            return
        for node in reversed(self.layout.nodes):
            left,top,right,bottom=self.boxes[node["id"]]
            if left<=event.x<=right and top<=event.y<=bottom:
                self.selected=node
                self.name.set(node["name"])
                self.kind.set(node["kind"])
                self.dragging=(event.x-node["x"]*self.canvas.winfo_width(),event.y-node["y"]*self.canvas.winfo_height())
                self.draw()
                break

    def drag(self,event):
        if self.dragging:
            width,height=self.canvas.winfo_width(),self.canvas.winfo_height()
            self.selected["x"]=min((width-78)/width,max(78/width,(event.x-self.dragging[0])/width))
            self.selected["y"]=min((height-54)/height,max(54/height,(event.y-self.dragging[1])/height))
            self.draw()

    def release(self,event):
        if self.dragging:
            self.dragging=None
            self.layout.save()

    def rename(self,*_):
        if self.selected is None or self.deleting:
            return
        name=self.name.get().strip()[:32]
        if name:
            self.selected["name"]=name
            self.layout.save()
            if self.selected['id'] in self.registered:
                self.app.worker.submit("profile_rename",{"profile_id":self.selected['id'],"label":name})
            self.draw()

    def change_kind(self,event=None):
        if self.selected is None or self.deleting:
            return
        self.selected["kind"]=self.kind.get()
        self.layout.save()
        self.draw()

    def add(self):
        if self.deleting:
            return
        self.selected=self.layout.add()
        self.name.set(self.selected["name"])
        self.kind.set(self.selected["kind"])
        self.draw()

    def register(self):
        if self.selected is None or self.deleting:
            return
        self.layout.save()
        self.app.worker.submit("calibrate_prepare",{"profile_id":self.selected["id"],"label":self.selected["name"]})
        self.app.notebook.select(self.app.settings_page)
        self.app.message.set(f"{self.selected['name']}을 바라봐 주세요 · 4초 뒤 등록을 시작합니다")
        self.window.destroy()

    def delete_selected(self):
        if self.selected is None or self.deleting:
            return
        self.deleting=True
        self.dragging=None
        self.status.set("화면과 등록한 자세를 삭제하고 있어요")
        self.app.worker.submit("monitor_delete",{"profile_id":self.selected['id']})

    def deleted(self,identity):
        self.deleting=False
        self.layout.nodes=[node for node in self.layout.nodes if node['id']!=identity]
        self.registered.discard(identity)
        self.eye_ready.discard(identity)
        self.selected=self.layout.nodes[0] if self.layout.nodes else None
        self.name.set(self.selected['name'] if self.selected else "")
        self.kind.set(self.selected['kind'] if self.selected else "monitor")
        self.draw()
