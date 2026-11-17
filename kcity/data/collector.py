"""Case plans, dataset run configs and policy-driven collection (B0 expert or a fixed learned policy)."""

from collections import Counter
from copy import deepcopy
import json
import platform
import subprocess
import xml.etree.ElementTree as ET

import numpy as np

from kcity.data.dataset import atomic_json, now
from kcity.data.recorder import EpisodeRecorder
from kcity.data.storage import CHECKPOINT_MODE, NEXT_CODEC, require
from kcity.env.config import DEFAULT_PROTOCOL, ROOT, digest, file_sha256, git_info, make_case, repository_path
from kcity.env.env import IMPLEMENTATION_ID
from kcity.policy.rule_expert import EXPERT_ID, KCityRuleExpert

PATTERN = ('A', 'A', 'A', 'B', 'B', 'B', 'C', 'C', 'C', 'C')
EXPERT_SPLITS = ('expert_train', 'expert_val')


# ---------------------------------------------------------------- case plans


def resolved_case(
    contract,
    namespace,
    scenario_id,
    index,
    demand_multiplier=1.0,
    *,
    background=True,
    debug_warmup_s=None,
    debug_episode_limit_s=None
):
    """A case with the runtime variant it will run under; case_uid covers both."""
    case = make_case(contract, namespace, scenario_id, index, demand_multiplier)
    timing = contract['protocol']['timing']
    case['runtime_variant'] = dict(
        implementation=IMPLEMENTATION_ID,
        background=background,
        warmup_s=timing['warmup_s'] if debug_warmup_s is None else debug_warmup_s,
        horizon_s=(
            case['scenario']['episode_limit_s'] if debug_episode_limit_s is None else debug_episode_limit_s
        ),
        debug_override=debug_warmup_s is not None or debug_episode_limit_s is not None,
    )
    case['case_uid'] = digest({k: v for k, v in case.items() if k != 'case_uid'})
    return case


def case_plan(contract, kind, count=20000, start=0):
    """Main plans. expert: every 5th case of a scenario is expert_val. train/probe/archive: own namespaces."""
    require(type(count) is int and count > 0, 'Positive case count required')
    seen = Counter()
    result = []
    for cursor in range(count):
        scenario = PATTERN[cursor % len(PATTERN)]
        if kind == 'expert':
            index = seen[scenario] + start
            seen[scenario] += 1
            namespace = split = 'expert_val' if index % 5 == 4 else 'expert_train'
        else:
            require(kind in ('probe', 'train', 'archive'), 'Unknown case plan kind: ' + str(kind))
            index = cursor + start
            namespace, split = dict(
                probe=('contract_check', 'ops_probe'),
                train=('train', 'rl_train'),
                archive=('archive', 'archive'),
            )[kind]
        result.append(dict(case=resolved_case(contract, namespace, scenario, index), data_split=split))
    require(len({r['case']['case_uid'] for r in result}) == len(result), 'Repeated case in plan')
    return result


def resolve_plan(env, entries):
    """Explicit plans for checks/tests: entries (scenario_id, namespace, case_index, data_split[, demand])
    resolved with this environment's runtime variant (background traffic, debug warmup/horizon)."""
    plan = []
    for entry in entries:
        if entry['data_split'] in EXPERT_SPLITS or entry['namespace'] in EXPERT_SPLITS:
            require(
                entry['namespace'] == entry['data_split'],
                'Expert train/val seed namespaces and splits must match',
            )
        case = resolved_case(
            env.contract,
            entry['namespace'],
            entry['scenario_id'],
            entry['case_index'],
            entry.get('demand_multiplier', 1.0),
            background=env.background,
            debug_warmup_s=env.debug_warmup_s,
            debug_episode_limit_s=env.debug_episode_limit_s,
        )
        plan.append(dict(case=case, data_split=entry['data_split']))
    return plan


# ---------------------------------------------------------------- run config


def dataset_config(
    env,
    run_uid,
    plan,
    stage='debug',
    method='B0',
    seed=None,
    *,
    experiment_sha256=None,
    fixed_policy=None,
    evaluation_interval=50000
):
    """ShardWriter config. Rows come from the B0 expert, online RL (method B2/B3) or a fixed learned policy."""
    require(isinstance(run_uid, str) and run_uid, 'Stable run UID required')
    require(len({r['case']['case_uid'] for r in plan}) == len(plan), 'Duplicate planned case')
    require(
        json.loads(DEFAULT_PROTOCOL.read_text()) == env.contract['protocol'],
        'Collector requires the default environment contract (configs/kcity/v1/protocol.json)',
    )
    teacher = dict(id=EXPERT_ID, config=deepcopy(KCityRuleExpert().config))
    teacher['fingerprint'] = digest(teacher)
    assets = deepcopy(env.contract['protocol']['assets'])
    assets['scenarios'] = deepcopy(env.contract['protocol']['scenario_manifest'])
    assets['protocol'] = dict(
        path=str(DEFAULT_PROTOCOL.relative_to(ROOT)), sha256=file_sha256(DEFAULT_PROTOCOL)
    )
    location = ET.parse(repository_path(assets['network']['path'])).getroot().find('location')
    sumo = subprocess.check_output([env.sumolib.checkBinary('sumo'), '--version'], text=True).splitlines()[0]
    config = dict(
        schema_id='KC-COLLECTION-v1-candidate',
        run_uid=run_uid,
        source_stage=stage,
        eligible_for_research_training=stage == 'expert_pool',
        contract=env.contract,
        teacher=teacher,
        code=git_info(),
        asset_snapshots=assets,
        plan=plan,
        environment=dict(
            background=env.background,
            debug_warmup_s=env.debug_warmup_s,
            debug_episode_limit_s=env.debug_episode_limit_s,
        ),
        coordinate_frame=dict(
            position_reference='SUMO_front_bumper_center',
            location=dict(location.attrib) if location is not None else None,
        ),
        episode_id_scheme='dataset_local_monotonic_registry; run_uid makes Episode UIDs globally unique',
        runtime=dict(
            python=platform.python_version(),
            platform=platform.platform(),
            numpy=np.__version__,
            sumo_version=sumo,
        ),
        experiment_sha256=experiment_sha256,
        storage_codec=NEXT_CODEC,
    )
    if method != 'B0':
        config['checkpoint_policy'] = dict(
            mode=CHECKPOINT_MODE, keep_recent=2, evaluation_interval_transitions=evaluation_interval
        )
        config['online_policy'] = dict(method=method, seed=seed, version='KC-ONLINE-RLPD-v1')
        config['teacher'] = dict(
            id=method + '-online', config=dict(seed=seed), fingerprint=digest(dict(method=method, seed=seed))
        )
    if fixed_policy is not None:
        require(method == 'B0', 'fixed_policy and online RL are exclusive')
        require(
            {'method', 'seed', 'version', 'policy_sha256'} <= set(fixed_policy),
            'Incomplete fixed policy identity',
        )
        config['fixed_policy'] = dict(fixed_policy)
        config['teacher'] = dict(
            id=fixed_policy['method'] + '-fixed',
            config=dict(seed=fixed_policy['seed']),
            fingerprint=fixed_policy['policy_sha256'],
        )
    return config


# ---------------------------------------------------------------- collection


class PolicyCollector:
    """Run a policy (`predict(obs)`) through the plan cases in order and record every transition.

    Resumable at shard boundaries: an Episode that spans a shard is restored by replaying it.
    """

    def __init__(self, env, policy, writer):
        self.env, self.policy, self.writer = env, policy, writer
        self.plan = writer.config['plan']
        self.recorder = EpisodeRecorder(writer)
        self.index = 0  # next (or current) plan case
        self.obs = None
        self.detected = []
        saved, folder = writer.last_checkpoint()
        if saved is None:
            return
        require(saved['committed_transitions'] == writer.count, 'Collector/writer counter mismatch')
        self.index = saved['episode_index']
        if saved['active']:
            self.env.load_resume_state(folder / 'environment')
            require(self.env.case == self.plan[self.index]['case'], 'Restored case differs from data plan')
            self.obs = self.env._obs.copy()
            self.detected = self.env.get_detected_vehicles()
            self.recorder.restore(saved['recorder'])

    def _start(self):
        case = self.plan[self.index]['case']
        self.obs, reset = self.env.reset(
            options={k: case[k] for k in ['namespace', 'scenario_id', 'case_index', 'demand_multiplier']}
        )
        require(reset['case'] == case, 'Runtime case differs from declared source/seed manifest')
        self.detected = self.env.get_detected_vehicles()
        self.recorder.start(self.index, reset['state']['sim_tick'], reset['state'])

    def checkpoint(self):
        return dict(
            schema='KC-COLLECTOR-RESUME-v2',
            episode_index=self.index,
            active=self.recorder.active,
            committed_transitions=self.writer.count + self.writer.pending,
            recorder=self.recorder.state(),
        )

    def _commit(self):
        save_env = self.env.save_resume_state if self.recorder.active else None
        if self.writer.commit(self.checkpoint(), self.recorder.completed, save_env) is not None:
            self.recorder.completed = []

    def collect(self, target, stop=lambda: False):
        """Collect until an absolute transition target, then finish the current Episode."""
        require(
            type(target) is int and target > 0 and target >= self.writer.count,
            'Invalid absolute collection target',
        )
        while self.index < len(self.plan):
            if stop() or (self.writer.count + self.writer.pending >= target and not self.recorder.active):
                break
            if not self.recorder.active:
                self._start()
            before, detected = self.obs.copy(), deepcopy(self.detected)
            nxt, reward, term, trunc, info = self.env.step(self.policy.predict(before))
            next_detected = self.env.get_detected_vehicles()
            self.recorder.record(
                observation=before,
                detected=detected,
                next_observation=nxt,
                next_detected=next_detected,
                reward=reward,
                terminated=term,
                truncated=trunc,
                info=info,
            )
            self.obs, self.detected = nxt, next_detected
            if term or trunc:
                self.index += 1
            if self.writer.pending >= self.writer.shard_rows or (
                (term or trunc) and self.writer.count + self.writer.pending >= target
            ):
                self._commit()
                atomic_json(
                    self.writer.root.parent / 'STATUS.json',
                    dict(
                        phase='COLLECTING',
                        updated_at=now(),
                        transitions=self.writer.count,
                        target=target,
                        completed_episodes=self.index,
                    ),
                )
        if self.writer.pending:
            self._commit()
        complete = self.writer.count >= target and not self.recorder.active
        require(complete or stop(), 'Case plan exhausted before target; preserve partial run for review')
        return dict(
            phase='COMPLETE' if complete else 'STOPPED',
            transitions=self.writer.count,
            target=target,
            completed_episodes=self.index,
            finish_episode=True,
        )
