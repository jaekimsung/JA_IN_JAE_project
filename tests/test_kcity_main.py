"""Main-runner operational contracts; probes never count as main data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from kcity.training.experiment import load_experiment
from kcity.data.collector import PolicyCollector,case_plan,dataset_config
from kcity.data.online import OnlineRecorder
from kcity.training.runs import Owner,read
from kcity.training.bc import run_bc
from kcity.policy.checkpoint import read_bundle
from kcity.policy.ppo import KCityPPO
from kcity.training.ppo import KCityRunner,RecordingRunner,run_ppo
from kcity.env.config import load_contract,digest
from kcity.env.env import SumoKCityEnv
from kcity.policy.rule_expert import KCityRuleExpert
from fixtures import fixture_batch,serializable,trace_rows
from kcity.data.dataset import ShardWriter,validate_dataset,validate_row,read_shard
from kcity.data.storage import checkpoint_from_shard


class MainContractTests(unittest.TestCase):
    def test_expert_split_is_per_scenario_and_disjoint(self):
        plan=case_plan(load_contract(),'expert',count=100)
        self.assertEqual(len({r['case']['case_uid'] for r in plan}),100)
        for sid in ['A','B','C']:
            rows=[r for r in plan if r['case']['scenario_id']==sid]
            self.assertEqual(sum(r['data_split']=='expert_val' for r in rows),len(rows)//5)
            self.assertTrue(all((r['case']['case_index']%5==4)==(r['data_split']=='expert_val') for r in rows))

    def test_experiment_settings_check_case_panels(self):
        spec=load_experiment()
        self.assertEqual(spec['seeds'],[11,22,33])
        broken=deepcopy(spec);broken['case_panels']['dev']['sha256']='0'*64
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'experiment.json';path.write_text(__import__('json').dumps(broken))
            with self.assertRaisesRegex(ValueError,'Case panel dev'):load_experiment(path)

    def test_owner_refuses_config_change_and_duplicate_process(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'job'
            owner=Owner(root,{'source':'a'})
            with self.assertRaisesRegex(RuntimeError,'Another process'):Owner(root,{'source':'a'},True)
            owner.close()
            with self.assertRaisesRegex(ValueError,'identical'):Owner(root,{'source':'b'},True)
            resumed=Owner(root,{'source':'a'},True)
            resumed.close()

    def test_recorded_step_matches_native_policy_and_update(self):
        torch.set_num_threads(1)
        spec=load_experiment()
        e=SumoKCityEnv(background=True)
        r=SumoKCityEnv(background=True)
        with tempfile.TemporaryDirectory() as d:
            writer=None
            try:
                a=KCityPPO(spec['policy'],hparams=spec['ppo'],seed=22)
                b=KCityPPO(spec['policy'],hparams=spec['ppo'],seed=22)
                native=KCityRunner(a,e,run_id='native',namespace='contract_check')
                record=RecordingRunner(b,r,run_id='recorded',namespace='contract_check')
                native.case_cursor=record.case_cursor=3000000
                cfg=dataset_config(r,'recorded-fixture',case_plan(r.contract,'probe',20,3000000),'debug','B2',22)
                writer=ShardWriter(Path(d)/'data',cfg,shard_rows=2048)
                recorder=OnlineRecorder(record,writer)
                record.recorder=recorder
                left=native.collect(32)
                right=record.collect(32)
                self.assertEqual(digest(trace_rows(left)),digest(trace_rows(right)))
                self.assertEqual(native.update(),record.update())
                self.assertEqual(digest(serializable(a.training_state())),digest(serializable(b.training_state())))
                recorder.commit()
                report=validate_dataset(writer.root)
                self.assertEqual(report['unique_transitions'],32)
                row=next(read_shard(writer.folders[0]))
                self.assertEqual(row['policy_id'],'B2')
                self.assertIsNotNone(row['learning']['log_prob_raw'])
                bad=deepcopy(row);bad['train_seed']=33
                with self.assertRaisesRegex(ValueError,'policy/seed'):validate_row(bad,writer.config)
                self.assertFalse(__import__('json').loads((writer.root/'RELEASE.json').read_text())['eligible_for_research_training'])
            finally:
                if writer is not None:writer.close()
                e.close();r.close()

    def test_expert_target_finishes_episode_without_main_eligibility(self):
        with tempfile.TemporaryDirectory() as d:
            env=SumoKCityEnv(background=True)
            writer=None
            try:
                cfg=dataset_config(env,'finish-episode-fixture',case_plan(env.contract,'expert',10,3000000),'debug')
                writer=ShardWriter(Path(d)/'data',cfg,shard_rows=512)
                collector=PolicyCollector(env,KCityRuleExpert(),writer)
                result=collector.collect(1)
                self.assertEqual(result['phase'],'COMPLETE')
                self.assertGreater(result['transitions'],1)
                self.assertFalse(collector.recorder.active)
                self.assertEqual(len(validate_dataset(writer.root)['episodes']),1)
            finally:
                if writer is not None:writer.close()
                env.close()

    def test_bc_stop_before_first_validation_resumes_with_best_selection(self):
        spec=deepcopy(load_experiment())
        spec['bc'].update(updates_per_seed=10,validate_every_updates=5)
        obs,action,mask=fixture_batch(32)
        data=dict(observation=obs,action_target=action,action_mask=mask)
        views={'expert_train':data,'expert_val':data}
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'bc'
            with patch('kcity.training.bc.read_views',return_value=({'data_id':'SYNTHETIC-UNIT','view_id':'fixture'},views)):
                with patch('kcity.training.bc.stopped',return_value=True):
                    run_bc(root,Path(d)/'mock-views',11,spec,'cpu')
                self.assertEqual(read(root/'STATUS.json')['updates'],1)
                self.assertIsNone(read(root/'STATUS.json')['best']['loss'])
                with patch('kcity.training.bc.stopped',return_value=False):
                    run_bc(root,Path(d)/'mock-views',11,spec,'cpu',resume=True)
                self.assertEqual(read(root/'COMPLETE.json')['updates'],10)
                self.assertIn(read(root/'BEST.json')['path'],['update-000005','update-000010'])
                kept=read(root/'CHECKPOINT_RETENTION.json')['retained']
                self.assertLessEqual(len(kept),3)
                self.assertIn(read(root/'LATEST.json')['path'],kept)
                self.assertIn(read(root/'BEST.json')['path'],kept)

    def test_main_loop_exact_cap_and_partial_stop_match_continuous(self):
        spec=deepcopy(load_experiment())
        spec['ppo'].update(n_steps=8,n_epochs=1,minibatch_size=4)
        spec['budgets']['ppo_transitions_per_method_seed']=19
        spec['metrics']['dev_interval_transitions']=10
        original_step=RecordingRunner.step
        def stop_after_five(runner):
            result=original_step(runner)
            if runner.agent.num_timesteps==stop_at:
                (paused/'STOP').touch()
            return result
        with tempfile.TemporaryDirectory() as d:
            baseline=Path(d)/'continuous'
            small_plan=lambda c,k:case_plan(c,k,count=60)
            with patch('kcity.training.ppo.case_plan',side_effect=small_plan),patch('kcity.training.ppo.evaluate_dev',return_value=True):
                run_ppo(baseline,'B2',11,spec,'cpu')
                for stop_at in [5,8,10,19]:
                    paused=Path(d)/f'paused-{stop_at}'
                    with patch.object(RecordingRunner,'step',stop_after_five):
                        run_ppo(paused,'B2',11,spec,'cpu')
                    status=read(paused/'STATUS.json')
                    self.assertEqual(status['transitions'],stop_at)
                    if stop_at==5:self.assertEqual(status['rollout_updates'],0)
                    (paused/'STOP').unlink()
                    run_ppo(paused,'B2',11,spec,'cpu',resume=True)
            fingerprints=[]
            for folder in [baseline]+[Path(d)/f'paused-{n}' for n in [5,8,10,19]]:
                self.assertEqual(read(folder/'COMPLETE.json')['transitions'],19)
                report=validate_dataset(folder/'transitions')
                self.assertEqual(report['unique_transitions'],19)
                checkpoint=checkpoint_from_shard(folder/read(folder/'LATEST.json')['path'])
                meta=read(checkpoint/'metadata.json')
                payload=read_bundle(checkpoint,'ppo',meta['config'])
                fingerprints.append(digest(serializable(payload['agent'])))
            self.assertTrue(all(fingerprints[0]==x for x in fingerprints[1:]))


if __name__=='__main__':unittest.main()
