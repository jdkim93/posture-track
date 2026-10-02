"""Local, antialiased score dashboard. No screen capture or external assets."""
from datetime import date, timedelta
import calendar
import math
from functools import lru_cache
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageChops

BACKGROUND = "#18191e"
INK, MUTED, ACCENT = "#edf0f4", "#a0a6b1", "#d0b28d"


def format_duration(seconds):
    seconds = max(0,round(seconds))
    if seconds >= 3600:
        return f"{seconds//3600}시간 {seconds%3600//60}분"
    if seconds >= 60:
        return f"{seconds//60}분 {seconds%60}초"
    return f"{seconds}초"


@lru_cache(maxsize=64)
def font(size, bold=False, latin=False):
    if size < 20:
        size += 2
    directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    name = ("segoeuisl.ttf" if size >= 30 else "segoeuib.ttf" if bold else "segoeui.ttf") if latin else ("malgunbd.ttf" if bold else "malgun.ttf")
    return ImageFont.truetype(str(directory / name), size * 2)


def dashboard_regions(width, height):
    width, height = max(800,width), max(560,height)
    x, right = 44, width-14
    bottom = 270 if height < 630 else 302
    y = bottom+18
    return {"today":(14,78,right,bottom), "week":(x,y+58,x+190,y+125),
            "month":(x+230,y+58,x+420,y+125),
            "switch_week":(x+235,y+16,x+315,y+46),
            "switch_month":(x+325,y+16,x+405,y+46),
            "plot":(x,y+135,right-30,height-40)}


def dashboard_bars(width, height, stats, period="week", demo=False):
    width, height = max(800,width), max(560,height)
    today = date.fromisoformat(stats.get("date",date.today().isoformat()))
    first = today.replace(day=1) if period == "month" else today-timedelta(days=today.weekday())
    last = today.replace(day=calendar.monthrange(today.year,today.month)[1]) if period == "month" else first+timedelta(days=6)
    groups = []
    cursor = first
    while cursor <= last:
        end = min(last,cursor+timedelta(days=6-cursor.weekday())) if period == "month" else cursor
        groups.append((cursor,end))
        cursor = end+timedelta(days=1)
    rows = stats.get("month_days" if period == "month" else "days",[])
    y = (270 if height<630 else 302)+18
    base = height-77
    plot_h = max(30,base-y-(140 if height<630 else 160))
    bars = []
    for i,(first,last) in enumerate(groups):
        selected = [(g,b) for day,g,b in rows if first.isoformat()<=day<=last.isoformat()]
        # Weekly bars use the same eligible-day weighting as weekly details.
        eligible = [(g,b) for g,b in selected if period != "month" or g+b>=1800]
        g,b = sum(a for a,_ in eligible),sum(b for _,b in eligible)
        score = 100*g/(g+b) if g+b and not demo else None
        xx = 109+i*(width-188)/max(1,len(groups)-1)
        yy = base-(score or 0)/100*plot_h
        key = ("range_week:" if period=="month" else "day:")+first.isoformat()
        bars.append({"key":key,"first":first,"last":last,"x":xx,"y":yy,"base":base,
                     "score":score,"qualified":g+b>=1800,"bounds":(xx-24,min(yy,base-8)-8,xx+24,base+39)})
    return bars


def dashboard_hit(width,height,stats,period,x,y):
    regions = dashboard_regions(width,height)
    for key in ("switch_week","switch_month"):
        a,b,c,d = regions[key]
        if a<=x<=c and b<=y<=d:
            return key
    for bar in dashboard_bars(width,height,stats,period):
        a,b,c,d = bar["bounds"]
        if a<=x<=c and b<=y<=d:
            return bar["key"]
    for key in ("today",):
        a,b,c,d = regions[key]
        if a<=x<=c and b<=y<=d:
            return key
    if 14<=x<=max(800,width)-14 and regions["today"][3]+18<=y<=max(560,height)-14:
        return "period"
    return None


def render_dashboard(width, height, stats, demo=False, period="week", hover=None):
    width, height = max(800, width), max(560, height)
    image = Image.new("RGB", (width * 2, height * 2), BACKGROUND)
    d = ImageDraw.Draw(image)
    def box(b):
        return tuple(round(v * 2) for v in b)
    def text(x, y, value, size=14, color=INK, bold=False, anchor="la", latin=False):
        d.text((x*2,y*2), value, fill=color, font=font(size,bold,latin), anchor=anchor)
    def line(b, color, thickness=1):
        d.line(box(b), fill=color, width=thickness*2)
    def rounded(b, color, radius=22):
        d.rounded_rectangle(box(b), radius=radius*2, fill=color)
    today = date.fromisoformat(stats["date"]) if stats.get("date") else date.today()
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(days=6)
    pad, right = 14, width-14
    text(pad, 18, "내 자세 리포트", 27)
    text(right, 28, f"{today.month}월 {today.day}일  {'월화수목금토일'[today.weekday()]}요일", 13, MUTED, anchor="ra")
    # One focal card: the ring reads as a score rather than a progress goal.
    top, bottom = 78, 270 if height < 630 else 302
    rounded((pad,top,right,bottom),"#2a506a",26)
    gradient = Image.new("RGB", image.size, BACKGROUND)
    gd = ImageDraw.Draw(gradient)
    for yy in range(top*2,bottom*2+1):
        t=(yy-top*2)/((bottom-top)*2)
        color=tuple(round(a+(b-a)*t) for a,b in zip((51,100,133),(25,37,53)))
        gd.line((pad*2,yy,right*2,yy),fill=color)
    hero_mask=Image.new("L",image.size)
    ImageDraw.Draw(hero_mask).rounded_rectangle(box((pad,top,right,bottom)),radius=52,fill=255)
    image.paste(gradient,(0,0),hero_mask)
    d=ImageDraw.Draw(image)
    # Low-contrast concentric curves add depth without downloaded artwork.
    overlay = Image.new("RGBA", image.size)
    od = ImageDraw.Draw(overlay)
    for radius in (200,240,280):
        od.arc(box((right-radius-35,top-radius+60,right+radius-35,top+radius+60)),75,250,fill=(204,227,207,18),width=2)
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).rounded_rectangle(box((pad,top,right,bottom)),radius=52,fill=255)
    overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"),mask))
    image.paste(overlay,(0,0),overlay)
    d = ImageDraw.Draw(image)
    total = stats.get("today_good",0)+stats.get("today_bad",0)
    value = 100*stats.get("today_good",0)/total if total and not demo else None
    x = pad+34
    text(x,top+29,"TODAY / POSTURE",12,"#b7cddd",latin=True)
    text(x,top+60,"오늘의 자세 점수",26,"#f5f7fa")
    text(x,top+112,"카메라를 켜면 오늘의 기록이 쌓입니다." if value is None else "점수 그래프를 클릭하면 이탈 기록을 볼 수 있어요.",14,"#dce5ee")
    text(x,top+(146 if height<630 else 155),f"유효 관측  {total/60:.1f}분",13,"#dce5ee")
    hint = "데모 · 실제 기록 없음" if demo else "아직 기록이 없어요" if not total else "30분 미만 · 잠정 점수" if total<1800 else "오늘의 관측을 반영한 점수"
    text(x,top+(171 if height < 630 else 184),hint,11,"#b7cddd")
    cx, cy, r = right-145, top+112, 79
    def gauge(end,color):
        if end<=195:
            return
        points = [(cx+r*math.cos(math.radians(a)),cy+18+r*math.sin(math.radians(a)))
                  for a in [195+(end-195)*i/200 for i in range(201)]]
        d.line([tuple(round(v*2) for v in point) for point in points],fill=color,width=18,joint="curve")
        for px,py in (points[0],points[-1]):
            d.ellipse(box((px-4.5,py-4.5,px+4.5,py+4.5)),fill=color)
    gauge(345,"#68839a")
    if value is not None:
        gauge(195+value*1.5,"#edcca5")
    text(cx,cy-20,f"{value:.0f}" if value is not None else "—",58,"#f5f7fa",anchor="ma",latin=True)
    text(cx,cy+55,"/ 100",12,"#b7cddd",anchor="ma",latin=True)
    y, card_bottom = bottom+18, height-14
    rounded((pad,y,right,card_bottom),"#25272e",24)
    if hover == "today":
        d.rounded_rectangle(box((pad,top,right,bottom)),radius=52,outline="#547087",width=2)
    elif hover in ("period","week","month"):
        d.rounded_rectangle(box((pad,y,right,card_bottom)),radius=48,outline="#414a56",width=2)
    x = pad+30
    text(x,y+23,"기간별 자세 점수",21,bold=True)
    regions = dashboard_regions(width,height)
    for key, label in (("week","이번 주"),("month","이번 달")):
        a,b,c,e = regions["switch_"+key]
        rounded((a,b,c,e),"#3d4b59" if hover=="switch_"+key else "#394958" if key==period else "#30343e",12)
        text((a+c)/2,b+6,label,11,INK if key==period else MUTED,anchor="ma")
    date_label = f"{today.year}.{today.month}" if period=="month" else f"{monday.month}.{monday.day} – {end.month}.{end.day}"
    text(right-30,y+29,date_label,12,MUTED,anchor="ra",latin=True)
    rows = {day:(g,b) for day,g,b in stats.get("month_days" if period=="month" else "days",[])}
    qualified = [100*g/(g+b) for g,b in rows.values() if g+b>=1800]
    week = stats.get("week") if not demo else None
    text(x,y+65,f"{week:.0f}" if week is not None else "—",38,bold=True,latin=True)
    text(x+85,y+81,"주간 평균",12,MUTED)
    month = stats.get("month") if not demo else None
    text(x+230,y+65,f"{month:.0f}" if month is not None else "—",38,bold=True,latin=True)
    text(x+315,y+81,"월간 평균",12,MUTED)
    text(right-225,y+70,"최저",11,MUTED)
    text(right-225,y+91,f"{min(qualified):.0f}" if qualified and not demo else "—",22,ACCENT,latin=True)
    text(right-110,y+70,"최고",11,MUTED)
    text(right-110,y+91,f"{max(qualified):.0f}" if qualified and not demo else "—",22,ACCENT,latin=True)
    line((x,y+131,right-30,y+131),"#353840")
    plot_top, base = y+(140 if height < 630 else 160), card_bottom-63
    plot_h = max(30,base-plot_top)
    for level in (0,50,100):
        yy=base-level/100*plot_h
        line((x+30,yy,right-30,yy),"#34373f")
        text(x+12,yy,str(level),9,"#858d9a",anchor="rm",latin=True)
    for i,bar in enumerate(dashboard_bars(width,height,stats,period,demo)):
        day,xx,yy,score = bar["first"],bar["x"],bar["y"],bar["score"]
        hovered = hover == bar["key"]
        if hovered:
            rounded(bar["bounds"],"#2b3038",12)
        if score is not None:
            color=("#d8bc9a" if bar["qualified"] else "#c0aa8a") if hovered else ACCENT if bar["qualified"] else "#b8a07a"
            half = 10
            rounded((xx-half,min(yy,base-3),xx+half,base+1),color,half)
            text(xx,yy-19,f"{score:.0f}"+("*" if not bar["qualified"] else ""),11,color,anchor="ma",latin=True)
        else:
            d.ellipse(box((xx-2,base-3,xx+2,base+1)),fill="#525b67")
        current = day<=today<=bar["last"]
        if current and not hovered:
            rounded((xx-26,base+12,xx+26,base+36),"#394958",12)
        label = f"{day.day}–{bar['last'].day}일" if period=="month" else f"{'월화수목금토일'[i]} {day.day}"
        text(xx,base+15,label,11,INK if current or hovered else MUTED,anchor="ma")
    text(right-30,card_bottom-21,"막대: "+("주별" if period=="month" else "날짜별")+" 상세 · 카드: 기간 상세 · 30분 이상 측정한 날만 평균 집계 · * 잠정",10,MUTED,anchor="ra")
    return image.resize((width,height),Image.Resampling.LANCZOS)
