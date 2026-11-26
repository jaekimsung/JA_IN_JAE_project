"""Environment contract (configs/kcity/v2_1), case/seed generation and file hashing. Starts no SUMO process."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / 'configs/kcity/v2_1/protocol.json'


class ContractError(ValueError):
    pass


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def repository_path(name):
    path = Path(name)
    result = (ROOT / path).resolve()
    if path.is_absolute() or not result.is_relative_to(ROOT):
        raise ContractError('Asset must be a repository-relative path: ' + name)
    return result


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ContractError(name + ' must be numeric')
    if not math.isfinite(value) or value <= 0:
        raise ContractError(name + ' must be positive and finite')


def load_contract(path=DEFAULT_PROTOCOL):
    protocol = json.loads(Path(path).read_text(encoding='utf-8'))
    if protocol.get('schema_id') != 'KC-PROTOCOL-v1':
        raise ContractError('Unsupported protocol schema')
    for name, ref in dict(protocol['assets'], scenarios=protocol['scenario_manifest']).items():
        asset = repository_path(ref['path'])
        if not asset.is_file() or file_sha256(asset) != ref['sha256']:
            raise ContractError('Pinned file missing or changed: ' + name)
    scenarios = json.loads(repository_path(protocol['scenario_manifest']['path']).read_text(encoding='utf-8'))
    if scenarios.get('schema_id') != 'KC-SCENARIOS-v2':
        raise ContractError('Unsupported scenario schema')
    spec = dict(protocol=protocol, scenario_manifest=scenarios)
    validate_settings(spec)
    return spec


def validate_settings(spec):
    p, s = spec['protocol'], spec['scenario_manifest']
    for name in ['sumo_step_s', 'control_step_s']:
        positive(p['timing'][name], name)
    steps = p['timing']['substeps']
    if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
        raise ContractError('substeps must be a positive integer')
    if not math.isclose(p['timing']['sumo_step_s'] * steps,
                        p['timing']['control_step_s'], abs_tol=1e-12):
        raise ContractError('Control interval does not equal sum of SUMO ticks')
    positive(p['timing']['warmup_s'], 'warmup_s')
    for name in ['max_accel_mps2', 'max_decel_mps2', 'speed_cap_mps',
                 'lane_command_duration_s', 'lane_cooldown_s']:
        positive(p['control'][name], name)
    for name, upper in [('speed_mode', 127), ('lane_change_mode', 4095)]:
        value = p['control'][name]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
            raise ContractError('Invalid control bitset: ' + name)
    if p['training']['enabled'] or p['research_settings_frozen']:
        raise ContractError('Environment contract must not set training/frozen flags; experiment settings live in configs/kcity/v2_1/experiment.json')
    if p['control']['longitudinal_adapter'] != 'setAcceleration':
        raise ContractError('Longitudinal adapter must be setAcceleration')
    if p['seed']['algorithm'] != 'sha256_component_streams_v1':
        raise ContractError('Unsupported seed algorithm')
    namespace_values = list(p['seed']['namespaces'].values())
    if len(namespace_values) != len(set(namespace_values)):
        raise ContractError('Seed namespaces must be disjoint')
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in namespace_values):
        raise ContractError('Namespaces must be nonnegative integers')
    root_seed = p['seed']['root_seed']
    if isinstance(root_seed, bool) or not isinstance(root_seed, int) or root_seed < 0:
        raise ContractError('root_seed must be a nonnegative integer')
    ids = [r['id'] for r in s['scenarios']]
    if sorted(ids) != ['A', 'B', 'C']:
        raise ContractError('Exactly one A, B, and C scenario is required')
    if s['mixture_per_10_episodes'] != dict(A=3, B=3, C=4):
        raise ContractError('Task mixture must preserve the documented 3/3/4 block')
    if set(s['scenario_codes']) != set(ids) or len(set(s['scenario_codes'].values())) != 3:
        raise ContractError('Scenario codes must be distinct')
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0
           for x in s['scenario_codes'].values()):
        raise ContractError('Scenario codes must be nonnegative integers')
    traffic = p['traffic']
    if traffic['request_generator'] != 'poisson_split_streams_v1':
        raise ContractError('Unsupported traffic generator')
    positive(traffic['baseline_requested_vph'], 'baseline_requested_vph')
    weights = traffic['vehicle_type_weights']
    if len(weights) != len(traffic['vehicle_types']) or len(weights) != 4:
        raise ContractError('Need four type weights')
    for weight in weights:
        positive(weight, 'type probability')
    if not math.isclose(sum(weights), 1.0, abs_tol=1e-12):
        raise ContractError('Type weights must sum to one')
    for value in traffic['evaluation_demand_multipliers']:
        positive(value, 'evaluation_demand_multiplier')


def scenario(spec, scenario_id):
    for row in spec['scenario_manifest']['scenarios']:
        if row['id'] == scenario_id:
            return deepcopy(row)
    raise ContractError('Unknown scenario: ' + str(scenario_id))


def case_seeds(spec, namespace, scenario_id, case_index):
    if isinstance(case_index, bool) or not isinstance(case_index, int) or case_index < 0:
        raise ContractError('case_index must be a nonnegative integer')
    p = spec['protocol']['seed']
    if namespace not in p['namespaces']:
        raise ContractError('Unknown seed namespace: ' + namespace)
    scenario(spec, scenario_id)
    base = dict(algorithm=p['algorithm'], root_seed=p['root_seed'],
                namespace=p['namespaces'][namespace],
                scenario=spec['scenario_manifest']['scenario_codes'][scenario_id],
                case_index=case_index)
    # Independent integer seeds are never drawn from policy/global RNG state.
    return {key: int(digest(dict(base, component=key)), 16) % (2**31 - 1)
            for key in p['components']}


def make_case(spec, namespace, scenario_id, case_index, demand_multiplier=1.0):
    positive(demand_multiplier, 'demand_multiplier')
    row = scenario(spec, scenario_id)
    seeds = case_seeds(spec, namespace, scenario_id, case_index)
    body = dict(protocol_id=spec['protocol']['protocol_id'], contract_sha256=digest(spec),
                namespace=namespace, case_index=case_index, scenario_id=scenario_id,
                scenario=row, seeds=seeds,
                requested_lambda_vph=spec['protocol']['traffic']['baseline_requested_vph'] * demand_multiplier,
                demand_multiplier=demand_multiplier)
    return dict(body, case_uid=digest(body))


def traffic_requests(spec, case, route_ids, duration_s=None):
    """Requested Poisson arrivals; not SUMO departures, samples or feasibility proof."""
    validate_settings(spec)
    routes = sorted(set(route_ids))
    if not routes:
        raise ContractError('Background route pool is empty')
    duration = duration_s if duration_s is not None else (
        spec['protocol']['timing']['warmup_s'] + case['scenario']['episode_limit_s'])
    positive(duration, 'duration_s')
    positive(case['requested_lambda_vph'], 'requested_lambda_vph')
    arrivals, od, kind = [random.Random(case['seeds'][k]) for k in ['arrivals', 'od', 'vehicle_type']]
    traffic = spec['protocol']['traffic']
    rows, now = [], 0.0
    while True:
        now += arrivals.expovariate(case['requested_lambda_vph'] / 3600.0)
        if now >= duration:
            break
        index = len(rows)
        rows.append(dict(request_id=case['case_uid'][:16] + f'-hv-{index:06d}',
            requested_depart_s=round(now, 9), route_id=od.choice(routes),
            vehicle_type=kind.choices(traffic['vehicle_types'], weights=traffic['vehicle_type_weights'])[0],
            depart_lane=traffic['insertion_lane'], depart_speed_mps=traffic['departure_speed_mps']))
    return rows


def git_info():
    """Code version for provenance (recorded, never compared on resume)."""
    import subprocess

    def run(*args):
        try:
            return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    status = run('status', '--porcelain', '--untracked-files=no')
    return dict(commit=run('rev-parse', 'HEAD'), dirty=None if status is None else bool(status))
