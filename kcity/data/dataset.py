"""Transition schema (KC-DATA-v1), validation, atomic shard writer and dataset validation.

JSONL is authoritative for full State. NPZ is the same transitions, not a
second dataset. Only atomically committed shard directories count as data.
"""

from collections import Counter
from datetime import datetime
from copy import deepcopy
import gzip
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

import numpy as np

from kcity.env.config import digest, file_sha256, make_case, repository_path
from kcity.env.observation import (
    BINARY,
    CORRIDOR,
    CURRENT,
    OBS_DIM,
    OBSERVATION_ID,
    TLS_DIST,
    TLS_GREEN,
    TLS_RED,
    lane_mask,
)
from kcity.evaluation.metrics import EpisodeMetrics
from kcity.data.storage import (
    NEXT_CODEC,
    CHECKPOINT_MODE,
    encode_rows,
    decode_rows,
    save_external,
    sync_retention,
    verify_retention,
)

SCHEMA_ID = 'KC-DATA-v2'
EGO_COLUMNS = (
    'ego_x',
    'ego_y',
    'ego_speed',
    'ego_accel',
    'ego_angle_deg',
    'ego_lane',
    'ego_lane_count',
    'ego_route_progress_m',
)
EVENT_COLUMNS = ('collision', 'arrival', 'tls_crossing', 'yield_violation', 'lane_change', 'wrong_route')
END_CODES = dict(
    arrival=1, collision=2, red_entry=3, yield_violation=4, wrong_route=5, deadline=6, teleport=7, removal=8
)  # 0 = Episode continues
BASE_FIELDS = {
    'episode',
    't',
    'observation',
    'action_raw',
    'action',
    'reward',
    'terminated',
    'truncated',
    'state',
    'detected_vehicles',
    'event',
    'next_observation',
    'next_state',
}
# validate_pair()가 직전 행에서 읽는 필드. writer는 전체 행 대신 이것만 참조로 보관한다.
PAIR_FIELDS = (
    'episode_uid',
    't',
    'terminated',
    'truncated',
    'next_observation',
    'next_state',
    'next_detected_vehicles',
)
STATE_FIELDS = {
    'sim_tick',
    'sim_time_s',
    'ego_alive',
    'snapshot_valid',
    'ego_x',
    'ego_y',
    'ego_z',
    'ego_speed',
    'ego_accel',
    'ego_angle_deg',
    'ego_lane',
    'ego_lane_id',
    'ego_road_id',
    'ego_lane_pos',
    'ego_route_index',
    'ego_route_progress_m',
    'ego_distance_m',
    'vehicles',
    'signals',
    'traffic',
    'route_state',
    'quality',
}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def now():
    return datetime.now().astimezone().isoformat()


PLAN_SCHEMA = 'KC-PLAN-COMPACT-v1'


def compact_plan(plan):
    """RUN.json form of a plan: case keys + case_uid; cases are regenerated deterministically on load."""
    runtime = plan[0]['case']['runtime_variant'] if plan else None
    cases = []
    for entry in plan:
        case = entry['case']
        item = dict(
            namespace=case['namespace'],
            scenario_id=case['scenario_id'],
            case_index=case['case_index'],
            demand_multiplier=case['demand_multiplier'],
            case_uid=case['case_uid'],
            data_split=entry['data_split'],
        )
        if case['runtime_variant'] != runtime:
            item['runtime_variant'] = case['runtime_variant']
        cases.append(item)
    return dict(schema=PLAN_SCHEMA, runtime_variant=runtime, cases=cases)


def expand_plan(contract, plan):
    """Full plan (list of {case, data_split}) from either form; regenerated cases must keep their case_uid."""
    if isinstance(plan, list):
        return plan
    if plan.get('schema') != PLAN_SCHEMA:
        raise ValueError('Unsupported plan schema')
    result = []
    for item in plan['cases']:
        case = make_case(
            contract, item['namespace'], item['scenario_id'], item['case_index'], item['demand_multiplier']
        )
        case['runtime_variant'] = item.get('runtime_variant', plan['runtime_variant'])
        case['case_uid'] = digest({k: v for k, v in case.items() if k != 'case_uid'})
        if case['case_uid'] != item['case_uid']:
            raise ValueError('Plan case regenerated with a different identity')
        result.append(dict(case=case, data_split=item['data_split']))
    return result


def stored_config(config):
    """What RUN.json holds (compact plan); its digest is the run_config_sha256."""
    return dict(config, plan=compact_plan(expand_plan(config['contract'], config['plan'])))


def loaded_config(stored):
    """In-memory config with full plan cases, from RUN.json."""
    return dict(stored, plan=expand_plan(stored['contract'], stored['plan']))


def pid_alive(pid):
    """Whether a process with this pid exists (signal 0 only checks; nothing is delivered)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.partial-' + uuid.uuid4().hex)
    with temp.open('w') as f:
        f.write(json_text(value) + '\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def episode_uid(run_uid, index, case_uid):
    return digest_string(f'{run_uid}:{index}:{case_uid}')


def transition_uid(episode, t):
    return digest_string(f'{episode}:{t}')


def digest_string(value):
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def traffic_group(case):
    return digest(
        dict(scenario_id=case['scenario_id'], seeds=case['seeds'], contract_sha256=case['contract_sha256'])
    )


def observation_mask(o):
    return lane_mask(np.asarray(o, dtype=np.float32))


def enrich_state(state, interval, history, start_tick, dt=0.1):
    state = deepcopy(state)
    end = state['sim_tick']
    begin = max(start_tick, end - round(60 / dt))
    counts = sum(n for tick, n in history if begin < tick <= end)
    state['traffic'].update(
        departed_hv_interval=interval['departed_hv'],
        arrived_hv_interval=interval['arrived_hv'],
        realized_departures_window=dict(
            start_tick=begin,
            end_tick=end,
            observed_s=(end - begin) * dt,
            departures=counts,
            realized_vph=counts * 3600 / ((end - begin) * dt) if end > begin else None,
            scope='post-reset interval endpoints,up to60s',
        ),
    )
    return state


def make_transition(
    *,
    config,
    case,
    episode_index,
    t,
    attempt_uid,
    observation,
    detected,
    next_observation,
    next_detected,
    reward,
    terminated,
    truncated,
    info,
    start_tick,
    previous_interval,
    departure_history,
    policy_context=None,
):
    eid = episode_uid(config['run_uid'], episode_index, case['case_uid'])
    old_history = list(departure_history)
    new_history = old_history + [[info['sim_tick_tp1'], info['traffic_interval']['departed_hv']]]
    action = deepcopy(info['action'])
    split = config['plan'][episode_index]['data_split']
    row = dict(
        schema_id=SCHEMA_ID,
        observation_schema_id=OBSERVATION_ID,
        run_uid=config['run_uid'],
        case_uid=case['case_uid'],
        episode_uid=eid,
        attempt_uid=attempt_uid,
        transition_uid=transition_uid(eid, t),
        episode=episode_index,
        t=t,
        traffic_seed_group_uid=traffic_group(case),
        source_stage=config['source_stage'],
        data_split=split,
        policy_id='B0',
        policy_version=config['teacher']['id'],
        policy_checkpoint_sha256=config['teacher']['fingerprint'],
        policy_checkpoint_kind='rule_source_and_config',
        train_seed=None,
        scenario_id=case['scenario_id'],
        observation=np.asarray(observation, dtype=np.float32).tolist(),
        action_raw=info['action_raw'],
        action=action,
        action_mask=action['lane_mask'],
        reward=float(reward),
        reward_components=info['reward_components'],
        terminated=bool(terminated),
        truncated=bool(truncated),
        state=enrich_state(info['state'], previous_interval, old_history, start_tick),
        next_state=enrich_state(info['next_state'], info['traffic_interval'], new_history, start_tick),
        detected_vehicles=deepcopy(detected),
        next_detected_vehicles=deepcopy(next_detected),
        next_observation=np.asarray(next_observation, dtype=np.float32).tolist(),
        event=info['event'],
        events=info['events'],
        substep_samples=info['substep_samples'],
        traffic_interval=info['traffic_interval'],
        sim_tick_t=info['sim_tick_t'],
        sim_tick_tp1=info['sim_tick_tp1'],
        episode_start_tick=start_tick,
        episode_time_s=info['episode_time_s'],
        control_dt_s=info['control_dt_s'],
        executed_substeps=info['executed_substeps'],
        observation_valid=info['observation_valid'],
        next_observation_valid=info['next_observation_valid'],
        end_reason=info['end_reason'],
    )
    # Validation happens once, in ShardWriter.append(), which every collector uses.
    if config.get('online_policy'):
        if policy_context is None:
            raise ValueError('Online records require acting policy provenance')
        row.update(
            policy_id=config['online_policy']['method'],
            policy_version=config['online_policy']['version'],
            train_seed=config['online_policy']['seed'],
            policy_checkpoint_kind='acting_state_dict_sha256',
            policy_checkpoint_sha256=policy_context['behavior_sha'],
        )
        row['learning'] = dict(
            update_step=policy_context['update_step'], random_action=policy_context['random_action']
        )
    elif config.get('fixed_policy'):
        fixed = config['fixed_policy']
        row.update(
            policy_id=fixed['method'],
            policy_version=fixed['version'],
            train_seed=fixed['seed'],
            policy_checkpoint_kind='acting_state_dict_sha256',
            policy_checkpoint_sha256=fixed['policy_sha256'],
        )
    return row


def validate_row(row, config=None):
    """Raise ValueError on any contract violation; return the row's canonical JSON text."""

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    require(BASE_FIELDS <= row.keys(), 'Missing required transition fields')
    text = json_text(row)  # Reject nonfinite values anywhere, including full State.
    require(row['schema_id'] == SCHEMA_ID and row['observation_schema_id'] == OBSERVATION_ID, 'Wrong schema')
    for key in ['episode', 't']:
        require(type(row[key]) is int and row[key] >= 0, 'Invalid episode/t')
    require(row['transition_uid'] == transition_uid(row['episode_uid'], row['t']), 'Wrong transition UID')
    require(
        row['episode_uid'] == episode_uid(row['run_uid'], row['episode'], row['case_uid']),
        'Wrong episode UID',
    )
    for name in ['observation', 'next_observation']:
        a = np.asarray(row[name])
        require(a.shape == (OBS_DIM,) and np.isfinite(a).all() and (np.abs(a) <= 1).all(), 'Invalid ' + name)
        require(np.array_equal(a, a.astype(np.float32)), 'Observation was not stored as actual float32')
        if row['observation_valid' if name == 'observation' else 'next_observation_valid']:
            require(np.isin(a[BINARY], [0, 1]).all(), 'Invalid observation binary fields')
            signal = a[TLS_RED : TLS_GREEN + 1].sum()
            require(signal <= 1 and (signal or a[TLS_DIST] == 1), 'Signal one-hot/distance mismatch')
            for k in range(5):
                require(
                    0 <= a[CORRIDOR + 4 * k] <= 1 and -1 <= a[CORRIDOR + 4 * k + 2] <= 0,
                    'Front/rear distance sign mismatch',
                )
    raw = np.asarray(row['action_raw'], dtype=np.float32)
    bounded = np.asarray(row['action']['env_input'], dtype=np.float32)
    require(raw.shape == (2,), 'Invalid raw action')
    require(np.array_equal(np.clip(raw, -1, 1), bounded), 'Incorrect raw->clip transform')
    control = (
        config['contract']['protocol']['control']
        if config is not None
        else dict(max_accel_mps2=2.0, max_decel_mps2=4.5)
    )
    requested = float(bounded[0]) * (
        control['max_accel_mps2'] if bounded[0] >= 0 else control['max_decel_mps2']
    )
    require(
        math.isclose(row['action']['accel_request_mps2'], requested, abs_tol=1e-9),
        'Acceleration adapter mismatch',
    )
    a = row['action']
    lane = 1 if bounded[1] >= 0.5 else -1 if bounded[1] <= -0.5 else 0
    require(a['lane_change'] == lane, 'Incorrect lane command')
    require(a['accel_raw'] == bounded[0], 'Clipped action mismatch')
    mask = row['action_mask']
    require(len(mask) == 3 and all(type(x) is bool for x in mask) and mask[1], 'Invalid mask')
    require(mask == observation_mask(row['observation']) and mask == a['lane_mask'], 'Sampling mask mismatch')
    require(
        math.isclose(sum(row['reward_components'].values()), row['reward'], abs_tol=1e-10),
        'Reward component mismatch',
    )
    for name, tick in [('state', row['sim_tick_t']), ('next_state', row['sim_tick_tp1'])]:
        state = row[name]
        require(STATE_FIELDS <= state.keys(), 'Missing full State fields')
        require(
            state['sim_tick'] == tick and math.isclose(state['sim_time_s'], tick * 0.1, abs_tol=1e-7),
            'State/time misalignment',
        )
        vehicles = state['vehicles']
        ids = [v['id'] for v in vehicles]
        require(ids == sorted(set(ids)), 'Vehicle IDs not sorted/unique')
        for v in vehicles:
            require(
                {
                    'id',
                    'x',
                    'y',
                    'z',
                    'speed',
                    'lane',
                    'lane_id',
                    'road_id',
                    'lane_pos',
                    'accel_mps2',
                    'angle_deg',
                    'type_id',
                    'is_ego',
                }
                <= v.keys(),
                'Incomplete vehicle',
            )
        ego = [v for v in vehicles if v['is_ego']]
        require(len(ego) == int(state['ego_alive']), 'Ego alias/alive mismatch')
        require(
            state['traffic']['running_hv'] == len(vehicles) - len(ego),
            'HV count includes ego or omits vehicles',
        )
        if not ego:
            for k in ['ego_x', 'ego_y', 'ego_z', 'ego_speed', 'ego_lane']:
                require(state[k] is None, 'Fabricated missing-ego State')
        else:
            for k, vkey in [('ego_x', 'x'), ('ego_y', 'y'), ('ego_speed', 'speed'), ('ego_lane', 'lane')]:
                require(state[k] == ego[0][vkey], 'Ego and full-vehicle snapshot disagree')
    for state_key, detected_key in [('state', 'detected_vehicles'), ('next_state', 'next_detected_vehicles')]:
        vehicles = {v['id']: v for v in row[state_key]['vehicles']}
        for v in row[detected_key]:
            require(
                v['id'] in vehicles and not vehicles[v['id']]['is_ego'], 'Detected vehicle is absent or ego'
            )
            require(
                all(v[k] == vehicles[v['id']][k] for k in ['x', 'y', 'speed']),
                'Detected/full State time alignment mismatch',
            )
            require(
                v['relation'] in ['same_corridor', 'adjacent_corridor', 'crossing'],
                'Unknown detected relation',
            )
    require(
        row['event']['lane_before'] == row['state']['ego_lane']
        and row['event']['lane_after'] == row['next_state']['ego_lane'],
        'Lane event aliases disagree',
    )
    require(
        a['lane_change_executed'] == any(e['type'] == 'lane_change' for e in row['events']),
        'Requested/executed LC mismatch',
    )
    ticks = row['sim_tick_tp1'] - row['sim_tick_t']
    require(ticks == row['executed_substeps'] and 1 <= ticks <= 5, 'Invalid substep count')
    require(math.isclose(ticks * 0.1, row['control_dt_s'], abs_tol=1e-8), 'dt/tick mismatch')
    require(
        math.isclose(
            (row['sim_tick_tp1'] - row['episode_start_tick']) * 0.1, row['episode_time_s'], abs_tol=1e-7
        ),
        'Episode clock mismatch',
    )
    done = row['terminated'] or row['truncated']
    require(done or ticks == 5, 'Nonterminal partial control interval')
    require((row['end_reason'] is not None) == done, 'End reason/done mismatch')
    if not row['next_observation_valid']:
        require(
            np.count_nonzero(row['next_observation']) == 0, 'Invalid terminal observation must be absorbing'
        )
    if not row['next_state']['ego_alive']:
        require(not row['next_observation_valid'] and done, 'Missing ego was not terminated')
    require(
        row['event']['collided'] == any(e['type'] == 'collision' for e in row['events']),
        'Collision event mismatch',
    )
    require(
        row['event']['arrived'] == any(e['type'] == 'arrival' for e in row['events']),
        'Arrival event mismatch',
    )
    if config is not None:
        require(row['run_uid'] == config['run_uid'], 'Unknown run UID')
        entry = config['plan'][row['episode']]
        case = entry['case']
        require(
            row['case_uid'] == case['case_uid'] and row['traffic_seed_group_uid'] == traffic_group(case),
            'Case/seed group provenance mismatch',
        )
        require(row['data_split'] == entry['data_split'], 'Split differs from case manifest')
        online = config.get('online_policy')
        if online:
            require(
                row['policy_id'] == online['method']
                and row['policy_version'] == online['version']
                and row['train_seed'] == online['seed'],
                'Online policy/seed mismatch',
            )
            checksum = row['policy_checkpoint_sha256']
            require(
                isinstance(checksum, str)
                and len(checksum) == 64
                and all(c in '0123456789abcdef' for c in checksum),
                'Invalid acting-policy hash',
            )
            require(
                row['policy_checkpoint_kind'] == 'acting_state_dict_sha256', 'Missing acting-policy hash kind'
            )
            learning = row['learning']
            require(
                type(learning['update_step']) is int
                and learning['update_step'] >= 0
                and type(learning['random_action']) is bool,
                'Invalid online learner provenance',
            )
        elif config.get('fixed_policy'):
            fixed = config['fixed_policy']
            require(
                row['policy_id'] == fixed['method']
                and row['policy_version'] == fixed['version']
                and row['train_seed'] == fixed['seed'],
                'Fixed policy/seed mismatch',
            )
            require(
                row['policy_checkpoint_kind'] == 'acting_state_dict_sha256'
                and row['policy_checkpoint_sha256'] == fixed['policy_sha256'],
                'Fixed policy weights hash mismatch',
            )
        else:
            require(
                row['policy_checkpoint_sha256'] == config['teacher']['fingerprint'], 'Unknown teacher hash'
            )
            require(
                row['policy_id'] == 'B0' and row['policy_version'] == config['teacher']['id'],
                'Unknown policy/version',
            )
        require(
            row['source_stage'] == config['source_stage'] and row['scenario_id'] == case['scenario_id'],
            'Source stage/scenario differs from manifest',
        )
    return text


def validate_pair(previous, row):
    if previous is None:
        if row['t'] != 0:
            raise ValueError('Dataset begins inside an unrecorded Episode')
        return
    if previous['episode_uid'] == row['episode_uid']:
        if (
            previous['terminated']
            or previous['truncated']
            or row['t'] != previous['t'] + 1
            or previous['next_observation'] != row['observation']
            or previous['next_state'] != row['state']
            or previous['next_detected_vehicles'] != row['detected_vehicles']
        ):
            raise ValueError('Transition continuity/reset/next-state mismatch')
    elif not (previous['terminated'] or previous['truncated']) or row['t'] != 0:
        raise ValueError('Episode changed without a terminal transition')


def create_index(path):
    db = sqlite3.connect(path)
    db.executescript(
        'CREATE TABLE rows(uid TEXT PRIMARY KEY,episode INTEGER,t INTEGER,UNIQUE(episode,t));'
        'CREATE TABLE groups(gid TEXT PRIMARY KEY,split TEXT);'
        'CREATE TABLE episodes(eid TEXT PRIMARY KEY,split TEXT);'
    )
    return db


def index_row(db, row):
    for table, key in [('groups', row['traffic_seed_group_uid']), ('episodes', row['episode_uid'])]:
        result = db.execute(
            f'SELECT split FROM {table} WHERE ' + ('gid' if table == 'groups' else 'eid') + '=?', (key,)
        ).fetchone()
        if result and result[0] != row['data_split']:
            raise ValueError('Episode/traffic seed group leaks across splits')
        db.execute(f'INSERT OR IGNORE INTO {table} VALUES (?,?)', (key, row['data_split']))
    db.execute('INSERT INTO rows VALUES (?,?,?)', (row['transition_uid'], row['episode'], row['t']))


def numeric_view(rows):
    result = {}
    n = len(rows)
    for key, width in [('observation', OBS_DIM), ('next_observation', OBS_DIM), ('action_raw', 2)]:
        result[key] = np.asarray([r[key] for r in rows], np.float32).reshape(n, width)
    result['action_env_input'] = np.asarray([r['action']['env_input'] for r in rows], np.float32).reshape(
        n, 2
    )
    result['action_mask'] = np.asarray([r['action_mask'] for r in rows], bool).reshape(n, 3)
    for key, dtype in [
        ('reward', np.float32),
        ('terminated', bool),
        ('truncated', bool),
        ('episode', np.int64),
        ('t', np.int64),
        ('sim_tick_t', np.int64),
        ('sim_tick_tp1', np.int64),
        ('control_dt_s', np.float64),
        ('observation_valid', bool),
        ('next_observation_valid', bool),
    ]:
        result[key] = np.asarray([r[key] for r in rows], dtype)
    result['lane_change'] = np.asarray([r['action']['lane_change'] for r in rows], np.int8)
    for key in ['transition_uid', 'episode_uid', 'case_uid', 'traffic_seed_group_uid']:
        result[key] = np.asarray([r[key] for r in rows], dtype='U64')
    result['data_split'] = np.asarray([r['data_split'] for r in rows], dtype='U32')
    xy = []
    offsets = [0]
    for r in rows:
        xy.extend([[v['x'], v['y']] for v in r['detected_vehicles']])
        offsets.append(len(xy))
    result['detected_xy'] = np.asarray(xy, np.float64).reshape(-1, 2)
    result['detected_offsets'] = np.asarray(offsets, np.int64)
    # Numeric State columns (absolute values; missing ego = NaN), so the table needs no string parsing.
    ego = []
    for r in rows:
        s = r['state']
        ego.append([np.nan if s[k] is None else s[k] for k in EGO_COLUMNS])
    result['ego_state'] = np.asarray(ego, np.float64).reshape(n, len(EGO_COLUMNS))
    result['event_flags'] = np.asarray(
        [[any(e['type'] == kind for e in r['events']) for kind in EVENT_COLUMNS] for r in rows], bool
    ).reshape(n, len(EVENT_COLUMNS))
    result['end_code'] = np.asarray([END_CODES.get(r['end_reason'], 0) for r in rows], np.int8)
    return result


def shard_directories(root):
    folders = sorted((Path(root) / 'shards').glob('shard-*'))
    for i, p in enumerate(folders):
        if p.name != f'shard-{i:06d}' or not (p / 'SHARD.json').is_file():
            raise ValueError('Missing/uncommitted shard in committed namespace')
    return folders


def read_shard(folder):
    folder = Path(folder)
    manifest = json.loads((folder / 'SHARD.json').read_text())
    files = {
        str(p.relative_to(folder)): file_sha256(p)
        for p in folder.rglob('*')
        if p.is_file() and p.name != 'SHARD.json'
    }
    if files != manifest['files']:
        raise ValueError('Shard file set/SHA mismatch')
    with gzip.open(folder / 'transitions.jsonl.gz', 'rt') as f:
        if manifest.get('storage_codec') != NEXT_CODEC:
            raise ValueError('Unsupported data storage codec')
        yield from decode_rows(json.loads(line) for line in f)


class ShardWriter:
    def __init__(self, root, config, *, resume=False, shard_rows=25000):
        if config.get('storage_codec') != NEXT_CODEC:
            raise ValueError('Unsupported data storage codec')
        self.root = Path(root)
        self.config = deepcopy(config)
        self.shard_rows = shard_rows
        self.config['writer'] = dict(shard_rows=shard_rows)
        self.config['plan'] = expand_plan(self.config['contract'], self.config['plan'])
        config = self.config
        self.stored = stored_config(self.config)
        self.config_sha256 = digest(self.stored)  # the config never changes during a run
        if not isinstance(shard_rows, int) or isinstance(shard_rows, bool) or shard_rows < 1:
            raise ValueError('Positive shard_rows required')
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / 'RUN.json').exists() and any(self.root.iterdir()):
            raise FileExistsError('Refusing a nonempty unrecognized output directory')
        self.lock = self.root / '.writer.lock'
        self.attempt_uid = uuid.uuid4().hex
        self.db = None
        self.journal = None
        self.last = None
        self.count = 0
        self.pending = 0
        self.buffer = []
        if self.lock.exists():
            old = json.loads(self.lock.read_text())
            if pid_alive(old['pid']):
                raise RuntimeError('Another writer owns this dataset')
            if not resume:
                raise RuntimeError('Stale writer lock requires explicit resume')
            q = self.root / 'quarantine'
            q.mkdir(exist_ok=True)
            self.lock.rename(q / ('stale-lock-' + self.attempt_uid + '.json'))
        fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as f:
            f.write(json_text(dict(pid=os.getpid(), attempt_uid=self.attempt_uid)))
        try:
            manifest = self.root / 'RUN.json'
            if manifest.exists():
                if not resume or digest(json.loads(manifest.read_text())) != self.config_sha256:
                    raise ValueError('Run config changed or resume was not explicit')
            else:
                if resume:
                    raise ValueError('Cannot resume a missing run')
                for asset in config.get('asset_snapshots', {}).values():
                    if file_sha256(repository_path(asset['path'])) != asset['sha256']:
                        raise ValueError('Map/route asset changed')
                atomic_json(manifest, self.stored)
            (self.root / 'shards').mkdir(exist_ok=True)
            partial = self.root / 'partial'
            if partial.exists():
                # The SQLite index is derived data rebuilt below; keep only uncommitted rows/staging.
                (partial / 'index.sqlite').unlink(missing_ok=True)
                journal = partial / 'current.jsonl'
                if journal.exists() and journal.stat().st_size == 0:
                    journal.unlink()
                if any(partial.iterdir()):
                    q = self.root / 'quarantine'
                    q.mkdir(exist_ok=True)
                    partial.rename(q / ('partial-' + self.attempt_uid))
                else:
                    partial.rmdir()
            partial.mkdir()
            self.partial = partial
            index = partial / 'index.sqlite'
            self.db = create_index(index)
            self.folders = shard_directories(self.root)
            self.shard_sha256 = [file_sha256(p / 'SHARD.json') for p in self.folders]
            for folder in self.folders:
                for row in read_shard(folder):
                    validate_row(row, config)
                    validate_pair(self.last, row)
                    index_row(self.db, row)
                    self.last = row
                    self.count += 1
            self.db.commit()
            self.journal = (partial / 'current.jsonl').open('w')
            self.refresh_release()
            if self.external:
                sync_retention(self.root, self.folders, self.config['checkpoint_policy'])
        except BaseException:
            self.close()
            raise

    @property
    def external(self):
        """Online RL data: each shard references a separately retained learner bundle."""
        return self.config.get('checkpoint_policy', {}).get('mode') == CHECKPOINT_MODE

    def append(self, row):
        text = validate_row(row, self.config)
        validate_pair(self.last, row)
        index_row(self.db, row)
        self.journal.write(text + '\n')
        self.journal.flush()
        self.buffer.append(row)  # the journal is for crash recovery; commit uses these rows (<= shard_rows)
        self.last = {k: row[k] for k in PAIR_FIELDS}
        self.pending += 1

    def commit(self, checkpoint, completed_episodes, save_environment=None):
        if not self.pending:
            return None
        if self.external:
            if save_environment is None:
                raise ValueError('Online shard requires a learner checkpoint')
            save_learner, count = save_environment, self.count + self.pending
            save_environment = lambda stub: save_external(self.root, stub, save_learner, count)
        self.journal.flush()
        os.fsync(self.journal.fileno())
        self.journal.close()
        staging = self.partial / ('commit-' + uuid.uuid4().hex)
        staging.mkdir()
        rows = self.buffer
        if len(rows) != self.pending:
            raise ValueError('Buffered row count mismatch')
        with gzip.GzipFile(filename=str(staging / 'transitions.jsonl.gz'), mode='wb', mtime=0) as stream:
            for row in encode_rows(rows):
                stream.write((json_text(row) + '\n').encode())
        np.savez_compressed(staging / 'numeric.npz', **numeric_view(rows))
        with gzip.GzipFile(filename=str(staging / 'events.jsonl.gz'), mode='wb', mtime=0) as stream:
            for row in rows:
                for index, event in enumerate(row['events']):
                    item = dict(
                        episode_uid=row['episode_uid'],
                        t=row['t'],
                        sim_tick=event['sim_tick'],
                        event_uid=digest(
                            dict(transition_uid=row['transition_uid'], index=index, event=event)
                        ),
                        event=event,
                    )
                    stream.write((json_text(item) + '\n').encode())
        atomic_json(staging / 'collector.json', checkpoint)
        if save_environment is not None:
            save_environment(staging / 'environment')
        manifest = dict(
            schema_id=SCHEMA_ID,
            rows=len(rows),
            first_uid=rows[0]['transition_uid'],
            last_uid=rows[-1]['transition_uid'],
            split_counts=dict(Counter(r['data_split'] for r in rows)),
            completed_episodes=completed_episodes,
            run_config_sha256=self.config_sha256,
            storage_codec=NEXT_CODEC,
            files={str(p.relative_to(staging)): file_sha256(p) for p in staging.rglob('*') if p.is_file()},
        )
        atomic_json(staging / 'SHARD.json', manifest)
        for file in staging.rglob('*'):
            if file.is_file():
                with file.open('rb') as f:
                    os.fsync(f.fileno())
        target = self.root / 'shards' / f'shard-{len(self.folders):06d}'
        staging.rename(target)
        self.db.commit()
        self.count += self.pending
        self.pending = 0
        self.buffer = []
        self.folders.append(target)
        self.shard_sha256.append(file_sha256(target / 'SHARD.json'))
        (self.partial / 'current.jsonl').unlink()
        self.journal = (self.partial / 'current.jsonl').open('w')
        self.refresh_release()
        if self.external:
            sync_retention(self.root, self.folders, self.config['checkpoint_policy'])
        return target

    def refresh_release(self):
        shards = [
            dict(path=str(p.relative_to(self.root)), manifest_sha256=sha)
            for p, sha in zip(self.folders, self.shard_sha256)
        ]
        body = dict(
            schema_id=SCHEMA_ID,
            run_uid=self.config['run_uid'],
            run_config_sha256=self.config_sha256,
            committed_transitions=self.count,
            shards=shards,
            eligible_for_research_training=bool(self.config.get('eligible_for_research_training')),
        )
        atomic_json(self.root / 'RELEASE.json', dict(body, data_id=digest(body)))

    def last_checkpoint(self):
        if not self.folders:
            return None, None
        return json.loads((self.folders[-1] / 'collector.json').read_text()), self.folders[-1]

    def close(self):
        if self.journal is not None:
            self.journal.close()
            self.journal = None
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock.exists():
            self.lock.unlink()


def validate_dataset(root):
    root = Path(root)
    stored = json.loads((root / 'RUN.json').read_text())
    release = json.loads((root / 'RELEASE.json').read_text())
    body = {k: v for k, v in release.items() if k != 'data_id'}
    config_sha256 = digest(stored)
    config = loaded_config(stored)
    if release['data_id'] != digest(body) or release['run_config_sha256'] != config_sha256:
        raise ValueError('Release/run manifest mismatch')
    folders = shard_directories(root)
    if release['shards'] != [
        dict(path=str(p.relative_to(root)), manifest_sha256=file_sha256(p / 'SHARD.json')) for p in folders
    ]:
        raise ValueError('Release index is stale or incomplete; recover writer before reading')
    situations = Counter()
    counts = Counter()
    events = Counter()
    episodes = []
    previous = None
    n = 0
    tracker = None
    observed_episodes = {}
    with tempfile.TemporaryDirectory(prefix='kcity-dq-') as temp:
        db = create_index(Path(temp) / 'index.sqlite')
        try:
            for folder in folders:
                rows = list(read_shard(folder))
                manifest = json.loads((folder / 'SHARD.json').read_text())
                if len(rows) != manifest['rows'] or manifest['run_config_sha256'] != config_sha256:
                    raise ValueError('Shard row/config mismatch')
                expected = numeric_view(rows)
                with np.load(folder / 'numeric.npz', allow_pickle=False) as numeric:
                    if set(numeric.files) != set(expected):
                        raise ValueError('NPZ key set mismatch')
                    for key, value in expected.items():
                        if numeric[key].dtype != value.dtype or not np.array_equal(numeric[key], value):
                            raise ValueError('JSON/NPZ mismatch: ' + key)
                expected_events = sum(len(r['events']) for r in rows)
                with gzip.open(folder / 'events.jsonl.gz', 'rt') as f:
                    event_rows = [json.loads(line) for line in f]
                if len(event_rows) != expected_events:
                    raise ValueError('Event sidecar count mismatch')
                expected_event_rows = [
                    dict(
                        episode_uid=r['episode_uid'],
                        t=r['t'],
                        sim_tick=e['sim_tick'],
                        event_uid=digest(dict(transition_uid=r['transition_uid'], index=i, event=e)),
                        event=e,
                    )
                    for r in rows
                    for i, e in enumerate(r['events'])
                ]
                if event_rows != expected_event_rows:
                    raise ValueError('Event sidecar content mismatch')
                episodes.extend(manifest['completed_episodes'])
                for row in rows:
                    validate_row(row, config)
                    validate_pair(previous, row)
                    index_row(db, row)
                    previous = row
                    n += 1
                    counts[row['data_split']] += 1
                    events.update(e['type'] for e in row['events'])
                    situations['standstill_decisions'] += (
                        row['state']['ego_speed'] is not None and row['state']['ego_speed'] < 0.1
                    )
                    situations['front_neighbor_decisions'] += row['observation'][CORRIDOR + 4 * CURRENT] < 1
                    situations['red_exposure_decisions'] += row['observation'][TLS_RED] > 0.5
                    situations['lane_change_requests'] += row['action']['lane_change'] != 0
                    situations['rejected_requests'] += bool(row['action']['known_rejection_reasons'])
                    situations['detected_vehicle_entries'] += len(row['detected_vehicles'])
                    if row['t'] == 0:
                        tracker = EpisodeMetrics(
                            config['plan'][row['episode']]['case'], {'state': row['state']}
                        )
                    tracker.add(row['reward'], row['terminated'], row['truncated'], row)
                    if row['terminated'] or row['truncated']:
                        observed_episodes[row['episode_uid']] = tracker.finish()
                        tracker = None
            if len({e['episode_uid'] for e in episodes}) != len(episodes):
                raise ValueError('Duplicate completed Episode summary')
            if n != release['committed_transitions']:
                raise ValueError('Committed unique count mismatch')
            declared = {e['episode_uid']: e['metrics'] for e in episodes}
            if declared != observed_episodes:
                raise ValueError('Episode summary/BC eligibility differs from raw event trace')
        finally:
            db.close()
    retention = None
    if config.get('checkpoint_policy', {}).get('mode') == CHECKPOINT_MODE:
        retention = verify_retention(root, folders, config['checkpoint_policy'])
    return dict(
        passed=True,
        schema_id=SCHEMA_ID,
        data_id=release['data_id'],
        unique_transitions=n,
        committed_shards=len(folders),
        split_counts=dict(counts),
        event_counts=dict(events),
        situation_counts=dict(situations),
        episodes=episodes,
        retained_learner_checkpoints=len(retention['retained']) if retention else None,
        incomplete_partial_present=(root / 'partial/current.jsonl').exists()
        and (root / 'partial/current.jsonl').stat().st_size > 0,
    )
