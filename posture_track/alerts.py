"""Bounded fast sampling and confirmed notification recovery."""


class AlertRecovery:
    INTERVAL = .2
    VISIBLE_INTERVAL = .5
    BOOST_SECONDS = 20

    def __init__(self):
        self.active = {}
        self.until = 0

    def trigger(self, kind, now):
        self.active[kind] = None
        self.until = now+self.BOOST_SECONDS

    def fast(self, now):
        return bool(self.active)

    def interval(self, now, normal):
        if not self.active:
            return normal
        return min(normal,self.INTERVAL if now<self.until else self.VISIBLE_INTERVAL)

    def update(self, now, state, results):
        recovered = []
        for kind, began in list(self.active.items()):
            if kind == "touch":
                # A proximity alert belongs only to its continuous confirmed
                # episode. Lost tracking ends the alert, without claiming that
                # the hand has moved away or recording an unknown frame as good.
                if getattr(results.get("face_touch"),"status",None)!="bad":
                    recovered.append(kind)
                    del self.active[kind]
                continue
            good = state == "good"
            if not good:
                self.active[kind] = None
            elif began is None:
                self.active[kind] = now
            elif now-began>=.2:
                recovered.append(kind)
                del self.active[kind]
        return recovered

    def reset(self):
        kinds = list(self.active)
        self.active.clear()
        self.until = 0
        return kinds
