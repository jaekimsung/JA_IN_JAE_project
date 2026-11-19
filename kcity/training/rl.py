"""Online RL training (B2 online-only SAC, B3 RLPD with expert prior data) and its dev-panel curve.

Every environment step is recorded in the dataset format under <run>/transitions. A shard and the learner
bundle it refers to are committed together; on resume the replay buffer is rebuilt from the committed shards.
"""
import json
from pathlib import Path
import time

from kcity.data.collector import dataset_config
from kcity.data.dataset import ShardWriter, atomic_json
from kcity.data.online import OnlineRecorder
from kcity.data.pool import pool_data_id
from kcity.data.plans import GeneratedCasePlan
from kcity.data.replay import load_prior, load_store
from kcity.data.storage import checkpoint_from_shard
from kcity.env.config import ROOT, digest
from kcity.env.env import SumoKCityEnv
from kcity.evaluation.evaluate import evaluate_cases
from kcity.evaluation.metrics import aggregate, policy_weights_sha256
from kcity.policy.checkpoint import read_bundle, write_bundle
from kcity.policy.rlpd import KCityRLPD
from kcity.training.experiment import is_pilot, run_metadata, training_config
from kcity.training.runs import Owner, now, read, require, stopped
from kcity.training.logging import IntervalMean

RESET_KEYS = ('namespace', 'scenario_id', 'case_index', 'demand_multiplier')


def evaluate_dev(agent, root, point, spec, stop=lambda: False):
    """Deterministic dev-panel evaluation at a fixed transition count; resumable case by case."""
    folder = Path(root) / 'dev' / f'T{point:07d}'
    folder.mkdir(parents=True, exist_ok=True)
    policy_sha = policy_weights_sha256(agent)
    if (folder / 'POLICY.json').exists():
        require(read(folder / 'POLICY.json')['acting_state_dict_sha256'] == policy_sha, 'Dev policy changed at fixed transition')
    else:
        atomic_json(folder / 'POLICY.json', dict(acting_state_dict_sha256=policy_sha, actual_transitions=point))
    if (folder / 'SUMMARY.json').exists():
        return True
    cases = read(ROOT / spec['case_panels']['dev']['path'])['cases']
    records = read(folder / 'EPISODES.json') if (folder / 'EPISODES.json').exists() else []
    require([r['requested_case_uid'] for r in records] == [c['case_uid'] for c in cases[:len(records)]], 'Dev resume panel mismatch')
    env = SumoKCityEnv(background=True)
    try:
        for case in cases[len(records):]:
            if stop():
                return False
            rows, _ = evaluate_cases(agent, env, dict(cases=[case]))
            records.extend(rows)
            atomic_json(folder / 'EPISODES.json', records)
            atomic_json(Path(root) / 'STATUS.json', dict(phase='EVALUATING_DEV', transitions=point,
                completed_cases=len(records), planned_cases=len(cases), updated_at=now()))
        atomic_json(folder / 'SUMMARY.json', dict(actual_transitions=point, aggregate=aggregate(records, len(cases)),
                                                  acting_state_dict_sha256=policy_sha))
        curve = [read(path) for path in sorted((Path(root) / 'dev').glob('T*/SUMMARY.json'))]
        threshold, interval = spec['metrics']['target_rate'], spec['metrics']['dev_interval_transitions']

        def reached(row):
            a = row['aggregate']
            return (a['n_valid'] == len(cases) and a['data_quality_valid'] and
                    a['compliant_completion_rate'] is not None and a['compliant_completion_rate'] >= threshold)
        target = confirmation = None
        for first, second in zip(curve, curve[1:]):
            if reached(first) and reached(second) and second['actual_transitions'] - first['actual_transitions'] == interval:
                target, confirmation = first['actual_transitions'], second['actual_transitions']
                break
        atomic_json(Path(root) / 'SAMPLE_EFFICIENCY.json', dict(target_transition=target,
            confirmation_transition=confirmation, right_censored=confirmation is None,
            observed_through_transition=point, curve=curve))
        return True
    finally:
        env.close()


def run_rl(root, method, seed, spec, device, prior_pool=None, resume=False):
    root = Path(root)
    hparams = dict(spec['rlpd'])
    prior_id = None
    if method == 'B3':
        require(prior_pool is not None, 'B3 (RLPD) requires the expert pool as prior data')
        prior_id = pool_data_id(prior_pool)
    else:
        require(prior_pool is None, 'B2 is online-only; do not pass prior data')
        hparams['offline_ratio'] = 0.0
    pilot = is_pilot(spec)
    cfg = training_config(spec, 'pilot_rl' if pilot else 'main_rl', seed, method, device=device,
                          prior_pool=str(Path(prior_pool).resolve()) if prior_pool else None, prior_data_id=prior_id)
    cap = spec['budgets']['rl_transitions_per_method_seed']
    interval = spec['metrics']['dev_interval_transitions']
    owner = Owner(root, cfg, resume)
    env = SumoKCityEnv(background=True)
    writer = None
    clock = time.monotonic()
    try:
        agent = KCityRLPD(hparams, seed=seed, device=device)
        bundle_config = dict(method=method, seed=seed, hidden_dims=hparams['hidden_dims'], hparams=hparams,
                             device_type=agent.device.type, contract_sha256=digest(env.contract))
        prior = load_prior(prior_pool, spec['budgets']['prior_transitions'], pilot=pilot,
                           minimum_pool_rows=spec['budgets']['expert_valid_transitions_min'],
                           contract=env.contract) if method == 'B3' else None
        plan = GeneratedCasePlan.for_budget(env.contract, 'train', cap + 1)
        dcfg = dataset_config(env, root.name + '-online', plan, 'pilot_rl_train' if pilot else 'rl_train', method, seed,
                              experiment_sha256=cfg['experiment_sha256'], evaluation_interval=interval)
        dcfg['learner_config'] = cfg
        writer = ShardWriter(root / 'transitions', dcfg, resume=resume, shard_rows=spec['rl']['commit_interval'])
        replay = load_store(writer.folders, cap)  # the committed online transitions are the replay buffer
        require(len(replay) == writer.count, 'Replay buffer differs from committed transitions')
        steps, episode = writer.count, 0
        saved, folder = writer.last_checkpoint()
        if saved is not None:
            bundle = checkpoint_from_shard(folder)
            agent.restore_training_state(read_bundle(bundle, 'rl', bundle_config)['agent'])
            episode = saved['trainer']['episode']
            obs = env.load_resume_state(bundle / 'environment')
            require(env.case == plan[episode]['case'], 'Restored case differs from the training plan')
        else:
            obs, _ = env.reset(options={k: plan[episode]['case'][k] for k in RESET_KEYS})

        # The recorder's behavior hash must describe the restored actor on resume.
        recorder = OnlineRecorder(agent, writer)
        training_interval = IntervalMean()
        interval_start = steps

        def commit():
            nonlocal interval_start
            folder = recorder.commit(dict(steps=steps, episode=episode),
                                     lambda path: write_bundle(path, 'rl', bundle_config, dict(agent=agent.training_state()), env))
            bundle = checkpoint_from_shard(folder)
            atomic_json(root / 'LATEST.json', dict(path=str(folder.relative_to(root)), transitions=steps))
            atomic_json(root / 'STATUS.json', dict(phase='STOPPED' if stopped(root) else ('RL_PILOT_TRAINING' if pilot else 'RL_TRAINING'),
                updated_at=now(), method=method, seed=seed, transitions=steps, target=cap, updates=agent.num_updates,
                episodes=episode, checkpoint=str(bundle), session_wall_s=time.monotonic() - clock, run=run_metadata()))
            with (root / 'curve.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(transitions=steps, updates=agent.num_updates, episodes=episode,
                    metrics=training_interval.mean(), metric_aggregation='interval_mean',
                    training_update_count=training_interval.count, interval_start_transitions=interval_start,
                    session_wall_s=time.monotonic() - clock, checkpoint=str(bundle))) + '\n')
            training_interval.reset()
            interval_start = steps

        while True:
            if steps % interval == 0 and not writer.pending:
                if not evaluate_dev(agent, root, steps, spec, lambda: stopped(root)):
                    return
            if steps >= cap or stopped(root):
                break
            random_action = steps < hparams['start_training']
            action = agent.random_action() if random_action else agent.act(obs)
            detected = env.get_detected_vehicles()
            fresh = not recorder.recorder.active
            reset_state = env._state if fresh else None
            nxt, reward, term, trunc, info = env.step(action)
            require(episode < len(plan), 'Training case plan exhausted')
            recorder.add(episode=episode, reset_state=reset_state, random_action=random_action,
                         observation=obs, detected=detected, next_observation=nxt,
                         next_detected=env.get_detected_vehicles(), reward=reward, terminated=term, truncated=trunc, info=info)
            replay.add(obs, action, reward, nxt, term)
            steps += 1
            if term or trunc:
                episode += 1
                obs, _ = env.reset(options={k: plan[episode]['case'][k] for k in RESET_KEYS})
            else:
                obs = nxt
            if not random_action:
                training_interval.add(agent.update(agent.sample_batch(replay, prior)))
            if writer.pending >= writer.shard_rows or steps % interval == 0 or steps == cap or stopped(root):
                commit()
        if steps == cap and not writer.pending:
            atomic_json(root / 'COMPLETE.json', dict(transitions=cap, updates=agent.num_updates, episodes=episode,
                completed_at=now(), policy_selection='budget_end',
                checkpoint=str(checkpoint_from_shard(root / read(root / 'LATEST.json')['path']))))
    finally:
        if writer is not None:
            writer.close()
        env.close()
        owner.close()
