"""Scale-independent face direction cues and sustained screen selection."""
import math
import numpy as np


def eye_direction_features(face,shape):
    if len(face)<=454:
        return {}
    indices=(33,133,263,362,234,454,1)
    points=np.asarray([face[index] for index in indices],dtype=float)
    h,w=shape[:2]
    if not np.all(np.isfinite(points)) or not all(0<=x<w and 0<=y<h for x,y in points):
        return {}
    a,b=(points[0]+points[1])/2,(points[2]+points[3])/2
    vector=b-a
    span=float(np.linalg.norm(vector))
    if span<8:
        return {}
    axis=vector/span
    width=abs(float(np.dot(points[5]-points[4],axis)))
    if width<16 or not .08<span/width<1.15:
        return {}
    offset=float(np.dot(points[6]-(a+b)/2,axis))/width
    if abs(offset)>.8:
        return {}
    return {"screen_eye_span":span/width,"screen_nose_offset":offset}


class ScreenTracker:
    """Ignore a single noisy frame; pause scoring while changing references."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.current=None
        self.candidate=None
        self.started=None
        self.count=0
        self.last=None
        self.signature=None

    def update(self,profiles,observation,signature):
        now=observation.timestamp
        if signature!=self.signature or (self.last is not None and (now<=self.last or now-self.last>12)):
            self.reset()
        self.signature,self.last=signature,now
        profile=profiles.select(observation,signature,self.current)
        if profile is None:
            self.candidate,self.started,self.count=None,None,0
            return None
        identity=profile.profile_id or profile.view
        if identity==self.current:
            self.candidate,self.started,self.count=None,None,0
            return profile
        if identity!=self.candidate:
            self.candidate,self.started,self.count=identity,now,1
        else:
            self.count+=1
        # Acquisition can be quick, but a change to another monitor needs
        # sustained evidence so a posture fluctuation cannot change its zero.
        hold=.3 if self.current is None else .8
        if self.count>=2 and now-self.started>=hold:
            self.current=identity
            self.candidate,self.started,self.count=None,None,0
            return profile
        return None
