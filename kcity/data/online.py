"""Record online PPO transitions in the dataset format, committed atomically with the learner bundle."""

from kcity.data.recorder import EpisodeRecorder
from kcity.data.storage import checkpoint_from_shard, require
from kcity.evaluation.metrics import policy_weights_sha256


class OnlineRecorder:
    """Receives each runner step (before the terminal reset) and adds PPO learner values to the row.

    The data shard and the learner bundle referenced by it are committed together, so after a
    crash the number of unique transitions equals the restored learner's counter.
    """

    def __init__(self, runner, writer):
        self.runner, self.writer = runner, writer
        self.recorder = EpisodeRecorder(writer)
        self.behavior_sha = policy_weights_sha256(runner.agent)
        saved, folder = writer.last_checkpoint()
        if saved is not None:
            runner.load_checkpoint(checkpoint_from_shard(folder))
            require(writer.count == runner.agent.num_timesteps, 'Atomic learner/data counts differ')
            self.recorder.restore(saved['recorder'])
            self.behavior_sha = saved['behavior_sha']

    def add(self, before, detected, nxt, next_detected, reward, term, trunc, info, lp, value, nv):
        runner = self.runner
        plan = self.writer.config['plan']
        require(
            runner.episode_count < len(plan),
            'PPO case plan exhausted after %d episodes; '
            'extend case_plan under a new run before continuing' % len(plan),
        )
        if not self.recorder.active:
            self.recorder.start(runner.episode_count, runner.env.episode_start_tick, info['state'])
        require(self.recorder.case == runner.env.case, 'Online case differs from declared plan')
        self.recorder.record(
            observation=before,
            detected=detected,
            next_observation=nxt,
            next_detected=next_detected,
            reward=reward,
            terminated=term,
            truncated=trunc,
            info=info,
            segment_reason='checkpoint' if term or trunc else None,
            policy_context=dict(
                behavior_sha=self.behavior_sha,
                update_id=runner.agent.num_updates,
                rollout_id=runner.agent.num_updates,
                log_prob_raw=lp,
                value=value,
                next_value=nv,
            ),
        )

    def commit(self):
        self.behavior_sha = policy_weights_sha256(self.runner.agent)
        state = dict(
            schema='KC-ONLINE-RESUME-v2', behavior_sha=self.behavior_sha, recorder=self.recorder.state()
        )
        folder = self.writer.commit(state, self.recorder.completed, self.runner.save_checkpoint)
        self.recorder.completed = []
        return folder
