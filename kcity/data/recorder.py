"""Per-Episode bookkeeping shared by policy collection and online RL recording."""

from copy import deepcopy

from kcity.data.dataset import make_transition
from kcity.evaluation.metrics import EpisodeMetrics


class EpisodeRecorder:
    """Turns environment steps of one plan case into validated dataset rows and an Episode summary.

    Tracks the decision index, the post-reset traffic interval and departure history that the
    rows' enriched State needs, and the event-derived metrics. Finished Episodes are kept in
    `completed` until the caller commits them with the next shard.
    """

    def __init__(self, writer):
        self.writer = writer
        self.plan = writer.config['plan']
        self.completed = []
        self._reset_episode(None)

    def _reset_episode(self, episode):
        self.episode = episode
        self.case = self.plan[episode]['case'] if episode is not None else None
        self.data_split = self.plan[episode]['data_split'] if episode is not None else None
        self.t = 0
        self.start_tick = None
        self.previous_interval = dict(departed_hv=0, arrived_hv=0)
        self.departure_history = []
        self.metrics = None

    @property
    def active(self):
        return self.metrics is not None

    def start(self, episode, start_tick, state):
        """Begin plan case `episode`; `state` is the privileged State right after reset."""
        self._reset_episode(episode)
        self.start_tick = start_tick
        self.metrics = EpisodeMetrics(self.case, {'state': state})

    def record(
        self,
        *,
        observation,
        detected,
        next_observation,
        next_detected,
        reward,
        terminated,
        truncated,
        info,
        policy_context=None
    ):
        row = make_transition(
            config=self.writer.config,
            case=self.case,
            episode_index=self.episode,
            t=self.t,
            attempt_uid=self.writer.attempt_uid,
            observation=observation,
            detected=detected,
            next_observation=next_observation,
            next_detected=next_detected,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info,
            start_tick=self.start_tick,
            previous_interval=self.previous_interval,
            departure_history=self.departure_history,
            policy_context=policy_context,
        )
        self.writer.append(row)
        self.metrics.add(row['reward'], terminated, truncated, row)
        self.t += 1
        self.previous_interval = deepcopy(info['traffic_interval'])
        self.departure_history.append([info['sim_tick_tp1'], info['traffic_interval']['departed_hv']])
        if terminated or truncated:
            self.completed.append(
                dict(
                    episode_uid=row['episode_uid'],
                    episode=self.episode,
                    case_uid=self.case['case_uid'],
                    data_split=self.data_split,
                    metrics=self.metrics.finish(),
                )
            )
            self.metrics = None
        return row

    def state(self):
        return dict(
            episode=self.episode,
            t=self.t,
            episode_start_tick=self.start_tick,
            previous_interval=self.previous_interval,
            departure_history=self.departure_history,
            metrics=self.metrics.state() if self.active else None,
        )

    def restore(self, saved):
        self._reset_episode(saved['episode'] if saved['metrics'] is not None else None)
        if saved['metrics'] is None:
            return
        self.t = saved['t']
        self.start_tick = saved['episode_start_tick']
        self.previous_interval = saved['previous_interval']
        self.departure_history = saved['departure_history']
        self.metrics = EpisodeMetrics.from_state(saved['metrics'])
