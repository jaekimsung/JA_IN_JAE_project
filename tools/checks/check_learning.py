"""KC-03 bounded evidence: corrected GAE, case panels and real metrics. No training."""
import argparse
import csv
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from kcity.env.config import load_contract,file_sha256
from kcity.env.env import SumoKCityEnv
from rl.buffer import RolloutBuffer
from kcity.evaluator import make_panel,evaluate_cases,METRIC_VERSION


class ScriptedProbe:
    """Privileged routing fixture, deliberately NOT research B0 or learned AV."""
    def __init__(self,env):self.env=env
    def predict(self,obs,deterministic=True):
        e=self.env
        left=(e.case['scenario_id'] in ['B','C'] and e._state['ego_road_id']=='-3#4'
              and e._state['ego_lane']==0 and e.get_action_mask()[0])
        return np.array([1.,float(left)],dtype=np.float32)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--old-buffer',type=Path,help='Optional preserved pre-fix utils/buffer.py')
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    started=datetime.now().astimezone().isoformat();contract=load_contract()
    b=RolloutBuffer();b.add([0],[0,0],0,1,2,terminated=False,truncated=True,next_value=4)
    b.add([0],[0,0],0,100,100,terminated=True,next_value=0)
    fixed=float(b.compute_gae(0,.99,.95)[0][0]);old=None
    if args.old_buffer:
        module=importlib.util.spec_from_file_location('preserved_buffer',args.old_buffer)
        before=importlib.util.module_from_spec(module);module.loader.exec_module(before)
        legacy=before.RolloutBuffer();legacy.add([0],[0,0],0,1+.99*4,2,False)
        legacy.add([0],[0,0],0,100,100,True)
        old=float(legacy.compute_gae(0,.99,.95)[0][0])
    panels={name:make_panel(contract,name) for name in ['dev','final']}
    panels.update({f'final_x{m}':make_panel(contract,'final',demand_multiplier=m) for m in [1.5,2.]})
    (out/'PANELS_NOT_EXECUTED.json').write_text(json.dumps(panels,indent=2)+'\n')
    runs=[]
    for background in [False,True]:
        folder=out/('traffic' if background else 'empty');folder.mkdir()
        env=SumoKCityEnv(background=background,debug_warmup_s=None if background else 0,artifact_dir=folder)
        probe=ScriptedProbe(env)
        panel=make_panel(contract,'contract_check',{'A':1,'B':1,'C':1})
        (folder/'PANEL.json').write_text(json.dumps(panel,indent=2)+'\n')
        traces=(folder/'transitions.jsonl').open('w')
        def write(case,obs,action,next_obs,reward,term,trunc,info):
            traces.write(json.dumps(dict(requested_case_uid=case['case_uid'],observation=obs.tolist(),
                next_observation=next_obs.tolist(),reward=reward,terminated=term,truncated=trunc,**info),allow_nan=False)+'\n')
        try:records,summary=evaluate_cases(probe,env,panel,on_transition=write)
        finally:traces.close();env.close()
        (folder/'EPISODES.json').write_text(json.dumps(records,indent=2,allow_nan=False)+'\n')
        with (folder/'EPISODES.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=sorted(set().union(*(r.keys() for r in records))))
            writer.writeheader()
            for r in records:writer.writerow({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in r.items()})
        (folder/'AGGREGATE.json').write_text(json.dumps(summary,indent=2)+'\n')
        runs.append(dict(background=background,records=records,aggregate=summary))
    sources=['rl/buffer.py','rl/ppo.py','kcity/env/env.py','kcity/evaluator.py',
             'tools/checks/check_learning.py','tests/test_kcity_learning.py']
    result=dict(started_at=started,ended_at=datetime.now().astimezone().isoformat(),
        metric_version=METRIC_VERSION,source_SHA256={f:file_sha256(ROOT/f) for f in sources},
        gae_fixture=dict(before=old,after=fixed,expected=2.96,raw_reward_preserved=b.rewards[0]==1),
        panels_generated_not_executed={k:dict(case_count=len(v['cases']),sha256=v['panel_sha256']) for k,v in panels.items()},
        actual_execution_namespace='contract_check',runs=runs,
        policy='privileged scripted probe; not B0/BC/PPO',learning_updates=0,optimizer_steps=0,
        expert_dataset_transitions=0,training_ready=False,
        passed=abs(fixed-2.96)<1e-5 and all(r['aggregate']['n_completed']==3 and
            r['aggregate']['data_quality_valid'] and not r['aggregate']['n_unknown_tls_crossings'] for r in runs))
    (out/'SUMMARY.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['runs','source_SHA256']},indent=2))
    for r in runs:
        for ep in r['records']:print(r['background'],ep['scenario_id'],ep['primary_end_reason'],ep['decision_count'],ep['data_quality_valid'])
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
