"""Local rounded controls and native title-bar appearance."""
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from .dashboard import font


class RoundedButton(tk.Button):
    def __init__(self, parent, text, command, primary=False, background="#18191e", min_width=112):
        width = max(min_width, int(font(14).getlength(text)/2)+38)
        self.images = []
        for hover in (False, True):
            image = Image.new("RGB", (width*2,88), background)
            draw = ImageDraw.Draw(image)
            fill = ("#afcbe4" if hover else "#a8c8e4") if primary else ("#333842" if hover else "#2c3039")
            draw.rounded_rectangle((1,1,width*2-1,87),radius=28,fill=fill)
            draw.text((width,44),text,font=font(14),fill="#1b2936" if primary else "#edf0f4",anchor="mm")
            self.images.append(ImageTk.PhotoImage(image.resize((width,44),Image.Resampling.LANCZOS)))
        super().__init__(parent,image=self.images[0],command=command,bg=background,
                         activebackground=background,bd=0,highlightthickness=0,
                         relief="flat",padx=0,pady=0,cursor="hand2",takefocus=True)
        self.bind("<Enter>",lambda _: self.configure(image=self.images[1]))
        self.bind("<Leave>",lambda _: self.configure(image=self.images[0]))
        self.bind("<FocusIn>",lambda _: self.configure(highlightthickness=1,highlightbackground="#657888"))
        self.bind("<FocusOut>",lambda _: self.configure(highlightthickness=0))


class RoundedProgress(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,height=42,bg="#18191e",highlightthickness=0)
        self.value=0
        self.bind("<Configure>",lambda _: self.draw())

    def set(self,value):
        value=min(1,max(0,float(value or 0)))
        if value!=self.value:
            self.value=value
            self.draw()

    def draw(self):
        width=max(100,self.winfo_width())
        image=Image.new("RGB",(width*2,84),"#18191e")
        draw=ImageDraw.Draw(image)
        draw.text((0,0),"올바른 자세 등록 중 · 잠시 그대로 앉아 주세요" if self.value else "첫 설정: 올바른 자세 등록 → 13초 유지 → 자동 저장",font=font(11),fill="#a0a6b1")
        if self.value:
            draw.text((width*2,0),f"{self.value:.0%}",font=font(11,latin=True),fill="#a8c8e4",anchor="ra")
        draw.rounded_rectangle((0,60,width*2-1,73),radius=6,fill="#303641")
        if self.value:
            draw.rounded_rectangle((0,60,max(13,int((width*2-1)*self.value)),73),radius=6,fill="#a8c8e4")
        self.photo=ImageTk.PhotoImage(image.resize((width,42),Image.Resampling.LANCZOS))
        self.delete("all")
        self.create_image(0,0,anchor="nw",image=self.photo)


class Switch(tk.Button):
    def __init__(self,parent,text,variable,command,background="#25272e",width=300):
        self.variable,self.label,self.disabled=variable,text,False
        self.background,self.width=background,width
        super().__init__(parent,command=lambda:self.toggle(command),bg=background,
                         activebackground=background,bd=0,highlightthickness=0,
                         padx=0,pady=0,relief="flat",cursor="hand2",takefocus=True,anchor="w")
        self.bind("<Configure>", self.resize)
        self.variable_trace = variable.trace_add("write",lambda *_:self.draw())
        self.bind("<Destroy>",self.cleanup,add=True)
        self.bind("<FocusIn>",lambda _:self.configure(highlightthickness=1,highlightbackground="#657888"))
        self.bind("<FocusOut>",lambda _:self.configure(highlightthickness=0))
        self.draw()

    def toggle(self,command):
        if not self.disabled:
            self.variable.set(not self.variable.get())
            command()

    def state(self,states):
        self.disabled="disabled" in states
        self.configure(state="disabled" if self.disabled else "normal")
        self.draw()

    def draw(self):
        image=Image.new("RGB",(self.width*2,72),self.background)
        draw=ImageDraw.Draw(image)
        on=self.variable.get() and not self.disabled
        draw.rounded_rectangle((4,15,76,57),radius=21,fill="#a8c8e4" if on else "#484d58")
        x=38 if on else 9
        draw.ellipse((x,20,x+31,51),fill="#1d2d3e" if on else "#abb1bb")
        text = self.label
        while text and font(12).getlength(text) > self.width*2-104:
            text = text[:-2] + "…"
        draw.text((96,36),text,font=font(12),fill="#757e8b" if self.disabled else "#edf0f4",anchor="lm")
        self.photo=ImageTk.PhotoImage(image.resize((self.width,36),Image.Resampling.LANCZOS))
        self.configure(image=self.photo)

    def resize(self, event):
        width = max(80, event.width - 2 * int(self.cget("highlightthickness")))
        if width != self.width:
            self.width = width
            self.draw()

    def cleanup(self,event):
        if event.widget is self:
            self.variable.trace_remove("write",self.variable_trace)


class SoundSwitch(Switch):
    """On means audible; the persisted preference remains a mute flag."""
    def __init__(self,parent,muted,command,background="#25272e",width=300,compact=False):
        self.muted,self.compact = muted,compact
        self.sound_enabled = tk.BooleanVar(parent,value=not muted.get())
        def changed():
            muted.set(not self.sound_enabled.get())
            command()
        super().__init__(parent,"",self.sound_enabled,changed,background,width)
        self.sound_trace = self.sound_enabled.trace_add("write",self.update_label)
        self.mute_trace = muted.trace_add("write",self.sync)
        self.bind("<Destroy>",self.cleanup_sound,add=True)
        self.update_label()

    def update_label(self,*_):
        self.label = ("소리 켜짐" if self.sound_enabled.get() else "소리 꺼짐")
        if not self.compact:
            self.label += " · 팝업과 소리" if self.sound_enabled.get() else " · 팝업만 표시"
        self.draw()

    def sync(self,*_):
        desired = not self.muted.get()
        if self.sound_enabled.get()!=desired:
            self.sound_enabled.set(desired)

    def cleanup_sound(self,event):
        if event.widget is self:
            self.muted.trace_remove("write",self.mute_trace)
            self.sound_enabled.trace_remove("write",self.sound_trace)


class RoundedCard(tk.Canvas):
    def __init__(self,parent,background="#18191e",fill="#25272e",padding=20,radius=18,auto_height=True):
        # Keep the embedded frame in the initial viewport so its geometry is
        # mapped and can resize the surface to the requested content height.
        super().__init__(parent,bg=background,highlightthickness=0,height=padding*2+100)
        self.background,self.fill,self.padding,self.radius = background,fill,padding,radius
        self.auto_height = auto_height
        self.content = tk.Frame(self,bg=fill)
        self.window = self.create_window((padding,padding),window=self.content,anchor="nw")
        self.content.bind("<Configure>",self.fit)
        self.bind("<Configure>",self.draw)

    def fit(self,event):
        if not self.auto_height:
            return
        height = self.content.winfo_reqheight()+self.padding*2
        if int(self.cget("height"))!=height:
            self.configure(height=height)

    def draw(self,event):
        self.itemconfigure(self.window,width=max(1,event.width-self.padding*2))
        if not self.auto_height:
            self.itemconfigure(self.window,height=max(1,event.height-self.padding*2))
        image = Image.new("RGB",(max(1,event.width)*2,max(1,event.height)*2),self.background)
        ImageDraw.Draw(image).rounded_rectangle((0,0,image.width-1,image.height-1),radius=self.radius*2,fill=self.fill)
        self.photo = ImageTk.PhotoImage(image.resize((max(1,event.width),max(1,event.height)),Image.Resampling.LANCZOS))
        self.delete("background")
        self.create_image(0,0,image=self.photo,anchor="nw",tags="background")
        self.tag_lower("background")


class RoundedScrollbar(tk.Canvas):
    """Shared quiet, rounded scroll thumb with track paging and dragging."""
    def __init__(self,parent,command,background="#18191e"):
        super().__init__(parent,width=12,bg=background,highlightthickness=0)
        self.command,self.first,self.last = command,0.0,1.0
        self.hover,self.drag_anchor = False,None
        self.bind("<Configure>",lambda _:self.draw())
        self.bind("<Enter>",lambda _:self.highlight(True))
        self.bind("<Leave>",lambda _:self.highlight(False))
        self.bind("<Button-1>",self.press)
        self.bind("<B1-Motion>",self.drag)
        self.bind("<ButtonRelease-1>",self.release)

    def set(self,first,last):
        self.first,self.last = float(first),float(last)
        self.draw()

    def bounds(self):
        height = max(1,self.winfo_height()-8)
        span = max(0,min(1,self.last-self.first))
        length = min(height,max(28,height*span))
        travel = height-length
        top = 4+travel*self.first/max(1e-9,1-span)
        return top,top+length,travel,span

    def draw(self):
        self.delete("all")
        if self.last-self.first>=.999:
            return
        top,bottom,_,_ = self.bounds()
        # Thick round-capped line gives a clean pill without native arrows.
        self.create_line(6,top+3,6,bottom-3,width=6,capstyle="round",
                         fill="#7b8797" if self.hover or self.drag_anchor else "#505966")

    def highlight(self,value):
        self.hover=value
        self.draw()

    def press(self,event):
        top,bottom,_,span = self.bounds()
        if span>=.999:
            return
        if top<=event.y<=bottom:
            self.drag_anchor=(event.y,self.first)
        else:
            self.command("scroll",-1 if event.y<top else 1,"pages")
        self.draw()

    def drag(self,event):
        if self.drag_anchor:
            _,_,travel,span = self.bounds()
            y,first = self.drag_anchor
            fraction = first+(event.y-y)/max(1,travel)*(1-span)
            self.command("moveto",max(0,min(1-span,fraction)))

    def release(self,event):
        self.drag_anchor=None
        self.draw()


class RoundedEntry(tk.Canvas):
    def __init__(self,parent,variable,width=280,background="#18191e"):
        super().__init__(parent,bg=background,width=width,height=42,highlightthickness=0)
        self.background = background
        self.entry = tk.Entry(self,textvariable=variable,bg="#30343e",fg="#edf0f4",insertbackground="#edf0f4",
                              relief="flat",bd=0,font=("Segoe UI",11))
        self.window = self.create_window((12,21),window=self.entry,anchor="w")
        self.bind("<Configure>",lambda _:self.draw())
        self.entry.bind("<FocusIn>",lambda _:self.draw())
        self.entry.bind("<FocusOut>",lambda _:self.draw())

    def draw(self):
        width = max(40,self.winfo_width())
        self.itemconfigure(self.window,width=width-24)
        image = Image.new("RGB",(width*2,84),self.background)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1,1,width*2-2,82),radius=20,fill="#30343e",
                               outline="#657888" if self.entry.focus_get() is self.entry else None,width=2)
        self.photo = ImageTk.PhotoImage(image.resize((width,42),Image.Resampling.LANCZOS))
        self.delete("background")
        self.create_image(0,0,image=self.photo,anchor="nw",tags="background")
        self.tag_lower("background")


class ThemedDropdown(tk.Canvas):
    """Rounded field and themed popup, retaining ComboboxSelected events."""
    def __init__(self, parent, variable, values, labels=None):
        super().__init__(parent, height=40, width=280, bg="#25272e",
                         highlightthickness=0, takefocus=True, cursor="hand2")
        self.variable, self.values = variable, tuple(values)
        self.labels = labels or {}
        self.popup = None
        self.active = 0
        self.trace = variable.trace_add("write", lambda *_: self.draw())
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", lambda _: self.toggle())
        for key in ("<space>", "<Return>", "<Down>"):
            self.bind(key, lambda _: self.open())
        self.bind("<FocusIn>", lambda _: self.draw())
        self.bind("<FocusOut>", lambda _: self.draw())
        self.bind("<Destroy>", self.cleanup, add=True)
        self.escape_binding = self.winfo_toplevel().bind("<Escape>", lambda _: self.close(), add=True)

    def __getitem__(self, key):
        return self.values if key == "values" else super().__getitem__(key)

    def cleanup(self, event):
        if event.widget is self:
            self.close()
            self.variable.trace_remove("write", self.trace)
            self.winfo_toplevel().unbind("<Escape>", self.escape_binding)

    def draw(self):
        width = max(80, self.winfo_width())
        image = Image.new("RGB", (width*2, 80), self.cget("bg"))
        draw = ImageDraw.Draw(image)
        focused = self.focus_get() is self or self.popup is not None
        draw.rounded_rectangle((1, 1, width*2-2, 78), radius=20, fill="#30343e",
                               outline="#657888" if focused else "#414753", width=2)
        text = self.labels.get(self.variable.get(), self.variable.get())
        while text and font(11).getlength(text) > width*2-76:
            text = text[:-2] + "…" if not text.endswith("…") else text[:-2] + "…"
        draw.text((24, 40), text, font=font(11), fill="#edf0f4", anchor="lm")
        x = width*2-34
        draw.line((x-7, 35, x, 42, x+7, 35), fill="#a8c8e4", width=3)
        self.photo = ImageTk.PhotoImage(image.resize((width,40), Image.Resampling.LANCZOS))
        self.delete("all")
        self.create_image(0,0,anchor="nw",image=self.photo)

    def toggle(self):
        self.close() if self.popup else self.open()

    def open(self):
        if self.popup or not self.values:
            return
        self.active = self.values.index(self.variable.get()) if self.variable.get() in self.values else 0
        popup = self.popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg="#414753", padx=1, pady=1)
        host = tk.Frame(popup, bg="#25272e", padx=5, pady=5)
        host.pack(fill="both", expand=True)
        self.rows = []
        for i, value in enumerate(self.values):
            label = self.labels.get(value, value)
            row = tk.Button(host, text=label, anchor="w", command=lambda i=i: self.select(i),
                            bg="#25272e", fg="#edf0f4", activebackground="#2e343d",
                            activeforeground="#edf0f4", relief="flat", bd=0,
                            highlightthickness=0, padx=12, pady=9, font=("Segoe UI", 10), cursor="hand2")
            row.pack(fill="x", pady=1)
            row.bind("<Enter>", lambda _, i=i: self.highlight(i))
            self.rows.append(row)
        self.highlight(self.active)
        popup.update_idletasks()
        width = min(self.winfo_screenwidth()-16, max(self.winfo_width(), popup.winfo_reqwidth()))
        height = popup.winfo_reqheight()
        x = min(self.winfo_rootx(), self.winfo_screenwidth()-width-8)
        y = self.winfo_rooty()+self.winfo_height()+5
        if y+height > self.winfo_screenheight()-8:
            y = max(8, self.winfo_rooty()-height-5)
        popup.geometry(f"{width}x{height}+{max(8,x)}+{y}")
        popup.bind("<Escape>", lambda _: self.close())
        popup.bind("<Up>", lambda _: self.highlight((self.active-1) % len(self.values)))
        popup.bind("<Down>", lambda _: self.highlight((self.active+1) % len(self.values)))
        popup.bind("<Return>", lambda _: self.select(self.active))
        popup.bind("<Button-1>", self.outside_click, add=True)
        popup.bind("<FocusOut>", lambda _: self.after_idle(self.check_focus))
        popup.grab_set()
        popup.focus_set()
        self.draw()

    def outside_click(self, event):
        popup = self.popup
        if popup and not (popup.winfo_rootx() <= event.x_root < popup.winfo_rootx()+popup.winfo_width()
                          and popup.winfo_rooty() <= event.y_root < popup.winfo_rooty()+popup.winfo_height()):
            self.close()

    def check_focus(self):
        if self.popup:
            focused = self.focus_get()
            if focused is None or focused.winfo_toplevel() is not self.popup:
                self.close()

    def highlight(self, index):
        self.active = index
        for i, row in enumerate(self.rows):
            selected = self.values[i] == self.variable.get()
            row.configure(bg="#2e343d" if i == index else "#25272e",
                          fg="#a8c8e4" if selected else "#edf0f4")

    def select(self, index):
        self.variable.set(self.values[index])
        self.close()
        self.event_generate("<<ComboboxSelected>>")

    def close(self):
        if self.popup:
            popup, self.popup = self.popup, None
            popup.grab_release()
            popup.destroy()
            if self.winfo_exists():
                self.focus_set()
                self.draw()


def style_titlebar(window):
    # Only our own window's appearance. Standard move/resize/system buttons stay native.
    try:
        import ctypes
        from ctypes import wintypes
        window.update_idletasks()
        user=ctypes.windll.user32
        user.GetParent.argtypes=[wintypes.HWND]
        user.GetParent.restype=wintypes.HWND
        hwnd=user.GetParent(window.winfo_id()) or window.winfo_id()
        setter=ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        setter.restype=ctypes.c_long
        # COLORREF uses little-endian RGB; caption matches #18191e.
        statuses={}
        for attribute,number in ((20,1),(35,0x1e1918),(36,0xf4f0ed),(34,0x1e1918)):
            value=ctypes.c_uint32(number)
            statuses[attribute]=setter(hwnd,attribute,ctypes.byref(value),ctypes.sizeof(value))
        return statuses
    except (AttributeError,OSError):
        return {}
