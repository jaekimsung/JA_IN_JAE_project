"""Local-only operational preflight. Does not collect, train, or upload."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from env.kcity_config import file_sha256
from utils.kcity_main import FROZEN,load_scientific,operational_sources,require,now,read
from utils.kcity_data import atomic_json
from utils.kcity_storage import CHECKPOINT_MODE


def dataset_storage(folder):
    folder=Path(folder)
    rows=read(folder/'RELEASE.json')['committed_transitions']
    shards=list((folder/'shards').glob('shard-*'))
    payload=sum(p.stat().st_size for s in shards for p in s.rglob('*') if p.is_file())
    data_bytes=0
    auxiliary=[]
    for shard in shards:
        data=sum((shard/name).stat().st_size for name in ['transitions.jsonl.gz','numeric.npz','events.jsonl.gz'])
        data_bytes+=data
        auxiliary.append(sum(p.stat().st_size for p in shard.rglob('*') if p.is_file())-data)
    index=folder/'partial/index.sqlite'
    model_folders=list((folder/'checkpoints').glob('T*'))
    model_bytes=[sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()) for directory in model_folders]
    config=read(folder/'RUN.json')
    return dict(transitions=rows,committed_bytes=payload,bytes_per_transition=payload/rows,
                transition_payload_bytes_per_transition=data_bytes/rows,
                max_joint_checkpoint_and_metadata_bytes=max(auxiliary),
                checkpoint_mode=config.get('checkpoint_policy',{}).get('mode','embedded'),
                retained_checkpoint_count=len(model_folders),retained_checkpoint_bytes=sum(model_bytes),
                max_retained_checkpoint_bundle_bytes=max(model_bytes,default=0),
                sqlite_bytes_per_transition=index.stat().st_size/rows if index.exists() else 0,
                one_time_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())-payload-sum(model_bytes))


def local_archive(probe,output):
    folder=output/'local_archive'
    folder.mkdir(exist_ok=False)
    files={}
    for p in probe.rglob('*'):
        if p.is_file() and 'partial' not in p.relative_to(probe).parts:
            files['probe/'+str(p.relative_to(probe))]=p
    for name in [*operational_sources(),'scripts/kcity/check_main_operations.py','scripts/kcity/preflight_main.py',
                 'configs/kcity/main_v1/FROZEN_PROTOCOL.json']:
        files['repository/'+name]=ROOT/name
    manifest={name:file_sha256(path) for name,path in sorted(files.items())}
    atomic_json(folder/'FILES_SHA256.json',manifest)
    archive=folder/'operational_evidence.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,path in sorted(files.items()):
            tar.add(path,arcname=name,recursive=False)
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers()
        require({m.name for m in members}==set(manifest),'Local archive file set mismatch')
        for member in members:
            stream=tar.extractfile(member)
            checksum=hashlib.sha256()
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                checksum.update(chunk)
            require(checksum.hexdigest()==manifest[member.name],'Local archive readback mismatch')
    result=dict(path=str(archive.resolve()),bytes=archive.stat().st_size,sha256=file_sha256(archive),
                files=len(manifest),all_files_read_back_verified=True,remote_uploads_enabled=False,
                remote_backup_verified=False)
    atomic_json(folder/'VERIFICATION.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',required=True,type=Path)
    parser.add_argument('--tests',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    spec=load_scientific()
    summary=read(args.probe/'SUMMARY.json')
    require(summary['passed'] and summary['operational_sources']==operational_sources(),'Missing or stale operational probe')
    require(summary['main_training_started'] is False and summary['remote_uploads_enabled'] is False,'Probe scope mismatch')
    tests=args.tests.read_text()
    count=re.search(r'^Ran (\d+) tests? in ',tests,re.MULTILINE)
    require(count is not None and re.search(r'^OK$',tests,re.MULTILINE),'Tests did not pass')
    args.output.mkdir(parents=True,exist_ok=False)
    backup=local_archive(args.probe,args.output)
    expert=dataset_storage(args.probe/'expert_dataset')
    ppo=dataset_storage(args.probe/'recorded_gpu/dataset')
    free=shutil.disk_usage(args.output).free
    # Preserve every logical State row; account for retained learner bundles separately.
    index_rate=max(expert['sqlite_bytes_per_transition'],ppo['sqlite_bytes_per_transition'])
    # The STOP fixture deliberately saves7- and64-row shards. Scaling three
    # optimizer bundles per2119 rows would falsely assume equally frequent STOPs
    # throughout production. Model bundle cost is per commit, not per data row.
    per_run=spec['budgets']['ppo_transitions_per_method_seed']
    interval=spec['metrics']['dev_interval_transitions']
    commits=sum(math.ceil(min(interval,per_run-start)/spec['ppo']['n_steps'])
                for start in range(0,per_run,interval))
    ppo_rate=(ppo['transition_payload_bytes_per_transition']+
              ppo['max_joint_checkpoint_and_metadata_bytes']*commits/per_run)
    ppo['production_bytes_per_transition_estimate']=ppo_rate
    ppo['joint_commits_per_million_run']=commits
    external=ppo['checkpoint_mode']==CHECKPOINT_MODE
    retained_per_run=math.ceil(per_run/interval)+2+1+1 if external else 0
    retained_total=6*retained_per_run*ppo['max_retained_checkpoint_bundle_bytes']
    # STOPs no longer accumulate model bundles; reserve two extra partial DATA
    # shards per learner rather than100 permanently retained learner copies.
    stop_reserve=(12*ppo['max_joint_checkpoint_and_metadata_bytes'] if external else
                  100*ppo['max_joint_checkpoint_and_metadata_bytes'])
    main_raw=(spec['budgets']['expert_valid_transitions_min']*expert['bytes_per_transition']+
              spec['budgets']['ppo_total_transitions']*ppo_rate+7000000*index_rate+stop_reserve+retained_total)
    # Reserve main plan/source archives, BC views/models, evaluation logs and staging.
    fixed_overhead=2*1024**3
    main_needed=int(1.5*(main_raw+fixed_overhead)+20*1024**3)
    full_needed=int(main_needed+1.5*spec['budgets']['archive_total_transitions']*
                    (max(expert['bytes_per_transition'],ppo_rate)+index_rate))
    capacity=dict(free_bytes=free,main7M_required_bytes=main_needed,
        submission10M_projected_required_bytes=full_needed,main7M_capacity_pass=free>=main_needed,
        submission10M_capacity_pass=free>=full_needed,expert_measurement=expert,ppo_measurement=ppo,
        reserve_bytes=20*1024**3,headroom_multiplier=1.5,fixed_overhead_bytes=fixed_overhead,
        additional_safe_stop_bundles_reserved=0 if external else 100,safe_stop_reserve_bytes=stop_reserve,
        retained_bundles_reserved_per_run=retained_per_run,retained_bundle_total_bytes=retained_total,
        data_storage_codec=read(args.probe/'recorded_gpu/dataset/RUN.json').get('storage_codec','full_v1'),
        method='Measured lossless row payload and SQLite plus per-shard metadata. External learner bundles: latest2 +50k evaluation points +initial +one staging copy per run. Headroom1.5x and operating reserve20GiB unchanged. No required logical State fields removed.')
    atomic_json(args.output/'CAPACITY.json',capacity)
    result=dict(phase='READY_LOCAL_ONLY' if capacity['main7M_capacity_pass'] else 'STORAGE_REVIEW_REQUIRED',
        launch_ready=capacity['main7M_capacity_pass'],checked_at=now(),scientific_sha256=file_sha256(FROZEN),
        operational_sources=operational_sources(),preflight_script_sha256=file_sha256(Path(__file__)),
        ready_stages=['expert_pool','bc','ppo'] if capacity['main7M_capacity_pass'] else [],
        scientific_settings_frozen=True,main_training_started=False,new_main_expert_transitions=0,
        new_main_ppo_transitions=0,tests_passed=int(count.group(1)),tests_log_sha256=file_sha256(args.tests),
        gpu_checks=summary,local_archive=backup,capacity=capacity,
        remote_uploads_enabled=False,remote_backup_verified=False,
        backup_requirement='User explicitly prohibited Drive uploads; remote backup is waived, not verified. Local archive only.',
        scope='Main expert1M + BC + PPO6M preparation only; no main collection/training launched. Recheck disk before every stage.',
        deferred=['final evaluation3000episodes','archive3M implementation and capacity recheck','submission packaging'])
    atomic_json(args.output/'LAUNCH_READY.json',result)
    print(json.dumps(dict(phase=result['phase'],launch_ready=result['launch_ready'],
        free_GiB=round(free/1024**3,2),required_main_GiB=round(main_needed/1024**3,2),
        required_submission_GiB=round(full_needed/1024**3,2),tests_passed=result['tests_passed'],
        remote_uploads_enabled=False),indent=2))


if __name__=='__main__':main()
