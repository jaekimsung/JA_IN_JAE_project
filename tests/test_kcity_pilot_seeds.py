"""Seed replication contract tests; no long training or simulation launch."""
import ast
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

import torch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.kcity.pilot_seeds import replication_config,ReplicationPilot
from scripts.kcity.pilot import check_config
from algorithms.kcity_training import KCityBC,KCityPPO,DEFAULT_PPO
from algorithms.kcity_policy import DEFAULT_POLICY


class ReplicationTests(unittest.TestCase):
    def test_only_reserved_new_seeds(self):
        for seed in [11,0,44]:
            with self.assertRaises(ValueError):replication_config(seed,'cpu',Path('/does-not-exist'))

    def test_bc_and_ppo_seed_changes_really_change_weights(self):
        cfg=dict(DEFAULT_POLICY,hidden_sizes=[4,4])
        bc22=KCityBC(cfg,seed=22);bc33=KCityBC(cfg,seed=33)
        self.assertFalse(torch.equal(bc22.policy.trunk[0].weight,bc33.policy.trunk[0].weight))
        for seed in [22,33]:
            a=KCityPPO(cfg,seed=seed);b=KCityPPO(cfg,seed=seed)
            self.assertTrue(all(torch.equal(v,b.policy.state_dict()[k]) for k,v in a.policy.state_dict().items()))
            self.assertEqual(len(a.optimizer.state),0);self.assertEqual(a.num_timesteps,0)

    def test_parent_stop_reaches_child(self):
        with tempfile.TemporaryDirectory() as td:
            child=ReplicationPilot.__new__(ReplicationPilot);child.root=Path(td)/'seed22'
            self.assertFalse(child.stopped())
            (Path(td)/'STOP').touch();self.assertTrue(child.stopped())

    def test_generic_pilot_constructors_use_config_seed(self):
        tree=ast.parse((ROOT/'scripts/kcity/pilot.py').read_text());calls=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ['KCityBC','KCityPPO']:
                seed=next(k.value for k in node.keywords if k.arg=='seed')
                calls.append((node.func.id,ast.unparse(seed)))
        self.assertEqual(calls,[('KCityBC',"self.config['seed']"),('KCityPPO',"self.config['seed']")])


if __name__=='__main__':unittest.main()
