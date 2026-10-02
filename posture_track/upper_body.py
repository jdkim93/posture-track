"""Upper-body posture change proxies; no invisible hip or spine inference."""
import math
import numpy as np
from .config import POSTURE_SENSITIVITY


def upper_body_metrics(pose, face, world, shape, view, pitch, yaw):
    from .vision import valid
    h,w = shape[:2]
    if len(face)<=454 or not all(valid(pose,i,w,h) for i in (11,12)):
        return {}
    points = np.asarray([face[10],face[152]],dtype=float)
    if not np.all(np.isfinite(points)) or not all(0<=x<w and 0<=y<h for x,y in points):
        return {}
    scale = float(np.linalg.norm(points[0]-points[1]))
    if not h*.05<scale<h*.8 or not view in ("front","oblique_left","oblique_right"):
        return {}
    left,right = np.asarray(pose[11][:2]),np.asarray(pose[12][:2])
    span = float(np.linalg.norm(right-left))
    if span<w*.08:
        return {}
    eye_points = np.asarray([face[i] for i in (33,133,263,362)],dtype=float)
    if not np.all(np.isfinite(eye_points)) or not all(0<=x<w and 0<=y<h for x,y in eye_points):
        return {}
    eye_scale = float(np.linalg.norm((eye_points[0]+eye_points[1]-eye_points[2]-eye_points[3])/2))
    if not scale*.15<eye_scale<scale*1.2:
        return {}
    normal = np.array((-(right-left)[1],(right-left)[0]))/span
    if normal[1]<0:
        normal = -normal
    shoulders = (left+right)/2
    metrics = {"upper_span":span/eye_scale,"upper_scale":scale,"upper_eye_scale":eye_scale,
               "upper_pitch":pitch,"upper_yaw":yaw}
    if len(world)>12:
        across=np.asarray(world[12],dtype=float)-np.asarray(world[11],dtype=float)
        if across.shape==(3,) and np.all(np.isfinite(across)) and .15<float(np.linalg.norm(across))<.8:
            metrics['upper_body_yaw']=(math.degrees(math.atan2(across[2],across[0]))+90)%180-90
            world_span=float(np.linalg.norm(across))
            forward=np.array((across[2],0,-across[0]))
            length=float(np.linalg.norm(forward))
            if length>world_span*.7:
                forward/=length
                if forward[2]>0:
                    forward=-forward
                center=(np.asarray(world[11])+np.asarray(world[12]))/2
                for index,key in ((7,'upper_neck_left_forward'),(8,'upper_neck_right_forward')):
                    if valid(pose,index,w,h):
                        ear=np.asarray(world[index],dtype=float)
                        if ear.shape==(3,) and np.all(np.isfinite(ear)):
                            value=float(np.dot(ear-center,forward))/world_span
                            if abs(value)<2:
                                metrics[key]=value
    ears_visible=all(valid(pose,i,w,h) for i in (7,8))
    if ears_visible:
        ears = (np.asarray(pose[7][:2])+pose[8][:2])/2
        gap = float(np.dot(shoulders-ears,normal))/scale
        if .05<gap<2:
            metrics['upper_gap']=gap
    # Relative depth cancels the world-landmark hip origin. Never use depth alone.
    if ears_visible and len(world)>12:
        joints = np.asarray([world[i] for i in (7,8,11,12)],dtype=float)
        if joints.shape==(4,3) and np.all(np.isfinite(joints)):
            across = joints[3]-joints[2]
            world_span = float(np.linalg.norm(across))
            forward = np.array((across[2],0,-across[0]))
            length = float(np.linalg.norm(forward))
            if .15<world_span<.8 and length>world_span*.7:
                forward /= length
                if forward[2]>0:
                    forward = -forward
                depth = float(np.dot((joints[2]+joints[3]-joints[0]-joints[1])/2,forward))/world_span
                if abs(depth)<2:
                    metrics["upper_depth"] = depth
    return metrics


def upper_body_change(metrics, baseline, sensitive=False):
    factor, noise_factor = POSTURE_SENSITIVITY['sensitive' if sensitive else 'standard']
    required = ("upper_span","upper_scale","upper_eye_scale","upper_pitch","upper_yaw")
    if any(key not in metrics or not math.isfinite(metrics[key]) for key in required):
        return None,"얼굴과 양쪽 어깨가 화면 안에 보여야 합니다",False
    if any(key not in baseline.values for key in required):
        return None,"어깨 기준이 저장되지 않았어요. 얼굴과 양쪽 어깨가 보이도록 ‘올바른 자세 등록’을 다시 눌러 주세요",True
    base = baseline.values
    if any(base[key]<=0 or metrics[key]<=0 for key in ("upper_scale","upper_eye_scale","upper_span")):
        return None,"얼굴과 어깨 크기를 다시 확인하고 있어요",False
    eye_zoom = metrics["upper_eye_scale"]/base["upper_eye_scale"]
    face_zoom = metrics["upper_scale"]/base["upper_scale"]
    shoulder_zoom = metrics["upper_span"]*metrics["upper_eye_scale"]/(base["upper_span"]*base["upper_eye_scale"])
    body_projection=1
    body_width_usable=True
    if 'upper_body_yaw' in metrics and 'upper_body_yaw' in base:
        body_cos=math.cos(math.radians(metrics['upper_body_yaw']))
        base_body_cos=math.cos(math.radians(base['upper_body_yaw']))
        if all(math.isfinite(v) and v>.45 for v in (body_cos,base_body_cos)):
            body_projection=body_cos/base_body_cos
            shoulder_zoom/=body_projection
        else:
            # An uncertain world shoulder direction disables width/depth
            # compensation, not independently visible head/neck evidence.
            body_width_usable=False
    # Forward leaning deliberately enlarges the head relative to the shoulders.
    # Uniform camera-distance changes cancel in the normalized measurements.
    # Reserve rejection for extreme scale or inconsistent face geometry.
    if not .45<eye_zoom<2.2 or not .45<shoulder_zoom<2.2:
        return None,"얼굴과 어깨가 모두 잘 보이도록 앉아 주세요",False
    pitch_change=abs(metrics["upper_pitch"]-base["upper_pitch"])
    if abs(metrics["upper_yaw"]-base["upper_yaw"])>25 or pitch_change>45:
        return None,"같은 방향을 바라보면 어깨 자세를 확인할 수 있어요",False
    # Eyes appear closer together when turning the head. Compensate moderate
    # horizontal projection changes within the selected screen's reference,
    # instead of discarding every observation over 12 degrees from its center.
    current_cos=math.cos(math.radians(metrics["upper_yaw"]))
    baseline_cos=math.cos(math.radians(base["upper_yaw"]))
    if min(current_cos,baseline_cos)<.45:
        return None,"얼굴을 조금 더 보이면 어깨 자세를 확인할 수 있어요",False
    corrected_eye_zoom=eye_zoom*baseline_cos/current_cos
    if not .7<face_zoom/corrected_eye_zoom<1.4:
        return None,"얼굴과 어깨가 모두 잘 보이도록 앉아 주세요",False
    metrics=dict(metrics)
    metrics["upper_span"]*=current_cos/baseline_cos/body_projection
    def change(key,threshold,lower=False):
        delta = base[key]-metrics[key] if lower else metrics[key]-base[key]
        return max(0,delta)/max(threshold*factor,noise_factor*baseline.noise.get(key,0))
    gap_available='upper_gap' in metrics and 'upper_gap' in base and math.isfinite(metrics['upper_gap']) and math.isfinite(base['upper_gap'])
    gap = change("upper_gap",max(.045,base['upper_gap']*.065),True) if pitch_change<=25 and gap_available else 0
    span = change("upper_span",max(.12,base["upper_span"]*.08),True) if body_width_usable else 0
    # Both visible compression cues, or forward shoulder movement corroborated
    # by at least one visible cue. A depth estimate by itself is insufficient.
    scores=[(min(gap,span),"목·어깨 간격과 어깨 폭이 함께 줄었어요")]
    # A user can keep their chin raised toward the screen while slouching.
    # Neck compression then stays small. Compare BOTH facial height and eye
    # spacing with shoulders, allowing this visible approach without requiring
    # the neck-gap signal or uncertain world depth to cross a threshold too.
    face_ratio=face_zoom/shoulder_zoom
    face_limit=max(.09*factor,noise_factor*(baseline.noise.get("upper_scale",0)/base["upper_scale"]+
                         baseline.noise.get("upper_span",0)/base["upper_span"]))
    face_approach=max(0,face_ratio-1)/face_limit
    scores.append((min(span,face_approach),"얼굴이 어깨보다 가까워지거나 어깨 폭이 줄었어요"))
    # Shoulder-derived world yaw can change as shoulders round, not just as
    # the torso rotates. Its width correction must not erase independent
    # visible neck compression and matching face/eye enlargement.
    head_approach=min(max(0,face_zoom-1),max(0,corrected_eye_zoom-1))/max(
        .05*factor,noise_factor*baseline.noise.get('upper_scale',0)/base['upper_scale'],
        noise_factor*baseline.noise.get('upper_eye_scale',0)/base['upper_eye_scale'])
    scores.append((min(gap,head_approach),"목·어깨 간격이 줄고 얼굴이 앞으로 가까워졌어요"))
    if body_width_usable and pitch_change<=25 and "upper_depth" in base and "upper_depth" in metrics and all(math.isfinite(values['upper_depth']) for values in (base,metrics)):
        # Ears moving forward relative to shoulders (head-forward slouch) and
        # shoulders moving forward relative to ears can have opposite signs.
        # Either still needs a corroborating visible compression cue.
        depth=abs(metrics["upper_depth"]-base["upper_depth"])/max(.06*factor,noise_factor*baseline.noise.get("upper_depth",0))
        scores.append((min(depth,max(gap,span,head_approach)),"귀·어깨의 앞뒤 관계와 상체 비율이 달라졌어요"))
    score,reason=max(scores,key=lambda item:item[0])
    return score,reason if score>=.5 else "등록한 자세와 얼굴·어깨 비율을 비교합니다",False


def forward_neck_change(metrics, baseline, sensitive=False):
    """Body-frame ear protraction plus visible scale/neck corroboration."""
    required=('upper_body_yaw','upper_span','upper_scale','upper_eye_scale','upper_pitch','upper_yaw')
    if any(key not in metrics or not math.isfinite(metrics[key]) for key in required):
        return None,"귀·얼굴과 양쪽 어깨가 보이면 목의 앞뒤 위치를 비교합니다",False
    if any(key not in baseline.values or not math.isfinite(baseline.values[key]) for key in required):
        return None,"목·몸통 방향 기준을 추가하려면 이 화면의 올바른 자세를 다시 등록해 주세요",True
    base=baseline.values
    if min(math.cos(math.radians(values['upper_body_yaw'])) for values in (metrics,base))<=.45:
        return None,"양쪽 어깨가 더 보이면 목의 앞뒤 위치를 비교할 수 있어요",False
    # Reuse the same projection and scale validity checks as upper-body posture.
    checked,reason,needs_registration=upper_body_change(metrics,baseline)
    if checked is None:
        return None,reason,needs_registration
    body_projection=math.cos(math.radians(metrics['upper_body_yaw']))/math.cos(math.radians(base['upper_body_yaw']))
    shoulder_zoom=metrics['upper_span']*metrics['upper_eye_scale']/(base['upper_span']*base['upper_eye_scale'])/body_projection
    face_ratio=(metrics['upper_scale']/base['upper_scale'])/shoulder_zoom
    eye_ratio=(metrics['upper_eye_scale']/base['upper_eye_scale'])*math.cos(math.radians(base['upper_yaw']))/math.cos(math.radians(metrics['upper_yaw']))/shoulder_zoom
    # Ear midpoint moves forward relative to the shoulders; body rotation is
    # removed when projecting both joints onto the shoulder-derived forward axis.
    ears=[key for key in ('upper_neck_left_forward','upper_neck_right_forward') if key in metrics and key in base
          and math.isfinite(metrics[key]) and math.isfinite(base[key])]
    if ears:
        if len(ears)==1 and (abs(metrics['upper_yaw']-base['upper_yaw'])>10 or abs(metrics['upper_body_yaw']-base['upper_body_yaw'])>10):
            return None,"한쪽 귀만 보일 때는 등록한 머리·몸통 방향에서 목 위치를 확인합니다",False
        delta=sum(metrics[key]-base[key] for key in ears)/len(ears)
        noise=sum(baseline.noise.get(key,0) for key in ears)/len(ears)
    elif all('upper_depth' in values and math.isfinite(values['upper_depth']) for values in (metrics,base)):
        delta=base['upper_depth']-metrics['upper_depth']
        noise=baseline.noise.get('upper_depth',0)
    else:
        if not any(key in base for key in ('upper_depth','upper_neck_left_forward','upper_neck_right_forward')):
            return None,"목 위치 기준이 없어요. 귀와 어깨가 보이도록 이 화면의 올바른 자세를 다시 등록해 주세요",True
        return None,"등록 때와 같은 귀가 보이면 목의 앞뒤 위치를 비교합니다",False
    factor, noise_factor=POSTURE_SENSITIVITY['sensitive' if sensitive else 'standard']
    protraction=max(0,delta)/max(.08*factor,noise_factor*noise)
    visible_approach=min(max(0,face_ratio-1),max(0,eye_ratio-1))/max(.04*factor,noise_factor*baseline.noise.get('upper_span',0)/base['upper_span'])
    gap=0
    if abs(metrics['upper_pitch']-base['upper_pitch'])<15 and all('upper_gap' in values and math.isfinite(values['upper_gap']) for values in (metrics,base)):
        gap=max(0,base['upper_gap']-metrics['upper_gap'])/max(.05*factor,noise_factor*baseline.noise.get('upper_gap',0))
    return min(protraction,max(visible_approach,gap)),"어깨에 대한 머리의 전방 이동을 비교합니다",False
