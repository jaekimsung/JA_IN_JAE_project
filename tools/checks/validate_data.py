"""Validate committed KC-05 data and optionally check BC tensors without updates."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from kcity.env.config import file_sha256
from kcity.data.dataset import atomic_json,iter_bc_batches,validate_dataset
from kcity.evaluator import aggregate


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path,help='New evidence directory')
    ap.add_argument('--check-bc-forward',action='store_true',help='Explicit debug-loader opt-in, no optimizer steps')
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic();quality=validate_dataset(args.dataset)
    config=json.loads((args.dataset/'RUN.json').read_text())
    summary=dict(checked_at=datetime.now().astimezone().isoformat(),dataset=str(args.dataset.resolve()),
        quality=quality,episode_aggregate=aggregate([e['metrics'] for e in quality['episodes']],len(config['plan'])),
        source_SHA256={f:file_sha256(ROOT/f) for f in ['tools/checks/validate_data.py','kcity/data/dataset.py','kcity/data/collector.py','kcity/policy/rule_expert.py']},
        learner_executed=False,optimizer_steps=0,expert_pool_transitions_for_10M=0,training_ready=False)
    if args.check_bc_forward:
        import torch
        from kcity.training import KCityBC
        model=KCityBC();before={k:v.clone() for k,v in model.policy.state_dict().items()}
        checks={}
        for split in ['expert_train','expert_val']:
            count=0;total=0.;mse=ce=0.
            with torch.no_grad():
                for batch in iter_bc_batches(args.dataset,split,allow_debug=True):
                    loss,parts=model.loss(batch['observation'],batch['action_target'],batch['action_mask'])
                    if not torch.isfinite(loss):raise ValueError('BC forward loss is not finite')
                    n=len(batch['observation']);count+=n;total+=float(loss)*n
                    mse+=float(parts['accel_mse'])*n;ce+=float(parts['lane_ce'])*n
            checks[split]=dict(eligible_transitions=count,untrained_forward_loss=total/count if count else None,
                accel_mse=mse/count if count else None,lane_ce=ce/count if count else None)
        unchanged=all(torch.equal(v,model.policy.state_dict()[k]) for k,v in before.items())
        summary['bc_forward_check']=dict(splits=checks,weights_unchanged=unchanged,
            optimizer_state_empty=not model.optimizer.state,gradient_updates=0,
            note='Untrained random actor tensor/label compatibility only; not BC training performance')
        if not unchanged or model.optimizer.state:raise RuntimeError('Forward-only check changed training state')
    summary['validation_wall_s']=time.monotonic()-started
    summary['passed']=quality['passed']
    atomic_json(args.output/'SUMMARY.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['quality','source_SHA256']},indent=2))


if __name__=='__main__':main()
