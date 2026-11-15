"""Read-only model diagnosis, separately labelled interventions and dev100.

No optimizer or learner calls. Original pilot case only for failure replay;
expanded evaluation uses reserved dev indices2,000,000+, never final cases.
"""
import argparse
from collections import Counter
from datetime import datetime
import gzip
import json
from pathlib import Path
import sys

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from algorithms.kcity_training import KCityPPO,read_bundle
from env.kcity_config import load_contract,make_case,file_sha256,digest
from env.kcity_env import SumoKCityEnv
from utils.kcity_data import atomic_json
from utils.kcity_evaluator import EpisodeMetrics,evaluate_cases,aggregate


def load_agent(pilot,method,step,device):
    path=pilot/('bc'/Path(f'update-{step:06d}') if method=='BC' else Path(method)/f'checkpoint-{step:06d}')
    meta=json.loads((path/'metadata.json').read_text())
    payload=read_bundle(path,meta['kind'],meta['config'])
    config=meta['config']['policy']
    agent=KCityPPO(config,seed=11,device=device)
    agent.policy.load_state_dict(payload['policy'] if method=='BC' else payload['agent']['policy'],strict=True)
    agent.policy.eval()
    return agent,dict(path=str(path),sha256=file_sha256(path/'SHA256.json'),kind=meta['kind'])


def diagnose(agent,scenario,folder,intervene=False):
    env=SumoKCityEnv(background=True);case=make_case(env.contract,'dev',scenario,1000000)
    folder.mkdir(parents=True,exist_ok=False);counts=Counter();stationary=Counter();probabilities=[];late=[]
    intervention_count=0
    try:
        obs,reset=env.reset(options={k:case[k] for k in ['namespace','scenario_id','case_index','demand_multiplier']})
        metrics=EpisodeMetrics(case,reset)
        with gzip.open(folder/'trace.jsonl.gz','wt') as f:
            for t in range(601):
                state=env._state
                tensor=torch.as_tensor(obs,device=agent.device).unsqueeze(0)
                with torch.no_grad():
                    nd,cd,_=agent.policy.distributions(tensor)
                    probs=cd.probs[0].cpu().numpy().tolist()
                requested=agent.predict(obs);action=requested.copy()
                # Diagnostic intervention only: issuing an available left
                # request on the initial Edge. Does not change trained weights.
                forced=bool(intervene and state['ego_road_id']=='-3#4' and state['ego_lane']==0 and env.get_action_mask()[0])
                if forced:action[1]=1;intervention_count+=1
                nxt,reward,term,trunc,info=env.step(action);metrics.add(reward,term,trunc,info)
                counts[f'lane_cmd_{int(requested[1])}']+=1
                if state['ego_speed']<.1:stationary[state['ego_lane_id']]+=1
                probabilities.append(probs)
                row=dict(t=t,observation=obs.tolist(),requested_action=requested.tolist(),executed_input=action.tolist(),
                    lane_probabilities=probs,forced_left=forced,state=state,next_state=info['next_state'],
                    events=info['events'],action=info['action'],reward_components=info['reward_components'])
                f.write(json.dumps(row,allow_nan=False)+'\n')
                if state['ego_road_id']=='-3#4' and state['ego_lane']==0 and obs[49]<.15:
                    late.append(dict(t=t,speed=state['ego_speed'],remaining_m=float(obs[49])*100,
                        mu=float(requested[0]),lane_probs=probs,mask=env.get_action_mask()))
                obs=nxt
                if term or trunc:break
        result=dict(metrics=metrics.finish(),requested_lane_counts=dict(counts),stationary_lane_counts=dict(stationary),
            lane_probability_mean=np.mean(probabilities,axis=0).tolist(),
            late_wrong_lane_first=late[0] if late else None,late_wrong_lane_last=late[-1] if late else None,
            final_state=env._state,intervention_count=intervention_count,
            purpose='diagnostic_intervention_NOT_policy_performance' if intervene else 'exact_pilot_case_replay')
        atomic_json(folder/'RESULT.json',result);return result
    finally:env.close()


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--pilot',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path);ap.add_argument('--device',default='cuda',choices=['cpu','cuda'])
    ap.add_argument('--diagnosis-only',action='store_true');args=ap.parse_args();torch.set_num_threads(1)
    args.output.mkdir(parents=True,exist_ok=False)
    status=dict(started_at=datetime.now().astimezone().isoformat(),phase='DIAGNOSIS',optimizer_steps=0,
                final_cases_executed=0,diagnoses={},expanded={})
    atomic_json(args.output/'STATUS.json',status)
    try:
        for method,step in [('B2',40000),('B3',30000)]:
            agent,source=load_agent(args.pilot,method,step,args.device)
            for sid in ['B','C']:
                for intervene in [False,True]:
                    key=f'{method}-{step}-{sid}-'+('forced-left' if intervene else 'original')
                    result=diagnose(agent,sid,args.output/key,intervene)
                    status['diagnoses'][key]=dict(source=source,**result)
                    atomic_json(args.output/'STATUS.json',status)
        if not args.diagnosis_only:
            status['phase']='EXPANDED_DEV100';atomic_json(args.output/'STATUS.json',status)
            contract=load_contract()
            cases=[make_case(contract,'dev',sid,2000000+i) for sid,n in [('A',30),('B',30),('C',40)] for i in range(n)]
            atomic_json(args.output/'DEV100_PANEL.json',dict(cases=cases,sha256=digest(cases),final_access=False))
            for method,step in [('BC',1000),('B2',50000),('B3',50000)]:
                agent,source=load_agent(args.pilot,method,step,args.device)
                folder=args.output/f'dev100-{method}';folder.mkdir();env=SumoKCityEnv(background=True);records=[]
                try:
                    for case in cases:
                        rows,_=evaluate_cases(agent,env,dict(cases=[case]));records.extend(rows)
                        status['expanded'][method]=dict(completed=len(records),planned=100,source=source,
                            aggregate=aggregate(records,100))
                        atomic_json(folder/'EPISODES.json',records);atomic_json(args.output/'STATUS.json',status)
                    atomic_json(folder/'SUMMARY.json',status['expanded'][method])
                finally:env.close()
        status['phase']='COMPLETE';atomic_json(args.output/'STATUS.json',status)
    except BaseException as error:
        status.update(phase='FAILED',error=type(error).__name__+': '+str(error));atomic_json(args.output/'STATUS.json',status);raise


if __name__=='__main__':main()
