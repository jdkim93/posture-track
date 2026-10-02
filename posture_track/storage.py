from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import TARGETS


class Recorder:
    """Only confirmed intervals; no camera frames or landmark arrays on disk."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS daily(day TEXT PRIMARY KEY, good REAL DEFAULT 0, bad REAL DEFAULT 0)")
        self.db.execute("CREATE TABLE IF NOT EXISTS intervals(start TEXT, end TEXT, state TEXT, view TEXT, version INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS behavior(start TEXT, end TEXT, name TEXT, version INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS posture_events(id INTEGER PRIMARY KEY, start TEXT, end TEXT, name TEXT, view TEXT, version INTEGER)")
        self.db.execute("CREATE TABLE IF NOT EXISTS record_meta(key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS posture_event_dates ON posture_events(start,end)")
        self.db.commit()
        self.previous = None
        self.active_events = {}
        self.details_started = self.db.execute("SELECT value FROM record_meta WHERE key='details_since'").fetchone() is not None

    def reset(self):
        self.previous = None
        self.active_events.clear()

    def update(self, now: float, wall: datetime, state: str, view: str, version: int,
               max_gap: float, touch=False, allow_write=True, results=None):
        confirmed = frozenset(t.id for t in TARGETS if not t.behavior and results and
                              t.id in results and results[t.id].status in ("bad", "recovering"))
        previous = self.previous
        if not allow_write:
            self.reset()
            return
        self.previous = (now, wall, state, view, version, touch, confirmed)
        if results is not None and not self.details_started:
            self.db.execute("INSERT OR IGNORE INTO record_meta VALUES('details_since',?)", (wall.isoformat(),))
            self.db.commit()
            self.details_started = True
        if previous is None:
            return
        old_now, start, old_state, old_view, old_version, old_touch, old_confirmed = previous
        seconds = now - old_now
        if not (0 < seconds <= max_gap) or old_view != view or old_version != version:
            self.active_events.clear()
            return
        if abs((wall - start).total_seconds() - seconds) > 1:
            self.active_events.clear()
            return  # System clock jumps must not corrupt date allocation.
        # Require both bounds to agree; do not bridge unknown/new transition.
        if old_state == state and state in ("good", "bad"):
            self.db.execute("INSERT INTO intervals VALUES(?,?,?,?,?)", (start.isoformat(), wall.isoformat(), state, view, version))
            cursor = start
            remaining = seconds
            while remaining > 0:
                midnight = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time(), tzinfo=cursor.tzinfo)
                chunk = min(remaining, max(0, (midnight - cursor).total_seconds()))
                if chunk <= 0:
                    break
                day = cursor.date().isoformat()
                self.db.execute("INSERT OR IGNORE INTO daily(day) VALUES(?)", (day,))
                self.db.execute(f"UPDATE daily SET {state}={state}+? WHERE day=?", (chunk, day))
                remaining -= chunk
                cursor = midnight
        if old_touch and touch:
            self.db.execute("INSERT INTO behavior VALUES(?,?,?,?)", (start.isoformat(), wall.isoformat(), "face_touch", version))
        shared = old_confirmed & confirmed
        for name in list(self.active_events):
            if name not in shared:
                del self.active_events[name]
        for name in shared:
            previous_event = self.active_events.get(name)
            if previous_event and previous_event[1] == start.isoformat():
                event_id = previous_event[0]
                self.db.execute("UPDATE posture_events SET end=? WHERE id=?", (wall.isoformat(), event_id))
            else:
                event_id = self.db.execute("INSERT INTO posture_events(start,end,name,view,version) VALUES(?,?,?,?,?)",
                                           (start.isoformat(),wall.isoformat(),name,view,version)).lastrowid
            self.active_events[name] = (event_id,wall.isoformat())
        self.db.commit()

    def summary(self, wall: datetime):
        day = wall.date()
        start = day - timedelta(days=day.weekday())
        month_start = day.replace(day=1)
        all_rows = list(self.db.execute("SELECT day,good,bad FROM daily WHERE day>=? AND day<=? ORDER BY day", (min(start,month_start).isoformat(), day.isoformat())))
        rows = [row for row in all_rows if row[0] >= start.isoformat()]
        today = next(((g, b) for d, g, b in rows if d == day.isoformat()), (0, 0))
        enough = [(d, g, b) for d, g, b in rows if g + b >= 1800]
        total = sum(g + b for _, g, b in enough)
        week = 100 * sum(g for _, g, _ in enough) / total if total else None
        behavior_rows = list(self.db.execute("SELECT start,end,version FROM behavior WHERE substr(start,1,10)=? ORDER BY start", (day.isoformat(),)))
        episodes, touch_seconds, previous_end, previous_version = 0, 0.0, None, None
        for began, end, version in behavior_rows:
            if began != previous_end or version != previous_version:
                episodes += 1
            touch_seconds += max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(began)).total_seconds())
            previous_end, previous_version = end, version
        month_rows = [row for row in all_rows if row[0] >= month_start.isoformat()]
        month_qualified = [(d,g,b) for d,g,b in month_rows if g+b>=1800]
        month_total = sum(g+b for _,g,b in month_qualified)
        month = 100*sum(g for _,g,_ in month_qualified)/month_total if month_total else None
        periods = {}
        since = self.db.execute("SELECT value FROM record_meta WHERE key='details_since'").fetchone()
        for key, first, period_rows, score in (("today", day, [row for row in rows if row[0]==day.isoformat()],
                                               100*today[0]/sum(today) if sum(today) else None),
                                              ("week", start, rows, week), ("month", month_start, month_rows, month)):
            periods[key] = self.details(first, day, wall, period_rows, score)
            periods[key]["details_since"] = since[0] if since else None
        # Keep graph drilldowns in the worker-owned SQLite connection.
        cursor = min(start,month_start)
        while cursor <= day:
            selected = [row for row in all_rows if row[0]==cursor.isoformat()]
            total_day = sum(g+b for _,g,b in selected)
            key = "day:"+cursor.isoformat()
            periods[key] = self.details(cursor,cursor,wall,selected,100*sum(g for _,g,_ in selected)/total_day if total_day else None)
            periods[key]["details_since"] = since[0] if since else None
            cursor += timedelta(days=1)
        cursor = month_start
        while cursor <= day:
            last = min(day,cursor+timedelta(days=6-cursor.weekday()))
            selected = [row for row in month_rows if cursor.isoformat()<=row[0]<=last.isoformat()]
            eligible = [row for row in selected if row[1]+row[2]>=1800]
            total_week = sum(g+b for _,g,b in eligible)
            key = "range_week:"+cursor.isoformat()
            periods[key] = self.details(cursor,last,wall,selected,100*sum(g for _,g,_ in eligible)/total_week if total_week else None)
            periods[key]["details_since"] = since[0] if since else None
            cursor = last+timedelta(days=1)
        return {"today_good": today[0], "today_bad": today[1], "days": rows, "week": week,
                "month": month, "month_days": month_rows, "date": day.isoformat(), "periods": periods,
                "touch_seconds": touch_seconds, "touch_episodes": episodes}

    def details(self, first, last, wall, rows, score):
        began = datetime.combine(first, datetime.min.time(), tzinfo=wall.tzinfo)
        until = datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=wall.tzinfo)
        targets = {t.id: {"name":t.label,"episodes":0,"seconds":0.0} for t in TARGETS if t.available}
        events = self.db.execute("SELECT start,end,name FROM posture_events WHERE substr(end,1,10)>=? AND substr(start,1,10)<=? ORDER BY start",
                                 (first.isoformat(),last.isoformat()))
        for start, end, name in events:
            seconds = (min(datetime.fromisoformat(end),until)-max(datetime.fromisoformat(start),began)).total_seconds()
            if seconds > 0 and name in targets:
                targets[name]["episodes"] += 1
                targets[name]["seconds"] += seconds
        behavior = self.db.execute("SELECT start,end,version FROM behavior WHERE substr(end,1,10)>=? AND substr(start,1,10)<=? ORDER BY start",
                                    (first.isoformat(),last.isoformat()))
        previous_end = previous_version = None
        for start, end, version in behavior:
            seconds = (min(datetime.fromisoformat(end),until)-max(datetime.fromisoformat(start),began)).total_seconds()
            if seconds > 0:
                if start != previous_end or version != previous_version:
                    targets["face_touch"]["episodes"] += 1
                targets["face_touch"]["seconds"] += seconds
            previous_end, previous_version = end, version
        return {"start":first.isoformat(),"end":last.isoformat(),"score":score,
                "good":sum(g for _,g,b in rows),"bad":sum(b for _,g,b in rows),
                "qualified_days":sum(g+b>=1800 for _,g,b in rows),"targets":targets}

    def close(self):
        self.db.commit()
        self.db.close()
