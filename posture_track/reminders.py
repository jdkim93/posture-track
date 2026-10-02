"""Persistent local reminders, independent of webcam observation."""
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import uuid

from .config import atomic_json


@dataclass
class Reminder:
    id: str
    title: str
    mode: str = "interval"
    interval_minutes: int = 60
    time: str = "09:00"
    enabled: bool = False
    muted: bool = True
    next_due: str | None = None

    def validate(self):
        if not isinstance(self.id,str) or not self.id or not isinstance(self.title,str) or not self.title.strip() or len(self.title)>40:
            raise ValueError("알림 이름은 1~40자로 입력해 주세요.")
        if self.mode not in ("interval","daily"):
            raise ValueError("알림 방식을 선택해 주세요.")
        if type(self.interval_minutes) is not int or not 1<=self.interval_minutes<=10080:
            raise ValueError("반복 간격은 1분~168시간으로 설정해 주세요.")
        try:
            hour,minute = map(int,self.time.split(":"))
            if not 0<=hour<=23 or not 0<=minute<=59 or self.time!=f"{hour:02}:{minute:02}":
                raise ValueError()
        except (ValueError,AttributeError):
            raise ValueError("시각은 09:00처럼 24시간 형식으로 입력해 주세요.") from None
        if type(self.enabled) is not bool or type(self.muted) is not bool:
            raise ValueError("알림 상태가 올바르지 않습니다.")
        if self.next_due:
            due = datetime.fromisoformat(self.next_due)
            if due.tzinfo is None:
                raise ValueError("알림 시각에 시간대가 필요합니다.")

    def schedule(self,now):
        if not self.enabled:
            self.next_due = None
        elif self.mode=="interval":
            self.next_due = (now+timedelta(minutes=self.interval_minutes)).isoformat()
        else:
            hour,minute = map(int,self.time.split(":"))
            due = now.replace(hour=hour,minute=minute,second=0,microsecond=0)
            if due<=now:
                due += timedelta(days=1)
            self.next_due = due.isoformat()

    def description(self):
        if self.mode=="daily":
            return "매일 "+self.time
        hours,minutes = divmod(self.interval_minutes,60)
        return ((f"{hours}시간" if hours else "")+(f" {minutes}분" if minutes and hours else f"{minutes}분" if minutes else ""))+"마다"


class ReminderBook:
    def __init__(self,path:Path):
        self.path = path
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema")!=1 or not isinstance(data.get("items"),list):
                raise ValueError("맞춤 알림 설정 파일을 읽을 수 없습니다.")
            self.items = [Reminder(**item) for item in data["items"]]
            for item in self.items:
                item.validate()
            if len({item.id for item in self.items})!=len(self.items):
                raise ValueError("알림 ID가 중복되어 있습니다.")
        else:
            self.items = [Reminder("water","물 마시기",interval_minutes=120),
                          Reminder("stretch","스트레칭",interval_minutes=60)]
            self.save()

    def save(self):
        atomic_json(self.path,{"schema":1,"items":[asdict(item) for item in self.items]})

    def upsert(self,item,now):
        item = replace(item,title=item.title.strip())
        item.validate()
        old = next((old for old in self.items if old.id==item.id),None)
        if old and (old.mode,old.interval_minutes,old.time,old.enabled)==(item.mode,item.interval_minutes,item.time,item.enabled):
            item.next_due = old.next_due
        else:
            item.schedule(now)
        if item.enabled and not item.next_due:
            item.schedule(now)
        updated = [item if old.id==item.id else old for old in self.items]
        if old is None:
            updated.append(item)
        atomic_json(self.path,{"schema":1,"items":[asdict(old) for old in updated]})
        self.items = updated

    def remove(self,identity):
        updated = [item for item in self.items if item.id!=identity]
        atomic_json(self.path,{"schema":1,"items":[asdict(item) for item in updated]})
        self.items = updated

    def due(self,now):
        fired,updated = [],[]
        for original in self.items:
            item = replace(original)
            if not item.enabled:
                updated.append(item)
                continue
            if not item.next_due:
                item.schedule(now)
            elif datetime.fromisoformat(item.next_due)<=now:
                fired.append(replace(item))
                if item.mode=="daily":
                    item.schedule(now)
                else:
                    previous = datetime.fromisoformat(item.next_due)
                    step = timedelta(minutes=item.interval_minutes)
                    item.next_due = (previous+step*(int((now-previous)//step)+1)).isoformat()
            updated.append(item)
        if updated!=self.items:
            # Persist before delivering, preventing duplicate alarms on restart.
            atomic_json(self.path,{"schema":1,"items":[asdict(item) for item in updated]})
            self.items = updated
        return fired


def new_reminder():
    return Reminder(uuid.uuid4().hex,"",enabled=True)
