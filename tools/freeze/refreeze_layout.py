"""Re-pin the frozen K-CITY science protocol after a directory relayout.

과학 설정(수치·보상·예산·사례 패널·환경 계약)은 바꾸지 않는다. 바뀌는 것은
FROZEN_PROTOCOL.json의 경로 키와 그 SHA뿐이다. 이전 동결본은 Git commit에서
읽고, 경로를 매핑한 뒤 과학 필드 digest가 동일한지 확인하고 다시 쓴다.

    python -B tools/freeze/refreeze_layout.py --previous <commit> --migration <map.json>

출력: configs/kcity/main_v1/{FROZEN_PROTOCOL.json, LAYOUT_MIGRATION.json,
OPERATIONAL_COMPATIBILITY.json}. 학습·수집·시뮬레이터 실행은 하지 않는다.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from kcity.env.config import digest, file_sha256, load_contract  # noqa: E402
from kcity.experiment import COMPAT, FROZEN, LAYOUT, science_digest  # noqa: E402


def git_json(commit, path):
    return json.loads(subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=ROOT))


def git_sha(commit, path):
    import hashlib
    return hashlib.sha256(subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=ROOT)).hexdigest()


def renamer(files):
    # 파일 경로만 치환한다. 'data'·'results' 같은 디렉터리 이름은 설명문의 일반 단어와 겹친다.
    table = dict(files)
    keys = sorted(table, key=len, reverse=True)
    pattern = re.compile(r'(?<![\w./-])(' + '|'.join(map(re.escape, keys)) + r')(?![\w])')

    def rename(value, changed, where=''):
        if isinstance(value, dict):
            return {rename(k, changed, where + '.key'): rename(v, changed, f'{where}.{k}')
                    for k, v in value.items()}
        if isinstance(value, list):
            return [rename(v, changed, f'{where}[{i}]') for i, v in enumerate(value)]
        if isinstance(value, str):
            new = pattern.sub(lambda m: table[m.group(1)], value)
            if new != value and not where.endswith('.key'):
                changed[where] = dict(before=value, after=new)
            return new
        return value
    return rename


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous', required=True, help='commit holding the pre-relayout freeze')
    parser.add_argument('--migration', required=True, help='JSON with files/dirs/deleted/modules maps')
    args = parser.parse_args()
    previous = subprocess.check_output(['git', 'rev-parse', args.previous], cwd=ROOT, text=True).strip()
    frozen_rel = 'configs/kcity/main_v1/FROZEN_PROTOCOL.json'
    compat_rel = 'configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json'
    old = git_json(previous, frozen_rel)
    old_compat = git_json(previous, compat_rel)
    plan = json.loads(Path(args.migration).read_text(encoding='utf-8'))
    changed = {}
    new = renamer(plan['files'])(old, changed)
    path_fields = {k: v for k, v in changed.items()
                   if not k.startswith(('.source_sha256', '.reference_contract_sha256'))}

    # 동결 대상 파일: 이전 핀을 새 경로로 옮긴 집합 + 새로 생긴 하위 패키지 __init__.
    pins = sorted(new['source_sha256'])
    for init in ['kcity/env/__init__.py', 'kcity/data/__init__.py',
                 'tools/checks/__init__.py', 'tools/main/__init__.py']:
        if init not in pins:
            pins.append(init)
    missing = [p for p in pins if not (ROOT / p).is_file()]
    if missing:
        raise SystemExit(f'Pinned files missing after relayout: {missing}')
    reverse = {v: k for k, v in plan['files'].items()}
    pinned = {}
    for name in sorted(pins):
        before = reverse.get(name, name if name in old['source_sha256'] else None)
        old_sha = old['source_sha256'].get(before) if before else None
        pinned[name] = dict(previous_path=before, previous_sha256=old_sha,
                            sha256=file_sha256(ROOT / name),
                            content_changed=old_sha is not None and old_sha != file_sha256(ROOT / name))
    new['source_sha256'] = {name: entry['sha256'] for name, entry in pinned.items()}
    new['reference_contract_sha256'] = {name: file_sha256(ROOT / name)
                                        for name in new['reference_contract_sha256']}

    # 사례 패널·환경 계약은 경로와 내용이 그대로여야 한다.
    for panel in new['case_panels'].values():
        if file_sha256(ROOT / panel['path']) != panel['sha256']:
            raise SystemExit('Case panel changed: ' + panel['path'])
    contract = load_contract(ROOT / new['base_contract']['path'])
    if digest(contract) != new['base_contract']['loaded_contract_sha256']:
        raise SystemExit('Base environment contract changed')

    migration = dict(
        schema_id='KC-LAYOUT-MIGRATION-v1', revision=2, previous_git_revision=previous,
        purpose='기능별 디렉터리 재구성. 과학 설정·환경·보상·정책·학습 수식·예산·사례 패널 불변.',
        files=plan['files'], dirs=plan['dirs'], deleted=plan['deleted'], modules=plan['modules'],
        renamed_protocol_fields=path_fields, pinned_sources=pinned,
        history_note='research_checks의 JSON과 서버 실행 기록에 남은 옛 경로는 계보로 보존한다. '
                     '이 표로 새 경로를 찾는다.')
    write(LAYOUT, migration)

    new['layout_revision'] = dict(
        revision=2, revised_at=datetime.now().astimezone().isoformat(),
        previous_git_revision=previous,
        previous_frozen_sha256=git_sha(previous, frozen_rel),
        previous_compatibility_sha256=git_sha(previous, compat_rel),
        migration=dict(path=str(LAYOUT.relative_to(ROOT)).replace('\\', '/'),
                       sha256=file_sha256(LAYOUT)))
    new['layout_revision']['science_digest'] = science_digest(new)
    if science_digest(new) != science_digest(renamer(plan['files'])(old, {})):
        raise SystemExit('Science fields differ from the previous freeze')
    write(FROZEN, new)

    compat = dict(
        scientific_sha256=file_sha256(FROZEN), extensions={},
        scope=old_compat['scope'],
        user_authorized_storage_changes=old_compat['user_authorized_storage_changes'],
        documentation_revision=dict(contracts={}),
        history=[dict(
            folded_into_layout_revision=2, previous_git_revision=previous,
            note='이전 운영 확장(kcity_data 온라인 기록·KC-NEXT-REF-v1)과 문서 개정 KC-DOCS-20261116은 '
                 '재동결된 SHA에 포함됐다. 이전 등록 내용은 아래와 Git 이력에 남는다.',
            previous=old_compat)])
    write(COMPAT, compat)
    print(json.dumps(dict(frozen_sha256=file_sha256(FROZEN), pinned_sources=len(pinned),
                          content_changed=sum(e['content_changed'] for e in pinned.values()),
                          renamed_protocol_fields=len(path_fields)), ensure_ascii=False))


if __name__ == '__main__':
    main()
