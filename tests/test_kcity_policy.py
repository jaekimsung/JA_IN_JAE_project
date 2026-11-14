"""KC-04 synthetic gradient/transfer and real SUMO resume fixtures; no study training."""
from copy import deepcopy
from pathlib import Path
import json
import random
import sys
import tempfile
import unittest

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from algorithms.bc import BCPolicy
from algorithms.kcity_policy import DEFAULT_POLICY,KCityPolicy,initialize_from_bc
from algorithms.kcity_training import DEFAULT_PPO,KCityBC,KCityPPO,KCityRunner,new_policy
from env.kcity_env import SumoKCityEnv


def fixture_batch(n=32):
    obs=np.zeros((n,73),np.float32);obs[:,0]=np.linspace(0,1,n);obs[:,41:46]=1
    obs[::3,42]=0;obs[1::3,44]=0;obs[::7,51]=1;obs[::5,52]=.5
    masks=KCityPolicy.mask_from_obs(obs).numpy()
    actions=np.zeros((n,2),np.float32);actions[:,0]=np.sin(np.arange(n))*.5
    for i in range(n):actions[i,1]=[1,0,-1][np.flatnonzero(masks[i])[i%int(masks[i].sum())]]
    return obs,actions,masks


def small_config():return dict(deepcopy(DEFAULT_POLICY),hidden_sizes=[16,16])
def small_hp():return dict(DEFAULT_PPO,n_steps=4,n_epochs=1,minibatch_size=4)


class PolicyTests(unittest.TestCase):
    def test_default_parameter_count(self):
        p=new_policy(None,11)
        self.assertEqual(sum(v.numel() for v in p.parameters()),86022)

    def test_sample_and_recomputed_logprob_match_with_masks(self):
        p=new_policy(small_config(),11);obs,_,masks=fixture_batch(128);o=torch.tensor(obs);m=torch.tensor(masks)
        a,lp,_=p.sample(o,m,generator=torch.Generator().manual_seed(4))
        lp2,entropy,_=p.evaluate_actions(o,a,m)
        self.assertTrue(torch.equal(lp,lp2));self.assertTrue(torch.isfinite(entropy).all())
        idx=(1-a[:,1]).long();self.assertTrue(m.gather(1,idx[:,None]).all())

    def test_deterministic_action_cannot_choose_masked_lane(self):
        p=new_policy(small_config(),1);obs,_,masks=fixture_batch();o=torch.tensor(obs)
        a=p.det_action(o);self.assertTrue(torch.tensor(masks).gather(1,(1-a[:,1]).long()[:,None]).all())

    def test_wrong_mask_or_category_rejected(self):
        p=new_policy(small_config(),1);obs,actions,masks=fixture_batch();o=torch.tensor(obs);a=torch.tensor(actions)
        wrong=masks.copy();wrong[0,0]=~wrong[0,0]
        with self.assertRaises(ValueError):p.evaluate_actions(o,a,torch.tensor(wrong))
        a[0,1]=.7
        with self.assertRaises(ValueError):p.evaluate_actions(o,a,torch.tensor(masks))

    def test_masked_keep_only_has_zero_lane_entropy(self):
        p=new_policy(small_config(),1);obs=torch.zeros(8,73)
        self.assertTrue(torch.equal(p.lane_entropy(obs),torch.zeros(8)))

    def test_invalid_observation_rejected(self):
        for obs in [torch.zeros(1,31),torch.full((1,73),float('nan')),torch.ones(1,73)*2]:
            with self.assertRaises(ValueError):KCityPolicy.mask_from_obs(obs)

    def test_bc_updates_actor_not_value_head_or_std(self):
        bc=KCityBC(small_config(),seed=11);before={k:v.clone() for k,v in bc.policy.state_dict().items()}
        loss=bc.train_batch(*fixture_batch())
        self.assertTrue(all(np.isfinite(v) for v in loss.values()))
        state=bc.policy.state_dict()
        self.assertTrue(all(torch.equal(v,state[k]) for k,v in before.items() if k.startswith('v_head.') or k=='log_std'))
        self.assertTrue(any(not torch.equal(v,state[k]) for k,v in before.items() if k.startswith('trunk.')))

    def test_bc_invalid_label_and_mask_rejected(self):
        bc=KCityBC(small_config());obs,actions,masks=fixture_batch()
        actions[0,0]=2
        with self.assertRaises(ValueError):bc.train_batch(obs,actions,masks)
        actions[0,0]=0;masks=masks.astype(int);masks[0,1]=2
        with self.assertRaises(ValueError):bc.train_batch(obs,actions,masks)

    def test_actor_transfer_matches_b1_and_preserves_b2_critic_std(self):
        bc=KCityBC(small_config());bc.train_batch(*fixture_batch())
        b2=KCityPPO(small_config(),hparams=small_hp());b3=KCityPPO(small_config(),hparams=small_hp())
        b3.initialize_bc(bc.policy,'synthetic-fixture')
        obs,_,_=fixture_batch()
        for o in obs:np.testing.assert_array_equal(bc.policy.predict(o),b3.predict(o))
        for k,v in b2.policy.state_dict().items():
            if k.startswith('v_head.') or k=='log_std':self.assertTrue(torch.equal(v,b3.policy.state_dict()[k]))
        self.assertEqual(len(b3.optimizer.state),0)
        for source,target in zip(bc.policy.parameters(),b3.policy.parameters()):self.assertNotEqual(source.data_ptr(),target.data_ptr())

    def test_transfer_rejects_legacy_config_mismatch_and_nonfresh_target(self):
        p=new_policy(small_config(),11)
        with self.assertRaises(ValueError):initialize_from_bc(p,BCPolicy(73))
        with self.assertRaises(ValueError):initialize_from_bc(p,new_policy(None,11))
        agent=KCityPPO(small_config(),hparams=small_hp());agent.num_timesteps=1
        with self.assertRaises(ValueError):agent.initialize_bc(p,'fixture')

    def test_owned_rng_ignores_global_rng(self):
        a=KCityPPO(small_config(),hparams=small_hp());b=KCityPPO(small_config(),hparams=small_hp())
        obs=fixture_batch()[0][2]
        for _ in range(3):
            aa=a.act(obs);random.random();np.random.rand(10);torch.rand(10);bb=b.act(obs)
            np.testing.assert_array_equal(aa[0],bb[0]);self.assertEqual(aa[1:],bb[1:])

    def test_bc_checkpoint_resume_next_batch_and_update_exact(self):
        a=KCityBC(small_config());a.train_batch(*fixture_batch())
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bc';a.save_checkpoint(path,{'data_id':'synthetic','next_batch':1})
            b=KCityBC(small_config());state=b.load_checkpoint(path,expected_data_id='synthetic')
            self.assertEqual(state['next_batch'],1)
            np.testing.assert_array_equal(a.sampler.integers(0,32,8),b.sampler.integers(0,32,8))
            self.assertEqual(a.train_batch(*fixture_batch()),b.train_batch(*fixture_batch()))
            self.assertTrue(all(torch.equal(v,b.policy.state_dict()[k]) for k,v in a.policy.state_dict().items()))
            self.assertEqual(a.updates,b.updates)
            with self.assertRaisesRegex(ValueError,'dataset identity'):
                KCityBC(small_config()).load_checkpoint(path,expected_data_id='other-data')

    def test_checkpoint_immutable_hash_and_config_checked(self):
        a=KCityBC(small_config())
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bc';a.save_checkpoint(path,{'data':'synthetic'})
            with self.assertRaises(FileExistsError):a.save_checkpoint(path,{})
            with self.assertRaises(ValueError):KCityBC(small_config(),seed=22).load_checkpoint(path)
            (path/'metadata.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'SHA256'):a.load_checkpoint(path)


class ResumeTests(unittest.TestCase):
    def runner(self,background=False,limit=None):
        e=SumoKCityEnv(background=background,debug_warmup_s=None if background else 0,
                       debug_episode_limit_s=limit)
        self.addCleanup(e.close)
        return KCityRunner(KCityPPO(small_config(),hparams=small_hp()),e,
                           run_id='synthetic-resume-fixture',namespace='contract_check')

    def test_partial_rollout_sumo_rng_optimizer_resume(self):
        a=self.runner(background=True);a.collect(4);a.update();a.collect(2)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ppo';a.save_checkpoint(path)
            expected=a.collect(4);a.update()
            b=self.runner(background=True);b.load_checkpoint(path)
            self.assertEqual(len(b.agent.buffer),2)
            actual=b.collect(4);b.update()
            for x,y in zip(expected,actual):
                np.testing.assert_array_equal(x[0],y[0]);self.assertEqual(x[1:5],y[1:5])
                self.assertEqual(x[5]['next_state'],y[5]['next_state'])
            self.assertTrue(all(torch.equal(v,b.agent.policy.state_dict()[k]) for k,v in a.agent.policy.state_dict().items()))
            self.assertEqual(a.agent.num_timesteps,b.agent.num_timesteps)
            self.assertEqual(a.agent.num_optimizer_steps,b.agent.num_optimizer_steps)

    def test_resume_across_case_boundary(self):
        a=self.runner(limit=.7);a.collect(3)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ppo';a.save_checkpoint(path);expected=a.collect(2)
            b=self.runner(limit=.7);b.load_checkpoint(path);actual=b.collect(2)
            self.assertEqual(a.case_cursor,b.case_cursor);self.assertEqual(a.episode_count,b.episode_count)
            for x,y in zip(expected,actual):np.testing.assert_array_equal(x[0],y[0])

    def test_active_lane_request_mode_and_cooldown_restored(self):
        # Direct environment test: force a valid request rather than hoping a
        # random initial policy chooses it at this seed.
        a=SumoKCityEnv(scenario_id='B',background=False,debug_warmup_s=0);self.addCleanup(a.close)
        b=SumoKCityEnv(scenario_id='B',background=False,debug_warmup_s=0);self.addCleanup(b.close)
        a.reset(seed=42);a.step([1,1])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'env';a.save_resume_state(path);b.load_resume_state(path)
            self.assertEqual(b.conn.vehicle.getLaneChangeMode(b.ego_id),512)
            self.assertEqual(a.get_action_mask(),b.get_action_mask())
            x=a.step([1,0]);y=b.step([1,0]);np.testing.assert_array_equal(x[0],y[0])

    def test_resume_rejects_wrong_run_before_starting_sumo(self):
        a=self.runner();a.collect(1)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'ppo';a.save_checkpoint(path);b=self.runner();b.run_id='other'
            with self.assertRaisesRegex(ValueError,'run/config'):b.load_checkpoint(path)
            self.assertIsNone(b.env.conn)

    def test_exact_cap_with_real_bounded_fixture_updates(self):
        a=self.runner();history=a.run_until(7,fixture=True)
        self.assertEqual([r['transitions'] for r in history],[4,7])
        self.assertEqual(a.agent.num_timesteps,7);self.assertEqual(a.agent.num_updates,2)
        self.assertEqual(len(a.agent.buffer),0)
        self.assertEqual(a.run_until(7,fixture=True),[])

    def test_research_gate_rejects_before_sumo_start(self):
        a=self.runner();a.namespace='train'
        with self.assertRaisesRegex(RuntimeError,'disabled'):a.run_until(7)
        with self.assertRaises(ValueError):a.run_until(7,fixture=True)
        self.assertIsNone(a.env.conn)


if __name__=='__main__':unittest.main()
