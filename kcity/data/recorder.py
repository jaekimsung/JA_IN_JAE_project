"""Per-Episode bookkeeping shared by policy collection and online RL recording."""

from kcity.data.dataset import make_transition
from kcity.evaluation.metrics import EpisodeMetrics


class EpisodeRecorder:
    """Turns environment steps of one plan case into validated dataset rows and an Episode summary.

    Tracks the decision index and the event-derived metrics. Finished Episodes are kept in
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
        self.metrics = None

    @property
    def active(self):
        return self.metrics is not None

    def start(self, episode, state):
        """Begin plan case `episode`; `state` is the privileged State right after reset."""
        self._reset_episode(episode)
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
            observation=observation,
            detected=detected,
            next_observation=next_observation,
            next_detected=next_detected,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info,
            policy_context=policy_context,
        )
        self.writer.append(row)
        self.metrics.add(row['reward'], terminated, truncated, row)
        self.t += 1
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
            metrics=self.metrics.state() if self.active else None,
        )

    def restore(self, saved):
        self._reset_episode(saved['episode'] if saved['metrics'] is not None else None)
        if saved['metrics'] is None:
            return
        self.t = saved['t']
        self.metrics = EpisodeMetrics.from_state(saved['metrics'])
