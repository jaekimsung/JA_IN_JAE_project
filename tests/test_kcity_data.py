"""expert/data fixtures: real SUMO rows, corruption, split and recovery tests."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.env.env import SumoKCityEnv
from kcity.data.collector import PolicyCollector,dataset_config,resolve_plan
from kcity.data.dataset import (ShardWriter,validate_row,validate_pair,make_transition,validate_dataset,
    create_index,index_row,atomic_json,digest,file_sha256)
from kcity.evaluation.metrics import EpisodeMetrics
from kcity.data.dataset import observation_mask
from kcity.env.observation import (CORRIDOR, COOLDOWN, EXISTS, INSIDE, LANE_ENDS, LANE_LEFT, OBS_DIM, SPEED,
                                   TLS_DIST, TLS_RED)


def observation(speed=6):
    o=np.zeros(OBS_DIM,np.float32);o[SPEED]=speed/8.33;o[EXISTS:EXISTS+5]=1;o[LANE_LEFT]=.6;o[TLS_DIST]=1
    for k in range(5):o[CORRIDOR+4*k:CORRIDOR+4*k+4]=[1,0,-1,0]
    return o


class ExpertTests(unittest.TestCase):
    def test_expert_is_memoryless_and_has_no_state_interface(self):
        e=KCityRuleExpert();o=observation();a=e.predict(o)
        for _ in range(3):np.random.rand(20);np.testing.assert_array_equal(a,e.predict(o))
        self.assertEqual(set(vars(e)),{'config'})
        with self.assertRaises(TypeError):e.predict(o,state={'future_signal':'G'})

    def test_red_and_front_vehicle_request_braking(self):
        e=KCityRuleExpert();o=observation();o[TLS_RED]=1;o[TLS_DIST]=.03
        self.assertLess(e.predict(o)[0],0)
        o=observation();o[CORRIDOR+4*2]=.03;o[CORRIDOR+4*2+1]=-5/8.33
        self.assertLess(e.predict(o)[0],0)

    def test_required_lane_checks_rear_gap(self):
        e=KCityRuleExpert();o=observation()
        self.assertEqual(e.predict(o)[1],0)  # the lane continues: no change
        o[LANE_ENDS]=1;o[EXISTS+3:EXISTS+5]=0  # rightmost lane ends, only the left lane continues
        self.assertEqual(e.predict(o)[1],1)
        o[CORRIDOR+4*1+2]=-.02;o[CORRIDOR+4*1+3]=.1
        self.assertEqual(e.predict(o)[1],0)
        o[CORRIDOR+4*1+2]=-.9;self.assertEqual(e.predict(o)[1],1)

    def test_masks_match_environment_and_actions_are_bounded(self):
        e=KCityRuleExpert()
        for internal,cooldown,left,right in [(0,0,1,1),(1,0,1,1),(0,.5,1,1),(0,0,0,1),(0,0,1,0)]:
            o=observation();o[INSIDE]=internal;o[COOLDOWN]=cooldown;o[EXISTS+1]=left;o[EXISTS+3]=right
            o[LANE_ENDS]=1;a,info=e.decision(o)
            self.assertEqual(info['lane_mask'],observation_mask(o))
            self.assertTrue(np.isfinite(a).all() and (np.abs(a)<=1).all())
            self.assertTrue(info['lane_mask'][int(1-a[1])])

    def test_invalid_observations_rejected(self):
        for o in [np.zeros(31),np.ones(OBS_DIM)*2,np.full(OBS_DIM,np.nan)]:
            with self.assertRaises(ValueError):KCityRuleExpert().predict(o)


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e=SumoKCityEnv(background=True);expert=KCityRuleExpert()
        cls.config=dataset_config(e,'KC05-unit-actual-A',resolve_plan(e,[
            dict(scenario_id='A',namespace='expert_train',case_index=0,data_split='expert_train')]))
        case=cls.config['plan'][0]['case'];cls.rows=[]
        try:
            obs,reset=e.reset(options={k:case[k] for k in ['namespace','scenario_id','case_index','demand_multiplier']})
            start=reset['state']['sim_tick'];interval=dict(departed_hv=0,arrived_hv=0);history=[]
            metrics=EpisodeMetrics(case,reset)
            for t in range(600):
                detected=e.get_detected_vehicles();nxt,r,term,trunc,info=e.step(expert.predict(obs))
                row=make_transition(config=cls.config,case=case,episode_index=0,t=t,attempt_uid='unit',
                    observation=obs,detected=detected,next_observation=nxt,next_detected=e.get_detected_vehicles(),
                    reward=r,terminated=term,truncated=trunc,info=info,start_tick=start,
                    previous_interval=interval,departure_history=history)
                cls.rows.append(row);metrics.add(row['reward'],term,trunc,row)
                history.append([info['sim_tick_tp1'],info['traffic_interval']['departed_hv']]);interval=info['traffic_interval'];obs=nxt
                if term or trunc:break
            cls.summary=dict(episode_uid=cls.rows[-1]['episode_uid'],episode=0,case_uid=case['case_uid'],
                data_split='expert_train',metrics=metrics.finish())
            if cls.summary['metrics']['primary_end_reason']!='arrival':raise RuntimeError('Actual B0 fixture did not complete')
        finally:e.close()

    def writer(self,path,**kwargs):return ShardWriter(path,self.config,**kwargs)

    def complete(self,path,shard_rows=64):
        w=self.writer(path,shard_rows=shard_rows)
        try:
            for i,row in enumerate(self.rows):
                w.append(row)
                if w.pending==shard_rows or i+1==len(self.rows):
                    w.commit({'fixture':True},[self.summary] if i+1==len(self.rows) else [])
        finally:w.close()

    def test_actual_rows_have_full_state_and_terminal_absorbing_next(self):
        for row in self.rows:validate_row(row,self.config)
        self.assertTrue(self.rows[-1]['terminated']);self.assertFalse(self.rows[-1]['next_observation_valid'])
        self.assertIsNone(self.rows[-1]['next_state']['ego_x'])
        self.assertTrue(all('vehicles' in r['state'] and 'vehicles' in r['next_state'] for r in self.rows))

    def test_missing_state_nan_and_action_alias_rejected(self):
        r=deepcopy(self.rows[0]);del r['state']['vehicles']
        with self.assertRaises(ValueError):validate_row(r)
        r=deepcopy(self.rows[0]);r['state']['vehicles'][0]['x']=float('nan')
        with self.assertRaises(ValueError):validate_row(r)
        r=deepcopy(self.rows[0]);r['action_raw'][0]=99
        with self.assertRaises(ValueError):validate_row(r)

    def test_reset_observation_contamination_rejected_across_rows(self):
        r=deepcopy(self.rows[0]);r['next_observation'][0]=.99
        with self.assertRaises(ValueError):validate_pair(r,self.rows[1])

    def test_detected_vehicle_not_in_same_snapshot_is_rejected(self):
        r=deepcopy(self.rows[0]);r['detected_vehicles'].append(dict(id='absent-sensor-id',x=0,y=0,speed=0,relation='crossing'))
        with self.assertRaisesRegex(ValueError,'Detected vehicle'):validate_row(r)

    def test_valid_cross_shard_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';self.complete(root,shard_rows=7);q=validate_dataset(root)
            self.assertEqual(q['unique_transitions'],len(self.rows));self.assertGreater(q['committed_shards'],1)

    def test_duplicate_transition_is_not_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            w=self.writer(Path(temp)/'data')
            try:
                w.append(self.rows[0])
                with self.assertRaises(ValueError):w.append(self.rows[0])
                self.assertEqual(w.pending,1)
            finally:w.close()

    def test_seed_group_cannot_cross_train_val(self):
        with tempfile.TemporaryDirectory() as temp:
            db=create_index(Path(temp)/'index.sqlite')
            try:
                index_row(db,self.rows[0]);bad=deepcopy(self.rows[1]);bad['data_split']='expert_val'
                with self.assertRaisesRegex(ValueError,'leaks'):index_row(db,bad)
            finally:db.close()

    def test_single_writer_lock_is_not_removed_by_second_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root)
            try:
                with self.assertRaisesRegex(RuntimeError,'Another writer'):self.writer(root,resume=True)
                self.assertTrue((root/'.writer.lock').exists())
            finally:w.close()

    def test_uncommitted_partial_is_quarantined_and_recollected_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root,shard_rows=2)
            w.append(self.rows[0]);w.append(self.rows[1]);w.commit({'fixture':True},[])
            w.append(self.rows[2]);w.close()
            self.assertEqual(validate_dataset(root)['unique_transitions'],2)
            w=self.writer(root,resume=True,shard_rows=2)
            try:
                self.assertEqual(w.count,2);w.append(self.rows[2]);w.commit({'fixture':True},[])
            finally:w.close()
            self.assertEqual(validate_dataset(root)['unique_transitions'],3)
            self.assertTrue(any((root/'quarantine').iterdir()))

    def test_clean_resume_rebuilds_index_without_quarantine_growth(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root,shard_rows=2)
            w.append(self.rows[0]);w.append(self.rows[1]);w.commit({'fixture':True},[]);w.close()
            for _ in range(2):
                w=self.writer(root,resume=True,shard_rows=2)
                try:self.assertEqual(w.count,2)
                finally:w.close()
            self.assertFalse((root/'quarantine').exists())
            self.assertEqual(sorted(p.name for p in (root/'partial').iterdir()),['current.jsonl','index.sqlite'])

    def test_commit_directory_survives_release_update_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root)
            try:
                w.append(self.rows[0]);w.append(self.rows[1])
                with patch.object(w,'refresh_release',side_effect=RuntimeError('fault after rename')):
                    with self.assertRaises(RuntimeError):w.commit({'fixture':True},[])
            finally:w.close()
            with self.assertRaisesRegex(ValueError,'stale'):validate_dataset(root)
            w=self.writer(root,resume=True)
            try:self.assertEqual(w.count,2)
            finally:w.close()
            self.assertEqual(validate_dataset(root)['unique_transitions'],2)

    def test_stale_lock_and_source_config_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root);w.close()
            child=subprocess.Popen([sys.executable,'-c','pass']);child.wait()
            atomic_json(root/'.writer.lock',{'pid':child.pid})
            w=self.writer(root,resume=True);w.close()
            bad=deepcopy(self.config);bad['teacher']['fingerprint']='0'*64
            with self.assertRaises(ValueError):ShardWriter(root,bad,resume=True)

    def test_npz_corruption_rejected_even_with_updated_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';self.complete(root)
            folder=root/'shards/shard-000000'
            with np.load(folder/'numeric.npz',allow_pickle=False) as arrays:data={k:arrays[k] for k in arrays.files}
            data['detected_offsets'][-1]+=1;np.savez_compressed(folder/'numeric.npz',**data)
            shard=json.loads((folder/'SHARD.json').read_text());shard['files']['numeric.npz']=file_sha256(folder/'numeric.npz')
            atomic_json(folder/'SHARD.json',shard)
            release=json.loads((root/'RELEASE.json').read_text());release['shards'][0]['manifest_sha256']=file_sha256(folder/'SHARD.json')
            release['data_id']=digest({k:v for k,v in release.items() if k!='data_id'});atomic_json(root/'RELEASE.json',release)
            with self.assertRaisesRegex(ValueError,'JSON/NPZ'):validate_dataset(root)

    def test_fabricated_success_summary_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root)
            try:
                w.append(self.rows[0]);w.commit({'fixture':True},[self.summary])
            finally:w.close()
            with self.assertRaisesRegex(ValueError,'BC eligibility'):validate_dataset(root)

    def test_unknown_signal_episode_is_preserved_but_excluded_from_bc(self):
        rows=deepcopy(self.rows)
        next(e for r in rows for e in r['events'] if e['type']=='tls_crossing')['classification_valid']=False
        tracker=EpisodeMetrics(self.config['plan'][0]['case'],{'state':rows[0]['state']})
        for r in rows:tracker.add(r['reward'],r['terminated'],r['truncated'],r)
        summary=deepcopy(self.summary);summary['metrics']=tracker.finish()
        self.assertIsNone(summary['metrics']['compliant_completion'])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';w=self.writer(root)
            try:
                for row in rows:w.append(row)
                w.commit({'fixture':True},[summary])
            finally:w.close()
            self.assertEqual(validate_dataset(root)['unique_transitions'],len(rows))


class CollectorTests(unittest.TestCase):
    def env(self):
        env=SumoKCityEnv(background=False,debug_warmup_s=0,debug_episode_limit_s=.7)
        self.addCleanup(env.close);return env

    def test_collector_resume_preserves_uids_progress_and_episode_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'data';expert=KCityRuleExpert();e=self.env()
            plan=[dict(scenario_id='A',namespace='expert_train',case_index=i,data_split='expert_train') for i in range(3)]
            config=dataset_config(e,'collector-resume-unit',resolve_plan(e,plan));w=ShardWriter(root,config,shard_rows=2)
            try:
                # STOP after 3 rows: the active Episode is checkpointed mid-way and replayed on resume.
                stopped=PolicyCollector(e,expert,w).collect(6,lambda:w.count+w.pending>=3)
                self.assertEqual(stopped['phase'],'STOPPED')
            finally:w.close();e.close()
            committed=validate_dataset(root)['unique_transitions'];self.assertEqual(committed,3)
            e=self.env();w=ShardWriter(root,config,resume=True,shard_rows=2)
            try:
                result=PolicyCollector(e,expert,w).collect(6)
                self.assertEqual(result['phase'],'COMPLETE');self.assertEqual(result['transitions'],6)
            finally:w.close()
            report=validate_dataset(root);self.assertEqual(len(report['episodes']),3)
            self.assertTrue(all(e['metrics']['primary_end_reason']=='deadline' for e in report['episodes']))


if __name__=='__main__':unittest.main()
