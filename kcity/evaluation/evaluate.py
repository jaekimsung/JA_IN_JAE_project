"""Deterministic case-panel evaluation (no retries, no learning)."""
import numpy as np

from kcity.evaluation.metrics import EpisodeMetrics, aggregate, policy_weights_sha256, reset_failure


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
            if ('contract_sha256' in case and
                    info['case']['contract_sha256'] != case['contract_sha256']):
                raise ValueError('Runtime environment contract does not match requested panel')
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


