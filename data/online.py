"""Record online PPO transitions in the same shard format, committed atomically with the learner bundle."""
from collections import Counter
from copy import deepcopy

from data.dataset import make_transition
from data.storage import checkpoint_from_shard
from evaluation.metrics import EpisodeMetrics, policy_weights_sha256
from data.storage import require


class OnlineRecorder:
    def __init__(self,runner,writer,method,seed):
        self.runner,self.writer,self.method,self.seed = runner,writer,method,seed
        self.metrics = None
        self.completed = []
        self.t = 0
        self.previous = dict(departed_hv=0,arrived_hv=0)
        self.history = []
        self.behavior_sha = policy_weights_sha256(runner.agent)
        saved,folder = writer.last_checkpoint()
        if saved is not None:
            runner.load_checkpoint(checkpoint_from_shard(folder))
            require(writer.count==runner.agent.num_timesteps,'Atomic learner/data counts differ')
            self.t,self.previous,self.history = saved['t'],saved['previous'],saved['history']
            if saved['metrics'] is not None:
                self.metrics = EpisodeMetrics.__new__(EpisodeMetrics)
                self.metrics.__dict__.update(saved['metrics'])
                self.metrics.commands = Counter({int(k):v for k,v in self.metrics.commands.items()})
                self.metrics.rejections = Counter(self.metrics.rejections)
            self.behavior_sha = saved['behavior_sha']

    def add(self,before,detected,nxt,next_detected,reward,term,trunc,info,lp,value,nv):
        r = self.runner
        plan = self.writer.config['plan']
        require(r.episode_count<len(plan),'PPO case plan exhausted after %d episodes; '
                'extend case_plan under a new run before continuing' % len(plan))
        case = plan[r.episode_count]['case']
        require(case==r.env.case,'Online case differs from declared plan')
        if self.metrics is None:
            self.metrics = EpisodeMetrics(case,{'state':info['state']})
            self.t = 0
            self.previous = dict(departed_hv=0,arrived_hv=0)
            self.history = []
        row = make_transition(config=self.writer.config,case=case,episode_index=r.episode_count,t=self.t,
            attempt_uid=self.writer.attempt_uid,observation=before,detected=detected,next_observation=nxt,
            next_detected=next_detected,reward=reward,terminated=term,truncated=trunc,info=info,
            start_tick=r.env.episode_start_tick,previous_interval=self.previous,departure_history=self.history,
            segment_reason='checkpoint' if term or trunc else None,
            policy_context=dict(behavior_sha=self.behavior_sha,update_id=r.agent.num_updates,
                rollout_id=r.agent.num_updates,log_prob_raw=lp,value=value,next_value=nv))
        self.writer.append(row)
        self.metrics.add(row['reward_env_raw'],term,trunc,row)
        self.t += 1
        self.previous = deepcopy(info['traffic_interval'])
        self.history.append([info['sim_tick_tp1'],info['traffic_interval']['departed_hv']])
        if term or trunc:
            self.completed.append(dict(episode_uid=row['episode_uid'],episode=r.episode_count,
                case_uid=case['case_uid'],data_split=self.writer.config['plan'][r.episode_count]['data_split'],
                metrics=self.metrics.finish()))
            self.metrics = None
            self.t = 0

    def commit(self):
        self.behavior_sha = policy_weights_sha256(self.runner.agent)
        state = dict(t=self.t,previous=self.previous,history=self.history,
                     behavior_sha=self.behavior_sha,metrics=deepcopy(self.metrics.__dict__) if self.metrics else None)
        folder = self.writer.commit(state,self.completed,self.runner.save_checkpoint)
        self.completed = []
        return folder
