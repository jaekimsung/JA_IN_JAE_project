"""Bounded KC-02 Gym checks with scripted actions; no learning or dataset collection."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from kcity.env.env import SumoKCityEnv,IMPLEMENTATION_ID
from kcity.env.config import file_sha256


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    begun=datetime.now().astimezone().isoformat();runs=[]
    # Empty-road tests use no warmup. Background cases keep the protocol's 60s.
    for background in [False,True]:
        for sid in ['A','B','C']:
            folder=out/(sid+('_traffic' if background else '_empty'));folder.mkdir()
            e=SumoKCityEnv(scenario_id=sid,background=background,artifact_dir=folder,
                debug_warmup_s=None if background else 0)
            start=time.monotonic();events=[];steps=0;max_vehicles=0;progress=[];end=None
            valid_obs=True;valid_ticks=True;unknown_crossings=0
            trace=folder/'transitions.jsonl'
            try:
                obs,reset=e.reset(seed=42)
                with trace.open('w') as f:
                    while steps<601:
                        # Deliberately simple scripted test, not B0 or learned AV.
                        lane=1 if sid in ['B','C'] and e._state['ego_road_id']=='-3#4' and e._state['ego_lane']==0 and e.get_action_mask()[0] else 0
                        obs,reward,term,trunc,info=e.step([1.,lane])
                        steps+=1;events+=info['events']
                        valid_obs &= e.observation_space.contains(obs)
                        valid_ticks &= (info['executed_substeps']==5 or term or trunc)
                        unknown_crossings+=sum(x['type']=='tls_crossing' and not x['classification_valid'] for x in info['events'])
                        max_vehicles=max(max_vehicles,info['next_state']['traffic']['running_hv'])
                        if info['next_state']['ego_route_progress_m'] is not None:progress.append(info['next_state']['ego_route_progress_m'])
                        f.write(json.dumps(dict(step=steps,observation=obs.tolist(),reward=reward,
                            terminated=term,truncated=trunc,**info),allow_nan=False)+'\n')
                        if term or trunc:end=info;break
                result=dict(scenario_id=sid,background=background,seed=42,steps=steps,
                    end_reason=end['end_reason'] if end else 'step_guard',
                    sim_elapsed_s=end['episode_time_s'] if end else None,
                    initial_state_sha256=reset['initial_state_sha256'],
                    initial_running_hv=reset['state']['traffic']['running_hv'],max_running_hv=max_vehicles,
                    finite_observation_shape=list(obs.shape),
                    progress_nondecreasing=all(b>=a-1e-5 for a,b in zip(progress,progress[1:])),
                    observation_contract_valid=bool(valid_obs),substep_contract_valid=bool(valid_ticks),
                    unknown_signal_crossings=unknown_crossings,
                    events=events,wall_seconds=time.monotonic()-start,
                    training_ready=False,learning_updates=0,
                    limitation='scripted acceleration/route Lane request, common SUMO safety; not research B0/learned policy')
                runs.append(result);(folder/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
                if end is None:raise RuntimeError('No finite episode termination')
            finally:e.close()
    result=dict(started_at=begun,ended_at=datetime.now().astimezone().isoformat(),
        implementation_id=IMPLEMENTATION_ID,runs=runs,learning_updates=0,expert_dataset_transitions=0,
        source_SHA256={str(p.relative_to(ROOT)):file_sha256(p) for p in [ROOT/'kcity/env/env.py',ROOT/'kcity/env/route.py',ROOT/'kcity/env/observation.py',Path(__file__).resolve()]},
        passed=all(r['end_reason']=='arrival' and r['progress_nondecreasing'] and
                   r['observation_contract_valid'] and r['substep_contract_valid'] and
                   not r['unknown_signal_crossings'] for r in runs),
        training_ready=False)
    (out/'SUMMARY.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['runs','source_SHA256']},indent=2))
    for r in runs:print(r['scenario_id'],r['background'],r['steps'],r['end_reason'],r['progress_nondecreasing'])
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
