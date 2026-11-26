"""Lossless row references and bounded, separately retained learner bundles.

Data shards stay immutable even when an obsolete learner bundle is removed.
Publish a verified external bundle BEFORE its referring data shard, and verify
latest/previous/evaluation bundles BEFORE pruning any older bundle.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from kcity.env.config import file_sha256

NEXT_CODEC = 'KC-NEXT-REF-v1'
CHECKPOINT_MODE = 'external_retained_v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def atomic(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.partial-' + uuid.uuid4().hex)
    with temp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def encode_rows(rows):
    """Leave terminal and final-in-shard next values explicit."""
    for index, row in enumerate(rows):
        result = dict(row)
        if index + 1 < len(rows) and not (row['terminated'] or row['truncated']):
            following = rows[index + 1]
            require(
                row['episode_uid'] == following['episode_uid'] and following['t'] == row['t'] + 1,
                'Next reference cannot cross an Episode or skip a timestep',
            )
            require(
                row['next_state'] == following['state']
                and row['next_observation'] == following['observation'],
                'Next reference is not lossless',
            )
            result.pop('next_state')
            result.pop('next_observation')
            result['next_reference'] = following['transition_uid']
        yield result


def decode_rows(rows):
    """One-row lookahead; return exactly the original logical records."""
    iterator = iter(rows)
    current = next(iterator, None)
    while current is not None:
        following = next(iterator, None)
        current = dict(current)
        if 'next_reference' in current:
            require(following is not None, 'Final shard row must store explicit next fields')
            require(
                not (current['terminated'] or current['truncated']),
                'Terminal row cannot reference a new Episode',
            )
            require(
                'next_state' not in current and 'next_observation' not in current,
                'Ambiguous explicit/referenced next',
            )
            require(
                current.pop('next_reference') == following['transition_uid']
                and current['episode_uid'] == following['episode_uid']
                and following['t'] == current['t'] + 1,
                'Broken next-row reference',
            )
            current['next_state'] = deepcopy(following['state'])
            current['next_observation'] = deepcopy(following['observation'])
        else:
            require(
                'next_state' in current and 'next_observation' in current, 'Missing next fields/reference'
            )
        yield current
        current = following


def verify_bundle(path, manifest_sha=None):
    path = Path(path)
    if manifest_sha is not None:
        require(file_sha256(path / 'SHA256.json') == manifest_sha, 'Retained checkpoint manifest changed')
    expected = json.loads((path / 'SHA256.json').read_text())
    actual = {
        p.relative_to(path).as_posix(): file_sha256(p)
        for p in path.rglob('*')
        if p.is_file() and p.name != 'SHA256.json'
    }
    require(actual == expected, 'Retained checkpoint file set/SHA mismatch')
    return file_sha256(path / 'SHA256.json')


def shard_reference(folder):
    path = Path(folder) / 'environment/REFERENCE.json'
    return json.loads(path.read_text()) if path.exists() else None


def checkpoint_from_shard(folder):
    folder = Path(folder).resolve()
    ref = shard_reference(folder)
    if ref is None:
        return folder / 'environment'  # Historical embedded bundles.
    require(ref['schema'] == CHECKPOINT_MODE, 'Unsupported checkpoint reference')
    root = folder.parent.parent
    path = (root / ref['path']).resolve()
    require(
        path.is_relative_to(root / 'checkpoints') and not path.is_symlink(), 'Unsafe checkpoint reference'
    )
    verify_bundle(path, ref['manifest_sha256'])
    return path


def save_external(root, stub, save, transitions):
    root, stub = Path(root), Path(stub)
    directory = root / 'checkpoints'
    directory.mkdir(exist_ok=True)
    path = directory / f'T{transitions:012d}-{uuid.uuid4().hex}'
    save(path)  # Native immutable bundle writer fsyncs before returning.
    checksum = verify_bundle(path)
    stub.mkdir()
    ref = dict(
        schema=CHECKPOINT_MODE,
        path=path.relative_to(root).as_posix(),
        manifest_sha256=checksum,
        transitions=transitions,
    )
    atomic(stub / 'REFERENCE.json', ref)
    return ref


def expected_retention(folders, policy):
    require(
        type(policy['keep_recent']) is int
        and policy['keep_recent'] >= 2
        and type(policy['evaluation_interval_transitions']) is int
        and policy['evaluation_interval_transitions'] > 0,
        'Invalid checkpoint retention policy',
    )
    references = []
    for folder in folders:
        ref = shard_reference(folder)
        require(ref is not None, 'Missing external checkpoint reference')
        require(ref['schema'] == CHECKPOINT_MODE, 'Unsupported external checkpoint schema')
        references.append(ref)
    recent = references[-policy['keep_recent'] :]
    return references, {
        r['path']: r
        for r in references
        if r in recent or r['transitions'] % policy['evaluation_interval_transitions'] == 0
    }


def sync_retention(root, folders, policy):
    """Called only by the single owner after a durable shard commit/recovery."""
    root = Path(root)
    refs, keep = expected_retention(folders, policy)
    # Never prune while the newest/previous/evaluation copies are unverified.
    for ref in keep.values():
        path = (root / ref['path']).resolve()
        require(path.is_relative_to((root / 'checkpoints').resolve()), 'Unsafe retained checkpoint path')
        verify_bundle(path, ref['manifest_sha256'])
    registry = dict(
        schema=CHECKPOINT_MODE,
        committed_shards=len(folders),
        committed_transitions=refs[-1]['transitions'] if refs else 0,
        policy=policy,
        retained=list(keep.values()),
    )
    # Mark older refs as intentionally disposable BEFORE removing their bundles.
    atomic(root / 'CHECKPOINTS.json', registry)
    removed = []
    for path in sorted((root / 'checkpoints').glob('T*')):
        if path.relative_to(root).as_posix() in keep:
            continue
        owned_name = re.fullmatch(r'T\d{12}-[0-9a-f]{32}', path.name) or re.fullmatch(
            r'T\d{12}-[0-9a-f]{32}\.partial-[A-Za-z0-9_-]+', path.name
        )
        require(
            owned_name is not None and path.is_dir() and not path.is_symlink(),
            'Unexpected object in owned checkpoint store',
        )
        removed.append(
            dict(
                path=path.relative_to(root).as_posix(),
                bytes=sum(p.stat().st_size for p in path.rglob('*') if p.is_file()),
            )
        )
        shutil.rmtree(path)
    if removed:
        with (root / 'CHECKPOINT_RETENTION.jsonl').open('a') as log:
            log.write(
                json.dumps(dict(committed_transitions=registry['committed_transitions'], removed=removed))
                + '\n'
            )
            log.flush()
            os.fsync(log.fileno())
    return registry


def verify_retention(root, folders, policy):
    root = Path(root)
    refs, keep = expected_retention(folders, policy)
    registry = json.loads((root / 'CHECKPOINTS.json').read_text())
    require(
        registry
        == dict(
            schema=CHECKPOINT_MODE,
            committed_shards=len(folders),
            committed_transitions=refs[-1]['transitions'] if refs else 0,
            policy=policy,
            retained=list(keep.values()),
        ),
        'Checkpoint retention registry is stale; recover writer before reading',
    )
    cumulative = 0
    for folder, ref in zip(folders, refs):
        cumulative += json.loads((Path(folder) / 'SHARD.json').read_text())['rows']
        require(ref['transitions'] == cumulative, 'Checkpoint/data transition boundary differs')
    for folder in folders:
        ref = shard_reference(folder)
        if ref['path'] in keep:
            checkpoint_from_shard(folder)
    return registry
