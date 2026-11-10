"""Bounded, CPU-only research audit; no policy updates or production map writes.

Run with the isolated audit Python and --output <new directory>.
Existing results are never overwritten. Paths in JSON are repository-relative.
"""
from pathlib import Path
from datetime import datetime
import argparse, ast, collections, contextlib, csv, hashlib, importlib.metadata
import json, os, platform, subprocess, sys, time, xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts/kcity'), '/usr/share/sumo/tools']
os.environ.setdefault('SUMO_HOME', '/usr/share/sumo')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.chdir(ROOT)
    start = datetime.now().astimezone().isoformat()
    files = sorted({*ROOT.glob('env/*.py'), *ROOT.glob('algorithms/*.py'),
        *ROOT.glob('utils/*.py'), *ROOT.glob('scripts/kcity/*.py'),
        *ROOT.glob('maps/kcity/*.xml'), *ROOT.glob('maps/kcity/*.sumocfg'),
        ROOT/'train.py', ROOT/'train_bc.py', ROOT/'test.py', ROOT/'collect_pomdp_data.py',
        ROOT/'data/dataset.npz', ROOT/'README.md', Path(__file__).resolve()})
    before = {str(p.relative_to(ROOT)): sha(p) for p in files}
    provenance = dict(started_at=start, python=sys.version, executable=sys.executable,
        platform=platform.platform(), commit=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
        initial_git_status=subprocess.check_output(['git','status','--short'], text=True),
        SHA256=before, training_updates=0, expert_transitions_collected=0)
    write(out/'provenance.json', provenance)
    summary = {}

    def command(name, argv):
        t = time.monotonic()
        p = subprocess.run(argv, capture_output=True, text=True, timeout=90)
        (out/(name+'.stdout.log')).write_text(p.stdout)
        (out/(name+'.stderr.log')).write_text(p.stderr)
        rec = dict(argv=argv, returncode=p.returncode, wall_seconds=time.monotonic()-t)
        write(out/(name+'.command.json'), rec)
        assert p.returncode == 0, (name,p.stderr[-500:])
        return rec

    import numpy as np
    import torch
    import sumolib
    import traci
    torch.set_num_threads(1)
    versions = {n:importlib.metadata.version(n) for n in ['numpy','torch','gymnasium']}
    versions.update(sumo=subprocess.check_output(['sumo','--version'],text=True).splitlines()[0],
        traci_path=traci.__file__, sumolib_path=sumolib.__file__)
    write(out/'versions.json',versions)
    m=ROOT/'maps/kcity'
    net=sumolib.net.readNet(str(m/'kcity.net.xml'),withInternal=True)
    xml=ET.parse(m/'kcity.net.xml').getroot()
    normal=[e for e in xml.findall('edge') if e.get('function')!='internal']
    rou=ET.parse(m/'kcity.rou.xml').getroot()
    from validate import topology_check
    from validate_signals import structural
    summary['structure']=dict(normal_edges=len(normal), normal_lanes=sum(len(e.findall('lane')) for e in normal),
        internal_lanes=sum(len(e.findall('lane')) for e in xml.findall('edge') if e.get('function')=='internal'),
        junction_types=dict(collections.Counter(j.get('type') for j in xml.findall('junction'))),
        finite_vehicles=len(rou.findall('vehicle')), routes=len(rou.findall('route')),
        topology=topology_check(m), signals=structural())
    assert not summary['structure']['topology']['errors']
    hist=json.loads((m/'reports/signals_validation/summary.json').read_text())
    after=[r for r in hist['runs'] if r['profile']=='after']
    hist_checks=[]
    for r in after:
        folder=m/'reports/signals_validation'/f"after_{r['demand']}_seed{r['seed']}"
        hist_checks.append(dict(demand=r['demand'],seed=r['seed'],
            network_matches=sha(m/'kcity.net.xml')==r['network_sha256'],
            signals_match=sha(m/'kcity.signals.add.xml')==r['signals_sha256'],
            generated_route_file_matches=(folder/'traffic.rou.xml').exists() and sha(folder/'traffic.rou.xml')==r['routes_sha256']))
    summary['historical_HV']=dict(runs=len(after),arrivals=sum(r['arrived'] for r in after),
        collision_records=sum(len(r['collisions']) for r in after),
        teleports=sum(int(r['teleports']['total']) for r in after),
        emergency_braking_warnings=sum(r['emergency_braking_warnings'] for r in after),hash_checks=hist_checks,
        scope='stored finite synthetic traffic; not an AV policy result or a new rerun of all 12 cases')

    q=rou.find("route[@id='qualifier']").get('edges').split()
    candidates={'A_signal':q[5:8],'B_required_lane_change':q[:6],'C_combined':q}
    scenarios={}
    for name,edges in candidates.items():
        links=[]
        for x,y in zip(edges,edges[1:]):
            cs=[c for c in net.getEdge(x).getOutgoing().get(net.getEdge(y),[]) if c.allows('passenger')]
            assert cs,(name,x,y)
            links.append(dict(from_edge=x,to_edge=y,from_length_m=net.getEdge(x).getLength(),
                from_lane_count=net.getEdge(x).getLaneNumber(),
                permitted_from_lanes=sorted({c.getFromLane().getIndex() for c in cs}),
                TLS=sorted({c.getTLSID() for c in cs if c.getTLSID()})))
        scenarios[name]=dict(route=edges,normal_edge_length_sum_m=sum(net.getEdge(e).getLength() for e in edges),
            connections=links,depart_lane_candidate=0,depart_pos_m_candidate=5,
            route_passenger_connectivity_checked=True,AV_spawn_and_expert_feasibility='not implemented/not tested')
    write(out/'scenario_candidates.json',scenarios)

    from algorithms.bc import BCPolicy
    from utils.networks import HybridActorCritic
    from utils.buffer import RolloutBuffer
    torch.manual_seed(0)
    bc=BCPolicy(31,2)
    policy=HybridActorCritic(31,hidden_sizes=(256,256),activation='relu',lane_keep_bias=.5)
    try:
        policy.load_state_dict(bc.state_dict())
        compatible=True;error=None
    except RuntimeError as e:
        compatible=False;error=str(e)[:500]
    obs=torch.zeros(128,31)
    actions,lp,_=policy.sample(obs)
    lp2,_,_=policy.evaluate_actions(obs,actions)
    summary['policy_fixture']=dict(obs_dim=31,act_dim=2,BC_parameters=sum(p.numel() for p in bc.parameters()),
        PPO_parameters=sum(p.numel() for p in policy.parameters()),direct_BC_state_dict_loads_into_PPO=compatible,
        expected_incompatibility=error,hybrid_sample_vs_evaluate_max_logprob_error=float((lp-lp2).abs().max()),
        unbounded_accel_samples_outside_Box=int((actions[:,0].abs()>1).sum()),
        sample_count=128,CUDA_used=False,training_updates=0)
    b=RolloutBuffer();gamma=.99
    b.add(np.zeros(31),np.zeros(2),0.,1+gamma*4,2,False)
    b.add(np.zeros(31),np.zeros(2),0.,100,100,True)
    adv,_=b.compute_gae(0,gamma,.95)
    summary['truncation_fixture']=dict(first_episode_truncated=True,second_episode_reset_value=100,
        terminal_observation_value=4,first_value=2,first_reward=1,stored_bootstrapped_reward=1+gamma*4,
        observed_first_advantage=float(adv[0]),correct_isolated_one_step_advantage=1+gamma*4-2,
        detected_cross_episode_value_leak=True,training_updates=0,
        evidence='PPO.collect_rollout stores terminated only; RolloutBuffer.compute_gae therefore continues across truncation')
    assert abs(float(adv[0])-(1+gamma*4-2))>90
    with np.load(ROOT/'data/dataset.npz',allow_pickle=False) as d:
        summary['legacy_dataset']=dict(path='data/dataset.npz',keys=d.files,
            observations_shape=list(d['observation'].shape),actions_shape=list(d['action_raw'].shape),
            episode_count=len(np.unique(d['episode'])),finite=bool(np.isfinite(d['observation']).all()),
            source_seed_route_policy_version_recorded_in_npz=False,scope='highway dataset, no K-CITY training proof')
    legacy=[]
    for p in (ROOT/'results').glob('*/eval_log.csv'):
        with p.open() as f:rows=list(csv.DictReader(f))
        legacy.append(dict(path=str(p.relative_to(ROOT)),rows=len(rows),last_row=rows[-1] if rows else None))
    summary['legacy_evaluation_logs']=legacy

    from env.road_config import ROAD,EGO,TRAFFIC
    from env.mdp_config import SIMULATION,OBSERVATION,ACTION,REWARD
    from env.road_builder import build
    from env.sumo_env import SumoHighwayEnv
    highway=out/'isolated_highway';highway.mkdir()
    with (out/'legacy_env.stdout.log').open('w') as stream,contextlib.redirect_stdout(stream):
        cfg=build(ROAD,EGO,TRAFFIC,str(highway))
        env=SumoHighwayEnv(cfg,ROAD,EGO,SIMULATION,OBSERVATION,ACTION,REWARD,traffic=TRAFFIC,gui=False)
        resets=[]
        try:
            for trial in range(2):
                np.random.seed(12345) # fixes the SUMO seed source; prefill still uses unseeded default_rng
                obs,info=env.reset(seed=12345)
                initial=env.get_privileged_state()
                fingerprint=hashlib.sha256(json.dumps(initial,sort_keys=True).encode()).hexdigest()
                modes=dict(speedMode=traci.vehicle.getSpeedMode('ego'),laneChangeMode=traci.vehicle.getLaneChangeMode('ego'))
                t0=traci.simulation.getTime()
                for _ in range(10):
                    obs,reward,term,trunc,info=env.step(np.array([0.,0.],dtype=np.float32))
                    if term or trunc:break
                resets.append(dict(trial=trial,observation_shape=list(obs.shape),finite=bool(np.isfinite(obs).all()),
                    initial_traffic_state_SHA256=fingerprint,initial_vehicle_count=len(initial['vehicles']),
                    ten_step_sim_seconds=traci.simulation.getTime()-t0,modes=modes,last_info=info))
        finally:env.close()
    summary['legacy_env_smoke']=dict(resets=resets,same_requested_seed_same_initial_state=resets[0]['initial_traffic_state_SHA256']==resets[1]['initial_traffic_state_SHA256'],
        training_updates=0,steps_maximum=20,generated_network_only_in=str(highway.relative_to(ROOT)))

    cmd=['sumo','-c',str(m/'kcity.sumocfg'),'--seed','43','--end','1800',
        '--no-step-log','true','--duration-log.disable','true','--tripinfo-output',str(out/'finite.trips.xml'),
        '--tripinfo-output.write-unfinished','true','--statistic-output',str(out/'finite.statistics.xml'),
        '--collision-output',str(out/'finite.collisions.xml')]
    cost=command('finite_HV_seed43',cmd)
    trips=ET.parse(out/'finite.trips.xml').findall('tripinfo')
    stats=ET.parse(out/'finite.statistics.xml').getroot()
    summary['finite_HV_new']=dict(seed=43,requested_vehicles=177,
        arrived=sum(float(t.get('arrival'))>=0 for t in trips),
        unfinished=sum(float(t.get('arrival'))<0 for t in trips),
        collision_records=len(ET.parse(out/'finite.collisions.xml').findall('collision')),
        teleports=stats.find('teleports').attrib,wall_seconds=cost['wall_seconds'],
        performance=stats.find('performance').attrib,scope='SUMO built-in controllers; no learned AV')
    command('live_IDM_seed43',['/usr/bin/python3','-B',str(ROOT/'view_kcity.py'),'--nogui','--seconds','600',
        '--seed','43','--report',str(out/'live_IDM.json')])
    summary['live_IDM_new']=json.loads((out/'live_IDM.json').read_text())

    # A separate socket, no GUI and no existing simulator process is controlled.
    with (out/'traci_probe.stdout.log').open('w') as stream:
        traci.start(['sumo','-c',str(m/'kcity.sumocfg'),'--seed','43','--no-step-log','true'],stdout=stream)
        conn=traci.getConnection()
        try:
            for _ in range(100):conn.simulationStep()
            tls=list(conn.trafficlight.getIDList())
            summary['TraCI_probe']=dict(version=conn.getVersion(),deltaT=conn.simulation.getDeltaT(),
                TLS_count=len(tls),signal_types={t:[x.type for x in conn.trafficlight.getAllProgramLogics(t)] for t in tls},
                demo_modes=dict(speedMode=conn.vehicle.getSpeedMode('demo_ego'),laneChangeMode=conn.vehicle.getLaneChangeMode('demo_ego')),
                demo_route=list(conn.vehicle.getRoute('demo_ego')),next_TLS=conn.vehicle.getNextTLS('demo_ego'),
                getBestLanes_available=hasattr(conn.vehicle,'getBestLanes'),getNextLinks_available=hasattr(conn.vehicle,'getNextLinks'))
        finally:conn.close()
    after_hashes={str(p.relative_to(ROOT)):sha(p) for p in files}
    summary['preserved_originals']=dict(all_selected_source_and_map_hashes_unchanged=before==after_hashes,
        changed=[k for k in before if before[k]!=after_hashes[k]])
    summary['ended_at']=datetime.now().astimezone().isoformat()
    write(out/'summary.json',summary)
    print(json.dumps(dict(ended_at=summary['ended_at'],structure=summary['structure'],
        finite_HV_new=summary['finite_HV_new'],truncation_fixture=summary['truncation_fixture'],
        original_files_preserved=summary['preserved_originals']),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
