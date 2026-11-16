"""73-D policy observation (KC-OBS73-v1) and detected-vehicle list, built from a privileged SUMO snapshot."""
import math
import numpy as np

OFFSETS=(2,1,0,-1,-2)


def build_observation(geometry, ego, vehicles, next_tls, remaining_s, horizon_s,
                      cooldown_s, speed_cap=8.33):
    if ego is None:
        return np.zeros(73,dtype=np.float32), [], [False,True,False]
    blocks=[geometry.lane_features(ego,vehicles,o) for o in OFFSETS]
    obs=np.zeros(73,dtype=np.float32)
    obs[0]=ego['speed']/speed_cap
    for k,block in enumerate(blocks):
        obs[1+4*k:5+4*k]=[1,0,-1,0]
        obs[21+k]=-1
        if not block['exists']:continue
        obs[41+k]=1
        obs[21+k]=float(block['connected'])
        obs[26+k]=block['density']
        for leader in [True,False]:
            other=block['front' if leader else 'rear']
            if other is None:continue
            j=1+4*k+(0 if leader else 2)
            obs[j]=(other['gap']/100 if leader else -other['gap']/50)
            obs[j+1]=(other['speed']-ego['speed'])/speed_cap
            obs[31+2*k+(0 if leader else 1)]=1
    internal=ego['road_id'].startswith(':')
    progress=geometry.locate(ego['road_id'],ego['lane_id'],ego['lane_pos'],ego['route_index'])
    obs[46]=0 if internal else ego['lane']/max(1,geometry.max_lanes-1)
    obs[47]=progress/geometry.total
    obs[48]=max(0.,geometry.total-progress)/1000
    obs[49]=(geometry.net.getLane(ego['lane_id']).getLength()-ego['lane_pos'])/100
    obs[50]=ego['accel_mps2']/(2 if ego['accel_mps2']>=0 else 4.5)
    obs[51]=internal
    obs[52]=cooldown_s
    obs[53]=max(0.,remaining_s)/horizon_s
    near=[t for t in next_tls if 0<=t[2]<=100]
    if near:
        _,_,distance,state=near[0]
        states={'r':0,'y':1,'Y':1,'G':2,'g':2,'o':3,'O':3}
        if state not in states:raise ValueError('Unmapped TLS state: '+state)
        obs[54]=1;obs[55]=distance/100;obs[56+states[state]]=1
    stop=geometry.next_rule(ego,stop_only=True)
    if stop is not None and stop<=100:obs[60]=1;obs[61]=stop/100
    unsignal=geometry.next_rule(ego)
    obs[62]=unsignal is not None and unsignal<=100
    index=ego['route_index']
    if index<len(geometry.links):
        possible=geometry.links[index]
        matching=[c for c in possible if c['from_lane']==ego['lane_id']]
        chosen=(matching or possible)[0]
        direction=chosen['direction'].lower()
        category={'l':0,'s':1,'r':2,'t':3}.get(direction)
        if category is not None:obs[63+category]=1
        boundary=geometry.prefix[index]+geometry.net.getEdge(geometry.edges[index]).getLength()-geometry.start_coordinate
        obs[67]=max(0.,boundary-progress)/100
        for j,k in enumerate([1,2,3]):
            obs[68+j]=blocks[k]['exists'] and blocks[k]['connected']
        obs[71]=1
    obs[72]=ego['allowed_speed_mps']/speed_cap
    mask=[bool(blocks[k]['exists'] and not internal and cooldown_s<=1e-9) for k in [1,2,3]]
    mask[1]=True
    detected=[]
    for v in vehicles:
        if v['id']==ego['id']:continue
        projections=[];in_slot=False
        for offset,block in zip(OFFSETS,blocks):
            if not block['exists']:continue
            for lid,_,start,_ in block['segments']:
                if v['lane_id']==lid:
                    rel=start+v['lane_pos']
                    if -50<=rel<=100:projections.append((abs(rel),offset,rel))
            in_slot |= any(block[k] and block[k]['id']==v['id'] for k in ['front','rear'])
        if projections:
            _,offset,rel=min(projections)
            relation='same_corridor' if offset==0 else 'adjacent_corridor'
            projected=True
        else:
            edge=geometry.net.getLane(ego['lane_id']).getEdge()
            other=geometry.net.getLane(v['lane_id']).getEdge()
            shared=edge.getToNode() in [other.getFromNode(),other.getToNode()]
            if not shared or math.hypot(v['x']-ego['x'],v['y']-ego['y'])>100:continue
            offset=rel=None;relation='crossing';projected=False
        detected.append(dict(id=v['id'],x=v['x'],y=v['y'],rel_pos=rel,speed=v['speed'],
            lane_offset=offset,edge_id=v['road_id'],lane_id=v['lane_id'],
            accel_mps2=v['accel_mps2'],rel_speed_mps=v['speed']-ego['speed'],
            relation=relation,projection_valid=projected,in_policy_slot=in_slot))
    detected.sort(key=lambda x:(abs(x['rel_pos']) if x['rel_pos'] is not None else math.inf,x['id']))
    obs=np.clip(obs,-1,1)
    if obs.shape!=(73,) or not np.isfinite(obs).all():raise ValueError('Invalid policy observation')
    return obs,detected,mask
