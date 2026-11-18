"""Record online RL transitions in the dataset format, committed atomically with the learner bundle."""

from kcity.data.recorder import EpisodeRecorder
from kcity.evaluation.metrics import policy_weights_sha256


class OnlineRecorder:
    """Adds learner provenance to each online row and commits shard + learner bundle together.

    After a crash the committed transitions are exactly those the restored learner has seen, and they
    are also what its replay buffer is rebuilt from. The acting-policy hash is taken at each commit:
    it identifies the actor the shard's rows started from (the actor is updated every step).
    """

    def __init__(self, agent, writer):
        self.agent, self.writer = agent, writer
        self.recorder = EpisodeRecorder(writer)
        self.behavior_sha = policy_weights_sha256(agent)
        saved, _ = writer.last_checkpoint()
        if saved is not None:
            self.recorder.restore(saved['recorder'])

    def add(self, *, episode, reset_state, random_action, **transition):
        if not self.recorder.active:
            self.recorder.start(episode, reset_state)
        return self.recorder.record(
            policy_context=dict(
                behavior_sha=self.behavior_sha, update_step=self.agent.num_updates, random_action=bool(random_action)
            ),
            **transition,
        )

    def commit(self, state, save_checkpoint):
        """`state` is the trainer's resume state; `save_checkpoint(path)` writes the learner bundle."""
        checkpoint = dict(schema='KC-ONLINE-RESUME-v3', recorder=self.recorder.state(), trainer=state)
        folder = self.writer.commit(checkpoint, self.recorder.completed, save_checkpoint)
        self.recorder.completed = []
        self.behavior_sha = policy_weights_sha256(self.agent)
        return folder
