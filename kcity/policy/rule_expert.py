"""B0 candidate: deterministic memoryless OBS73 -> acceleration/lane request.

No TraCI handle, full State, detected list, future signal or hidden state is
accepted. SUMO safety still participates in the resulting vehicle behavior.
"""
from copy import deepcopy
import math
import numpy as np

EXPERT_ID='KC-B0-OBS73-v1-candidate'
DEFAULT_EXPERT=dict(speed_cap_mps=8.33,cruise_mps=7.5,accel_mps2=2.,decel_mps2=4.5,
    following_decel_mps2=3.,time_headway_s=1.5,min_gap_m=3.,
    lane_front_gap_m=8.,lane_rear_gap_m=8.,lane_time_gap_s=1.5,stop_buffer_m=2.)


class KCityRuleExpert:
    def __init__(self,config=None):
        self.config=deepcopy(DEFAULT_EXPERT if config is None else config)
        if set(self.config)!=set(DEFAULT_EXPERT) or any(not math.isfinite(v) or v<=0 for v in self.config.values()):
            raise ValueError('Invalid expert configuration')

    def decision(self,observation):
        o=np.asarray(observation,dtype=np.float32)
        if o.shape!=(73,) or not np.isfinite(o).all() or (np.abs(o)>1).any():
            raise ValueError('Expert requires bounded finite OBS73')
        c=self.config;v=float(o[0])*c['speed_cap_mps']
        permitted=not bool(o[51]) and o[52]<=1e-9
        mask=[bool(permitted and o[42]>.5),True,bool(permitted and o[44]>.5)]
        requested=0;reasons=[]
        required=bool(o[71]>.5 and o[69]<.5 and not o[51])
        if required:
            for cmd,k,connection,category in [(1,1,68,0),(-1,3,70,2)]:
                if not mask[category] or o[connection]<.5:continue
                front=float(o[1+4*k])*100;rear=-float(o[3+4*k])*50
                rear_speed=max(0.,v+float(o[4+4*k])*c['speed_cap_mps'])
                front_ok=not o[31+2*k] or front>=max(c['lane_front_gap_m'],v*c['lane_time_gap_s'])
                rear_ok=not o[32+2*k] or rear>=max(c['lane_rear_gap_m'],rear_speed*c['lane_time_gap_s'])
                if front_ok and rear_ok:requested=cmd;reasons.append('route_lane');break
        target=max(.1,min(c['cruise_mps'],float(o[72])*c['speed_cap_mps']))
        a=c['accel_mps2']*(1-(v/target)**4)
        if o[35]>.5:
            gap=max(.1,float(o[9])*100)
            closing=-float(o[10])*c['speed_cap_mps']
            desired=c['min_gap_m']+max(0.,v*c['time_headway_s']+v*closing/(2*math.sqrt(c['accel_mps2']*c['following_decel_mps2'])))
            a-=c['accel_mps2']*(desired/gap)**2
            reasons.append('following')
        stops=[]
        if o[54]>.5 and (o[56]>.5 or o[57]>.5):
            stops.append(max(0.,float(o[55])*100-c['stop_buffer_m']));reasons.append('signal_stop')
        if required and not requested:
            stops.append(max(0.,float(o[49])*100-c['stop_buffer_m']));reasons.append('route_lane_wait')
        if o[60]>.5:
            # Memoryless candidate only: no claim of a certified dwell/priority
            # rule. A/B/C currently have no allway_stop on the assigned route.
            distance=float(o[61])*100
            if not (distance<1. and v<.15):stops.append(max(0.,distance-.5))
            else:target=min(target,.8);a=min(a,c['accel_mps2']*(1-(v/target)**4))
            reasons.append('stop_rule_candidate')
        for distance in stops:
            safe_speed=math.sqrt(2*c['following_decel_mps2']*distance)
            a=min(a,(safe_speed-v)/.5)
        a=float(np.clip(a,-c['decel_mps2'],c['accel_mps2']))
        normalized=a/(c['accel_mps2'] if a>=0 else c['decel_mps2'])
        return np.array([normalized,float(requested)],dtype=np.float32),dict(
            reasons=reasons,lane_mask=mask,requested_acceleration_mps2=a,
            rule_scope='following,route lane,red/yellow approach; no crossing-gap or full stop/yield certification')

    def predict(self,observation,deterministic=True):return self.decision(observation)[0]
