"""Lossless storage, retained checkpoint and crash-boundary fixtures."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kcity.env.config import file_sha256
from kcity.env.env import SumoKCityEnv
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.data.dataset import ShardWriter,read_shard,validate_dataset,atomic_json
from kcity.data.collector import ExpertCollector,dataset_config,case_plan
from kcity.data.storage import (NEXT_CODEC,CHECKPOINT_MODE,encode_rows,decode_rows,
    save_external,sync_retention,verify_retention,checkpoint_from_shard)


class CodecTests(unittest.TestCase):
    def rows(self):
        return [dict(episode_uid='a',t=i,transition_uid=str(i),terminated=i==2,truncated=False,
                     state={'n':i},observation=[i],next_state={'n':i+1},next_observation=[i+1]) for i in range(3)]

    def test_lossless_lookahead_and_explicit_boundaries(self):
        rows=self.rows()
        compact=list(encode_rows(rows))
        self.assertNotIn('next_state',compact[0])
        self.assertIn('next_state',compact[-1])
        self.assertEqual(list(decode_rows(compact)),rows)
        self.assertEqual(list(decode_rows(encode_rows(rows[:1]))),rows[:1])
        self.assertEqual(list(decode_rows(encode_rows(rows[1:]))),rows[1:])

    def test_reference_cannot_jump_episode_or_missing_tail(self):
        compact=list(encode_rows(self.rows()))
        for variant in ['wrong_uid','missing_tail','new_episode']:
            data=deepcopy(compact)
            if variant=='wrong_uid':data[0]['next_reference']='wrong'
            elif variant=='missing_tail':data=data[:1]
            else:data[1]['episode_uid']='b'
            with self.assertRaises(ValueError):list(decode_rows(data))


class RetentionTests(unittest.TestCase):
    policy=dict(mode=CHECKPOINT_MODE,keep_recent=2,evaluation_interval_transitions=12)

    def bundle(self,path):
        path.mkdir()
        (path/'training.pt').write_bytes(b'SYNTHETIC-CHECKSUM-FIXTURE')
        atomic_json(path/'metadata.json',dict(synthetic=True))
        atomic_json(path/'SHA256.json',{p.name:file_sha256(p) for p in path.iterdir()})

    def shard(self,root,index,count=4):
        folder=root/'shards'/f'shard-{index:06d}'
        folder.mkdir(parents=True)
        atomic_json(folder/'SHARD.json',dict(rows=count))
        save_external(root,folder/'environment',self.bundle,(index+1)*count)
        return folder

    def test_only_latest_previous_and_milestones_are_retained(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            folders=[]
            immutable=[]
            for i in range(6):
                folders.append(self.shard(root,i))
                immutable.append(file_sha256(folders[-1]/'environment/REFERENCE.json'))
                sync_retention(root,folders,self.policy)
            registry=verify_retention(root,folders,self.policy)
            self.assertEqual([r['transitions'] for r in registry['retained']],[12,20,24])
            self.assertEqual(len(list((root/'checkpoints').iterdir())),3)
            self.assertEqual(immutable,[file_sha256(p/'environment/REFERENCE.json') for p in folders])
            self.assertTrue(checkpoint_from_shard(folders[-1]).exists())
            self.assertTrue(checkpoint_from_shard(folders[-2]).exists())

    def test_corrupt_latest_does_not_delete_older_bundles(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            folders=[self.shard(root,i) for i in range(3)]
            newest=checkpoint_from_shard(folders[-1])
            oldest=checkpoint_from_shard(folders[0])
            (newest/'training.pt').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):sync_retention(root,folders,self.policy)
            self.assertTrue(oldest.exists())

    def test_orphan_before_data_publication_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            orphan_stub=root/'staging'
            save_external(root,orphan_stub,self.bundle,4)
            self.assertEqual(len(list((root/'checkpoints').iterdir())),1)
            sync_retention(root,[],self.policy)
            self.assertEqual(len(list((root/'checkpoints').iterdir())),0)
            self.assertEqual(json.loads((root/'CHECKPOINTS.json').read_text())['committed_transitions'],0)


class ActualDataStorageTests(unittest.TestCase):
    def actual_fixture(self,root):
        env=SumoKCityEnv(background=True)
        writer=None
        try:
            cfg=dataset_config(env,'crash-storage-fixture',case_plan(env.contract,'expert',10,3000000),'debug')
            writer=ShardWriter(root/'fixture',cfg,shard_rows=512)
            ExpertCollector(env,KCityRuleExpert(),writer).collect(1)
            return cfg,[row for folder in writer.folders for row in read_shard(folder)]
        finally:
            if writer is not None:writer.close()
            env.close()

    def test_crash_before_shard_publish_keeps_data_count_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            cfg,rows=self.actual_fixture(root)
            cfg['checkpoint_policy']=RetentionTests.policy
            writer=ShardWriter(root/'data',cfg,shard_rows=512)
            for row in rows[:8]:writer.append(row)
            rename=Path.rename
            def crash_at_publish(path,target):
                if path.name.startswith('commit-'):raise OSError('fixture crash before shard publish')
                return rename(path,target)
            try:
                with patch.object(Path,'rename',crash_at_publish):
                    with self.assertRaises(OSError):writer.commit({},[],RetentionTests().bundle)
            finally:writer.close()
            recovered=ShardWriter(root/'data',cfg,shard_rows=512,resume=True)
            try:
                self.assertEqual(recovered.count,0)
                self.assertEqual(len(list((recovered.root/'checkpoints').iterdir())),0)
            finally:recovered.close()

    def test_crash_after_shard_publish_recovers_matching_reference(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            cfg,rows=self.actual_fixture(root)
            cfg['checkpoint_policy']=RetentionTests.policy
            writer=ShardWriter(root/'data',cfg,shard_rows=512)
            for row in rows[:8]:writer.append(row)
            try:
                with patch.object(writer,'refresh_release',side_effect=RuntimeError('fixture crash after shard publish')):
                    with self.assertRaises(RuntimeError):writer.commit({},[],RetentionTests().bundle)
            finally:writer.close()
            recovered=ShardWriter(root/'data',cfg,shard_rows=512,resume=True)
            try:
                self.assertEqual(recovered.count,8)
                self.assertTrue(checkpoint_from_shard(recovered.folders[-1]).exists())
                self.assertEqual(validate_dataset(recovered.root)['unique_transitions'],8)
            finally:recovered.close()

    def test_full_state_and_npz_survive_compact_storage_and_legacy_reading(self):
        with tempfile.TemporaryDirectory() as d:
            env=SumoKCityEnv(background=True)
            writer=None
            full=[]
            try:
                cfg=dataset_config(env,'storage-real-fixture',case_plan(env.contract,'expert',10,3000000),'debug')
                writer=ShardWriter(Path(d)/'compact',cfg,shard_rows=17)
                append=writer.append
                def capture(row):
                    full.append(deepcopy(row));append(row)
                with patch.object(writer,'append',side_effect=capture):
                    ExpertCollector(env,KCityRuleExpert(),writer).collect(1)
                restored=[r for folder in writer.folders for r in read_shard(folder)]
                self.assertEqual(full,restored)
                self.assertTrue(validate_dataset(writer.root)['passed'])
                for folder in writer.folders:
                    with gzip.open(folder/'transitions.jsonl.gz','rt') as stream:
                        physical=[json.loads(line) for line in stream]
                    self.assertIn('next_state',physical[-1])
                    if len(physical)>1:
                        self.assertTrue(any('next_reference' in r for r in physical[:-1]))
                # The old full-next format is still readable without conversion.
                writer.close();writer=None
                legacy_cfg=dict(cfg);legacy_cfg.pop('storage_codec')
                legacy=ShardWriter(Path(d)/'legacy',legacy_cfg,shard_rows=len(full))
                try:
                    for row in full:legacy.append(row)
                    legacy.commit({},[])
                    self.assertEqual(full,list(read_shard(legacy.folders[0])))
                finally:legacy.close()
            finally:
                if writer is not None:writer.close()
                env.close()
