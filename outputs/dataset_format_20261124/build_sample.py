"""Prepare a 15-row real-data CSV using the supplied column template."""
from collections import Counter
import csv
import hashlib
import itertools
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from kcity.data.dataset import SCHEMA_ID, read_shard, shard_directories
from kcity.env.observation import OBSERVATION_ID

template = Path('/home/heven/Downloads/sample_15.csv')
original_template_hash = hashlib.sha256(template.read_bytes()).hexdigest()
with template.open(encoding='utf-8-sig', newline='') as stream:
    base_columns = next(csv.reader(stream))
assert len(base_columns) == 19

extra_columns = [
    'run_uid', 'case_uid', 'episode_uid', 'transition_uid', 'traffic_seed_group_uid',
    'data_split', 'scenario_id', 'policy_id', 'train_seed', 'policy_checkpoint_sha256',
    'action.lane_change_executed', 'action.known_rejection_reasons',
    'reward_components.progress', 'reward_components.arrival', 'reward_components.collision',
    'reward_components.red_entry', 'reward_components.yield_violation', 'reward_components.time',
    'sim_tick_t', 'sim_tick_tp1', 'control_dt_s', 'episode_time_s',
    'observation_valid', 'next_observation_valid', 'end_reason',
    'traffic_interval.departed_hv', 'traffic_interval.arrived_hv',
    'next_detected_vehicles', 'events', 'substep_samples',
    'learning.update_step', 'learning.random_action',
    'dataset.schema_id', 'dataset.observation_id', 'dataset.source_stage',
    'dataset.data_id', 'dataset.part', 'dataset.shard',
]
columns = base_columns + extra_columns
assert len(set(columns)) == len(columns)
pool = ROOT / 'runs/main_collection_20261119_193244/expert'
dataset = pool / 'part-00/dataset'
config = json.loads((dataset / 'RUN.json').read_text())
release = json.loads((dataset / 'RELEASE.json').read_text())
selected = []
counts = Counter()
for shard in shard_directories(dataset):
    for row in read_shard(shard):
        sid = row['scenario_id']
        if counts[sid] >= 5:
            continue
        counts[sid] += 1
        metadata = dict(schema_id=SCHEMA_ID, observation_id=OBSERVATION_ID,
                        source_stage=config['source_stage'], data_id=release['data_id'],
                        part='part-00', shard=shard.name)
        selected.append((row, metadata))
        if len(selected) == 15:
            break
    if len(selected) == 15:
        break
assert counts == Counter(A=5, B=5, C=5)


def value_at(row, metadata, column):
    if column.startswith('dataset.'):
        return metadata[column.split('.', 1)[1]]
    obj = row
    for component in column.split('.'):
        if not isinstance(obj, dict) or component not in obj:
            return None
        obj = obj[component]
    return obj


def cell(value):
    if value is None:
        return ''
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return str(value)


output = HERE / 'kcity_sample_15.csv'
with output.open('x', encoding='utf-8-sig', newline='') as stream:
    writer = csv.writer(stream, lineterminator='\r\n')
    writer.writerow(columns)
    for row, metadata in selected:
        writer.writerow([cell(value_at(row, metadata, key)) for key in columns])

# Re-read every cell and reconcile all source fields, including restored next references.
with output.open(encoding='utf-8-sig', newline='') as stream:
    reader = csv.DictReader(stream)
    assert reader.fieldnames[:19] == base_columns and reader.fieldnames == columns
    written = list(reader)
assert len(written) == 15
for record, (row, metadata) in zip(written, selected):
    for key in columns:
        value = value_at(row, metadata, key)
        actual = record[key]
        if isinstance(value, (list, dict)):
            assert json.loads(actual) == value, key
        else:
            assert actual == cell(value), key
    assert len(json.loads(record['observation'])) == 63
    assert len(json.loads(record['next_observation'])) == 63
    assert sum(json.loads(record[k]) for k in columns if k.startswith('reward_components.')) == row['reward']
    # Every source top-level field and every flattened dictionary leaf has a destination.
    for key, value in row.items():
        if key in {'action', 'event', 'reward_components', 'traffic_interval', 'learning'}:
            assert all(f'{key}.{leaf}' in columns for leaf in value), key
        else:
            assert key in columns, key
assert hashlib.sha256(template.read_bytes()).hexdigest() == original_template_hash
report = dict(output=str(output), template=str(template), rows=15, base_columns=19,
              added_columns=len(extra_columns), total_columns=len(columns),
              scenario_counts=dict(counts), observation_dimensions=63,
              encoding='UTF-8 with BOM', line_endings='CRLF', booleans='True/False',
              nested_values='compact JSON; full original State and arrays preserved',
              missing_values='empty cells (not zero)',
              columns=columns, template_sha256=original_template_hash,
              output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
              all_cells_match_source=True, all_source_fields_preserved=True,
              template_unchanged=True)
(HERE / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: report[k] for k in ['output', 'rows', 'base_columns', 'added_columns',
                                      'total_columns', 'scenario_counts', 'all_source_fields_preserved']},
                 ensure_ascii=False, indent=2))
