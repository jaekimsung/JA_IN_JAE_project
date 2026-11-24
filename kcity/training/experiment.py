"""Experiment settings (configs/kcity/experiment.json) and run provenance."""
import json

from kcity.env.config import ROOT, digest, file_sha256, git_info  # noqa: F401  (re-exported)
from kcity.policy.checkpoint import run_metadata  # noqa: F401  (re-exported)

EXPERIMENT = ROOT / 'configs/kcity/experiment.json'


def load_experiment(path=EXPERIMENT):
    """Read the experiment settings and check the case panels it points to are intact."""
    spec = json.loads((ROOT / path).read_text(encoding='utf-8'))
    if spec.get('schema_id') != 'KC-EXPERIMENT-v1':
        raise ValueError('Unsupported experiment settings schema')
    contract = spec['base_contract']
    if 'sha256' in contract and file_sha256(ROOT / contract['path']) != contract['sha256']:
        raise ValueError('Environment protocol differs from experiment settings')
    for name, panel in spec['case_panels'].items():
        if file_sha256(ROOT / panel['path']) != panel['sha256']:
            raise ValueError(f'Case panel {name} differs from experiment settings: {panel["path"]}')
    return spec


def experiment_sha256(spec):
    return digest(spec)


def is_pilot(spec):
    purpose = spec.get('run_purpose', 'main')
    if purpose not in ('main', 'pilot'):
        raise ValueError('run_purpose must be main or pilot')
    return purpose == 'pilot'


def training_config(spec, kind, seed=None, method=None, **extra):
    """Resume identity of a run: same kind/seed/method/settings. Code version is recorded, not enforced."""
    return dict(kind=kind, seed=seed, method=method, experiment_sha256=experiment_sha256(spec), **extra)
