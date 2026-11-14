"""KC-03 case panels and event-derived metrics; no policy training or retries.

This is separate from the legacy single-road evaluator. Unknown classifications
remain unknown; performance failures stay in the valid-case denominator.
"""
from collections import Counter
from copy import deepcopy
import math
import hashlib
import numpy as np

from env.kcity_config import digest, make_case

METRIC_VERSION = 'KC-METRICS-v1-candidate'
REASONS = ('collision', 'red_entry', 'wrong_route', 'teleport', 'removal',
           'arrival', 'deadline', 'external_limit', 'policy_invalid_action', 'step_guard')


def make_panel(contract, namespace, counts=None, demand_multiplier=1.0):
    """Pure generation only. Final cases are not executed by this function."""
    counts = {'A': 30, 'B': 30, 'C': 40} if counts is None else counts
    cases = []
    for sid, count in sorted(counts.items()):
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError('Case counts must be nonnegative integers')
        for index in range(count):
            cases.append(make_case(contract, namespace, sid, index, demand_multiplier))
    body = dict(namespace=namespace, counts=counts, demand_multiplier=demand_multiplier,
                cases=cases, contract_sha256=digest(contract))
    return dict(body, panel_sha256=digest(body))


class EpisodeMetrics:
    def __init__(self, case, reset_info):
        self.case = deepcopy(case)
        self.initial = deepcopy(reset_info['state'])
        self.events, self.samples, self.quality_errors = [], [], []
        self.steps = 0
        self.reward = self.elapsed = 0.0
        self.last_tick = self.initial['sim_tick']
        self.last = self.initial
        self.end_reason = None
        self.commands = Counter()
        self.rejections = Counter()
        self.clipped = self.unknown_overrides = self.departed = 0
        self.route_valid = self.initial['route_state']['route_valid']

    def add(self, reward, terminated, truncated, info):
        if self.end_reason is not None:
            raise ValueError('Metrics cannot accept a row after episode end')
        if info['sim_tick_t'] != self.last_tick:
            self.quality_errors.append('tick_discontinuity_or_duplicate')
        delta = info['sim_tick_tp1'] - info['sim_tick_t']
        samples = info['substep_samples']
        if (delta != info['executed_substeps'] or delta != len(samples) or
                [s['sim_tick'] for s in samples] != list(range(info['sim_tick_t']+1, info['sim_tick_tp1']+1)) or
                not math.isclose(sum(s['dt_s'] for s in samples), info['control_dt_s'], abs_tol=1e-8)):
            self.quality_errors.append('substep_alignment')
        self.last_tick = info['sim_tick_tp1']
        self.steps += 1
        self.reward += float(reward)
        self.elapsed = info['episode_time_s']
        self.events.extend(deepcopy(info['events']))
        self.samples.extend(deepcopy(samples))
        self.last = deepcopy(info['next_state'])
        self.route_valid &= self.last['route_state']['route_valid']
        action = info['action']
        self.commands[action['lane_change']] += 1
        self.rejections.update(action['known_rejection_reasons'])
        self.clipped += any(a != b for a, b in zip(info['action_raw'], action['env_input']))
        self.unknown_overrides += action['sumo_override_reason'] == 'unknown'
        self.departed += info['traffic_interval']['departed_hv']
        if terminated or truncated:
            self.end_reason = info['end_reason']
            if self.end_reason not in REASONS:
                self.quality_errors.append('unknown_end_reason')

    def finish(self, *, failure_reason=None, infrastructure_error=None):
        events = self.events
        counts = Counter(e['type'] for e in events)
        crossings = [e for e in events if e['type'] == 'tls_crossing']
        unknown = sum(not e['classification_valid'] for e in crossings)
        reds = sum(e.get('red_entry', False) for e in crossings)
        collision = counts['collision'] > 0
        wrong = counts['wrong_route'] > 0 or not self.route_valid
        correct_goal = any(e['type'] == 'arrival' and e['correct_goal'] for e in events)
        completion = (correct_goal and not wrong and
                      self.elapsed <= self.case['scenario']['episode_limit_s'] + 1e-8)
        primary = next((r for r in REASONS if
                        (r == 'red_entry' and reds) or counts[r]),
                       failure_reason or self.end_reason)
        if primary is None and infrastructure_error is None:
            raise ValueError('Unfinished episode must have an explicit failure reason')
        if not math.isclose(sum(s['dt_s'] for s in self.samples), self.elapsed, abs_tol=1e-7):
            self.quality_errors.append('elapsed_sample_coverage')
        known_speed = [s for s in self.samples if s['speed_mps'] is not None]
        speed_time = sum(s['dt_s'] for s in known_speed)
        gaps = [s for s in self.samples if s['leader_gap_m'] is not None]
        gap_time = sum(s['dt_s'] for s in gaps)
        hv_integral = sum(s['dt_s']*s['running_hv'] for s in self.samples)
        progress = self.last['ego_route_progress_m']
        # The fixed geometry length is supplied by reset, not inferred from a
        # changing lane length or from traveled distance.
        length = self.initial['route_state'].get('route_length_m')
        if completion and length is not None:
            progress = length
        return dict(metric_version=METRIC_VERSION, requested_case_uid=self.case['case_uid'],
            scenario_id=self.case['scenario_id'], namespace=self.case['namespace'],
            case_index=self.case['case_index'], demand_multiplier=self.case['demand_multiplier'],
            attempt_valid=infrastructure_error is None, infrastructure_invalid_reason=infrastructure_error,
            performance_failure_reason=failure_reason, primary_end_reason=primary,
            completion=bool(completion),
            compliant_completion=None if unknown else bool(completion and not collision and not reds),
            signal_classification_valid=not unknown,
            supported_rule_checks=['red_entry'], full_traffic_rule_compliance_verified=False,
            ever_AV_collision=collision, arrival_event=bool(counts['arrival']), correct_goal=correct_goal,
            correct_route=not wrong, red_entry_count=reds, tls_crossing_count=len(crossings),
            tls_crossing_unknown_count=unknown, valid_tls_crossing_count=len(crossings)-unknown,
            teleport=bool(counts['teleport']), removal=bool(counts['removal']), deadline=bool(counts['deadline']),
            elapsed_s=self.elapsed, decision_count=self.steps, ep_return=self.reward,
            moving_s=sum(s['dt_s'] for s in known_speed if s['speed_mps'] >= .1),
            standstill_s=sum(s['dt_s'] for s in known_speed if s['speed_mps'] < .1),
            speed_observed_s=speed_time, speed_unobserved_s=max(0., self.elapsed-speed_time),
            mean_speed_mps=sum(s['dt_s']*s['speed_mps'] for s in known_speed)/speed_time if speed_time else None,
            mean_gap_m=sum(s['dt_s']*s['leader_gap_m'] for s in gaps)/gap_time if gap_time else None,
            min_gap_m=min((s['leader_gap_m'] for s in gaps), default=None),
            leader_present_fraction=gap_time/self.elapsed if self.elapsed else None,
            unjustified_wait_s=None, route_progress_m=progress, route_length_m=length,
            completion_fraction=max(0., min(1., progress/length)) if progress is not None and length else None,
            HV_start=self.initial['traffic']['running_hv'],
            HV_min=min((s['running_hv'] for s in self.samples), default=None),
            HV_time_weighted_mean=hv_integral/self.elapsed if self.elapsed else None,
            pending_max=max((s['pending_hv'] for s in self.samples), default=None),
            actual_HV_departures_post_reset=self.departed,
            requested_lambda_vph=self.initial['traffic']['requested_lambda_vph'],
            commands_left=self.commands[1], commands_right=self.commands[-1],
            executed_LC_count=counts['lane_change'], known_rejection_counts=dict(self.rejections),
            accel_or_lane_clip_fraction=self.clipped/self.steps if self.steps else None,
            unknown_override_count=self.unknown_overrides,
            data_quality_valid=not self.quality_errors, quality_errors=list(self.quality_errors),
            penalized_time_s=self.elapsed if completion else self.case['scenario']['episode_limit_s'])


def aggregate(records, n_planned):
    """Rates use valid cases, including policy failures; never round to pass."""
    if n_planned < len(records):
        raise ValueError('More records than planned cases; keep retries in a separate attempt ledger')
    if len({r['requested_case_uid'] for r in records}) != len(records):
        raise ValueError('Duplicate cases cannot increase the denominator')
    valid = [r for r in records if r['attempt_valid']]
    n = len(valid)
    total = lambda key: sum(r[key] for r in valid)
    unknown = total('tls_crossing_unknown_count')
    quality = all(r['data_quality_valid'] for r in valid)
    supported = bool(n and quality and not unknown)
    crossings = total('valid_tls_crossing_count')
    observed_times = [r['elapsed_s'] for r in valid if r['elapsed_s'] is not None]
    collided = total('ever_AV_collision')
    completed = total('completion')
    compliant = sum(r['compliant_completion'] is True for r in valid)
    return dict(metric_version=METRIC_VERSION, n_planned=n_planned, n_valid=n,
        n_invalid_attempts=len(records)-n, n_unattempted=n_planned-len(records),
        n_missing_valid=n_planned-n, n_completed=completed, n_compliant_completed=compliant,
        n_collision=collided, n_red_episode=sum(r['red_entry_count'] > 0 for r in valid),
        n_teleport=total('teleport'), n_removal=total('removal'), n_deadline=total('deadline'),
        primary_end_reason_counts=dict(Counter(r['primary_end_reason'] for r in valid)),
        completion_rate=completed/n if n else None, collision_rate=collided/n if n else None,
        compliant_completion_rate=compliant/n if supported else None,
        n_red_crossings=total('red_entry_count'), n_valid_tls_crossings=crossings,
        n_unknown_tls_crossings=unknown,
        signal_compliance=1-total('red_entry_count')/crossings if crossings and supported else None,
        signal_metric_supported=supported, data_quality_valid=quality,
        observed_collision_rate_below_5pct=(collided/n < .05) if n else None,
        evaluation_complete=n == n_planned,
        n_elapsed_observed=len(observed_times),
        mean_elapsed_all=sum(observed_times)/len(observed_times) if observed_times else None,
        mean_elapsed_completed=sum(r['elapsed_s'] for r in valid if r['completion'])/completed if completed else None,
        penalized_time_all=sum(r['penalized_time_s'] for r in valid)/n if n else None,
        final_ready=False, training_ready=False)


def evaluate_cases(policy, env, panel, *, max_decisions=601, on_transition=None):
    """Bounded, deterministic evaluation. No retries, updates or shared env.

    Caller owns the evaluation env, policy version and append-only attempt
    storage. Only transport failures are infrastructure-invalid. Insertion
    failure and nonfinite/invalid policy output remain performance failures.
    Exceptions outside this explicit taxonomy propagate for diagnosis.
    """
    if isinstance(max_decisions,bool) or not isinstance(max_decisions,int) or max_decisions<1:
        raise ValueError('max_decisions must be a positive integer')
    if len({c['case_uid'] for c in panel['cases']}) != len(panel['cases']):
        raise ValueError('Duplicate evaluation cases')
    before_weights=policy_weights_sha256(policy)
    records=[]
    fatal=getattr(getattr(env.unwrapped, 'traci', None), 'FatalTraCIError', None)
    transport=(OSError, EOFError) + ((fatal,) if isinstance(fatal,type) else ())
    for case in panel['cases']:
        tracker=None
        try:
            obs, info=env.reset(options={k:case[k] for k in
                ['namespace','scenario_id','case_index','demand_multiplier']})
            if info['case']['seeds'] != case['seeds']:
                raise ValueError('Runtime seeds do not match requested panel')
            tracker=EpisodeMetrics(case,info)
            for _ in range(max_decisions):
                try:
                    action=np.asarray(policy.predict(obs,deterministic=True),dtype=np.float32)
                except (TypeError,ValueError):
                    records.append(tracker.finish(failure_reason='policy_invalid_action'))
                    break
                if action.shape != (2,) or not np.isfinite(action).all():
                    records.append(tracker.finish(failure_reason='policy_invalid_action'))
                    break
                next_obs,reward,terminated,truncated,transition=env.step(action)
                tracker.add(reward,terminated,truncated,transition)
                if on_transition is not None:
                    on_transition(case,obs,action,next_obs,reward,terminated,truncated,transition)
                obs=next_obs
                if terminated or truncated:
                    records.append(tracker.finish())
                    break
            else:
                records.append(tracker.finish(failure_reason='step_guard'))
        except transport as error:
            reason=type(error).__name__+': '+str(error)
            if tracker is not None:
                records.append(tracker.finish(infrastructure_error=reason))
            else:
                records.append(reset_failure(case,'infrastructure_error',reason))
        except RuntimeError as error:
            if tracker is None and str(error).startswith('Ego insertion failed after 30s'):
                records.append(reset_failure(case,'insertion_failure'))
            else:
                raise
    if policy_weights_sha256(policy) != before_weights:
        raise RuntimeError('Evaluation mutated policy weights')
    return records,aggregate(records,len(panel['cases']))


def reset_failure(case, reason, infrastructure_error=None):
    """No fabricated state/speed/time for a reset that produced no observation."""
    return dict(metric_version=METRIC_VERSION,requested_case_uid=case['case_uid'],
        scenario_id=case['scenario_id'],namespace=case['namespace'],case_index=case['case_index'],
        demand_multiplier=case['demand_multiplier'],attempt_valid=infrastructure_error is None,
        infrastructure_invalid_reason=infrastructure_error,performance_failure_reason=reason,
        primary_end_reason=reason,completion=False,compliant_completion=False,
        ever_AV_collision=False,red_entry_count=0,tls_crossing_unknown_count=0,
        valid_tls_crossing_count=0,teleport=False,removal=False,deadline=False,
        data_quality_valid=True,quality_errors=[],elapsed_s=None,reset_observation_available=False,
        observed_episode_time_available=False,
        penalized_time_s=case['scenario']['episode_limit_s'])


def policy_weights_sha256(policy):
    model=getattr(policy,'policy',policy)
    if not hasattr(model,'state_dict'):
        return None
    h=hashlib.sha256()
    for name,tensor in sorted(model.state_dict().items()):
        h.update(name.encode());h.update(str(tensor.dtype).encode());h.update(str(tuple(tensor.shape)).encode())
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()
