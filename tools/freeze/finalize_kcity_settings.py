"""Finish the authorized KC06 -> scientific-settings -> commit/push handoff.

This read-only watcher never launches a learner, changes the running pilot, or
turns on main training. Outputs are produced only after both replication seeds
and all nine seed/method dev100 evaluations pass integrity/completeness checks.
Scientific choices are preregistered in REQUEST.json, not chosen for a winner.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / 'docs/research_checks/KC-SETTINGS-20261115-01'
REPLICATES = Path('/home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/replicates_v1')
ORIGINAL = Path('/home/heven/kcity_research_runs/KC-06-20261115-01')
PYTHON = '/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python'
REMOTE = 'https://github.com/jaekimsung/JA_IN_JAE_project.git'


def now():
    return datetime.now().astimezone().isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def verify_checkpoint(path):
    path = Path(path)
    manifest = read(path / 'SHA256.json')
    for name, expected in manifest.items():
        file = (path / name).resolve()
        require(file.is_relative_to(path.resolve()), 'Unsafe checkpoint manifest path')
        require(sha(file) == expected, 'Changed checkpoint: ' + str(file))
    return dict(path=str(path), manifest_sha256=sha(path / 'SHA256.json'), verified=True)


def validate_records(records, planned=100):
    require(len(records) == planned, 'Evaluation is incomplete')
    ids = [r['requested_case_uid'] for r in records]
    require(len(set(ids)) == planned, 'Duplicate evaluation cases')
    require(all(r['namespace'] == 'dev' for r in records), 'Final/train cases in dev evaluation')
    require(all(r['attempt_valid'] and r['data_quality_valid'] for r in records),
            'Infrastructure or data-quality failure requires review')
    # Policy failures deliberately remain valid; low success never blocks reporting.
    return ids


def collect_results():
    supervisor = read(REPLICATES / 'STATUS.json')
    require(supervisor['phase'] == 'COMPLETE' and supervisor['completed_seeds'] == [22, 33],
            'Both replication seeds must finish before settings freeze')
    rows, curves, references, counters, panel = [], [], {}, {}, None
    for seed in [11, 22, 33]:
        root = ORIGINAL / 'pilot_v1' if seed == 11 else REPLICATES / f'seed{seed}'
        status = read(root / 'STATUS.json')
        require(status['phase'] == 'PILOT_TRAINING_COMPLETE', 'Pilot did not complete')
        require(status['main_research_training_started'] is False, 'Unexpected main training')
        require(status['bc_updates'] == 1000, 'BC budget mismatch')
        counters[str(seed)] = dict(bc_updates=status['bc_updates'], methods=status['methods'],
                                  peak_rss_kib=status.get('peak_rss_kib'))
        for method in ['B2', 'B3']:
            require(status['methods'][method]['transitions'] == 50000, 'PPO budget mismatch')
            for point in [0, 10000, 20000, 30000, 40000, 50000]:
                path = root / method / f'eval-{point:06d}.json'
                data = read(path)
                require(data['actual_transitions'] == point, 'Curve checkpoint mismatch')
                require(len(data['records']) == 3, 'Pilot curve case count mismatch')
                require(all(r['namespace'] == 'dev' for r in data['records']), 'Non-dev pilot curve')
                curves.append(dict(seed=seed, method=method, transitions=point,
                                   aggregate=data['aggregate']))
                references[str(path)] = sha(path)
        for method in ['BC', 'B2', 'B3']:
            folder = (ORIGINAL / 'diagnosis_v1' / f'dev100-{method}' if seed == 11
                      else root / 'dev100' / method)
            records = read(folder / 'EPISODES.json')
            ids = validate_records(records)
            if panel is None:
                panel = ids
            require(ids == panel, 'Policies were evaluated on different case panels')
            summary = read(folder / 'SUMMARY.json')
            checkpoint = (root / 'bc' / read(root / 'bc/BEST.json')['path'] if method == 'BC'
                          else root / method / 'checkpoint-050000')
            model = verify_checkpoint(checkpoint)
            expected = (summary['source']['sha256'] if seed == 11 else summary['manifest_sha256'])
            require(expected == model['manifest_sha256'], 'Evaluation model manifest mismatch')
            rows.append(dict(seed=seed, method=method, aggregate=summary['aggregate'], model=model))
            references[str(folder / 'EPISODES.json')] = sha(folder / 'EPISODES.json')
            references[str(folder / 'SUMMARY.json')] = sha(folder / 'SUMMARY.json')
        references[str(root / 'STATUS.json')] = sha(root / 'STATUS.json')
    exposure = []
    for path in sorted(ORIGINAL.glob('feasibility-*.json')):
        data = read(path)
        require(len(data['records']) == 10, 'Incomplete feasibility condition')
        for r in data['records']:
            require(r['attempt_valid'] and r['data_quality_valid'], 'Invalid feasibility record')
        exposure.append(dict(condition=path.stem, records=data['records'], aggregate=data['aggregate']))
        references[str(path)] = sha(path)
    require(len(exposure) == 9, 'Need all nine feasibility conditions')
    return dict(phase='COMPLETE', completed_at=now(), results=rows, pilot_dev3_curves=curves,
                feasibility=exposure, evidence_sha256=references, training_seeds=3,
                training_counters=counters, pilot_ppo_transitions_total=300000,
                pilot_bc_updates_total=3000, pilot_expert_unique_transitions=10000,
                final_cases_executed=0, main_training_started=False)


def build_protocol(request, evidence):
    sys.path.insert(0, str(ROOT))
    from kcity.env.config import load_contract, digest, make_case
    contract = load_contract()
    learning = read(ROOT / 'configs/kcity/v1/learning.json')
    from kcity.policy.policy import KCityPolicy, bc_optimizer
    policy = KCityPolicy(learning['policy'])
    bc_optimizer(policy, learning['bc']['learning_rate'])
    parameters = dict(total=sum(p.numel() for p in policy.parameters()),
                      bc_trainable=sum(p.numel() for p in policy.parameters() if p.requires_grad))
    panel_dir = ROOT / 'configs/kcity/main_v1'
    panels = {}
    for namespace, multipliers in [('dev', [1.0]), ('final', [1.0, 1.5, 2.0])]:
        cases = [make_case(contract, namespace, sid, i, multiplier)
                 for multiplier in multipliers for sid, n in [('A', 30), ('B', 30), ('C', 40)]
                 for i in range(n)]
        path = panel_dir / f'cases_{namespace}.json'
        write(path, dict(namespace=namespace, cases=cases, cases_sha256=digest(cases), executed=False))
        panels[namespace] = dict(path=str(path.relative_to(ROOT)), sha256=sha(path), cases=len(cases))
    sources = {str(p.relative_to(ROOT)): sha(p) for directory in
               ['kcity', 'rl', 'tools/map', 'tools/checks', 'legacy/highway/env', 'configs/kcity/v1']
               for p in sorted((ROOT / directory).rglob('*'))
               if p.is_file() and p.suffix in ['.py', '.json']}
    protocol = dict(schema_id='KC-SCIENTIFIC-FREEZE-v1', protocol_id=request['protocol_id'],
        frozen_at=now(), scientific_settings_frozen=True, training_enabled=False,
        launch_ready=False, status='SCIENTIFIC_SETTINGS_FROZEN_NOT_LAUNCH_READY',
        question='K-CITY 복합 교통 환경에서 전문가 사전학습의 효과와 한계 분석',
        methods=dict(B0='observation-aligned rule expert', B1='BC-only selected by validation loss',
                     B2='fresh PPO-only', B3='same-seed main BC actor initialization then PPO'),
        base_contract=dict(path='configs/kcity/v1/protocol.json', sha256=sha(ROOT/'configs/kcity/v1/protocol.json'),
                           loaded_contract_sha256=digest(contract)),
        timing=contract['protocol']['timing'], control=contract['protocol']['control'],
        traffic=dict(contract['protocol']['traffic'], feasibility_status='90 pilot episodes completed',
                     exposure_policy=request['decisions']['traffic_exposure']),
        policy=learning['policy'], parameters=parameters,
        ppo=learning['ppo'], bc=dict(learning['bc'], dataset_loader_status='KC05 implemented; main pool not collected',
            updates_per_seed=10000, batch_size=256, validate_every_updates=500,
            train_view_rows=200000, validation_view_rows=50000, loss='acceleration MSE + lane cross entropy'),
        rewards=request['decisions']['rewards'], seeds=[11,22,33],
        budgets=dict(expert_valid_transitions_min=1000000, ppo_transitions_per_method_seed=1000000,
                     ppo_methods=['B2','B3'], ppo_total_transitions=6000000,
                     archive_per_budget_end_policy=500000, archive_total_transitions=3000000,
                     planned_submission_unique_transitions_min=10000000,
                     final_episodes=3000, pilot_reuse_for_main=False),
        case_panels=panels, case_generation=request['decisions']['case_generation'],
        metrics=request['decisions']['metrics'], model_selection=request['decisions']['model_selection'],
        scope_limits=request['decisions']['scope_limits'],
        operational_remaining=request['operational_remaining'],
        reference_contract_sha256={name:sha(ROOT/name) for name in
            ['docs/specs/DATA_COLLECTION_SPEC.md','docs/specs/KCITY_EVALUATION.md','docs/specs/KCITY_DATA_PIPELINE.md']},
        source_sha256=sources, pilot_summary_sha256=sha(CHECK/'SUMMARY.json'))
    write(panel_dir/'FROZEN_PROTOCOL.json', protocol)
    return protocol


def write_report(evidence, protocol):
    lines = ['# K-CITY 본 실험 설정 확정', '',
        '추가 seed22·33의 학습 및 dev100 평가 완료 후 작성한 기록이다. '
        '**과학 설정 확정 완료, 본 수집·본 학습 미시작, 실행 준비 미완료**를 구분한다.', '',
        '## 실제 pilot 결과', '',
        '각 seed: fresh BC1,000updates, B2/B3 각각50,000전이. 동일 pilot expert10k를 공유했으며 '
        'seed11 가중치를 seed22/33으로 이어받지 않았다. 각 최종 정책은 같은 dev100개에서 평가했다.', '',
        '| seed | 정책 | 완주/100 | 충돌 | 적색 진입 Episode | 완료 사례 평균(s) | 실패 포함 시간(s) |',
        '|---|---|---:|---:|---:|---:|---:|']
    for row in evidence['results']:
        a = row['aggregate']
        mean = a['mean_elapsed_completed']
        lines.append(f"| {row['seed']} | {row['method']} | {a['n_completed']} | {a['n_collision']} | "
                     f"{a['n_red_episode']} | {mean if mean is None else round(mean,3)} | {a['penalized_time_all']:.3f} |")
    lines += ['', '100개 사례는 독립 학습100회가 아니다. 학습 seed는3개이며, seed별 결과와 중간 checkpoint 실패를 '
        '함께 보존한다. 최종100/100이나 짧은 완주시간만으로 학습 방식의 우월성을 선언하지 않는다. '
        '초기 이점은 동일 전이 dev곡선과 BC 추가비용을 함께 비교한다.', '',
        '총 pilot PPO300,000전이·BC3,000updates이며 expert10,000전이는 공유 원본을 한 번만 센다. '
        'seed/방법별 실제 rollout·optimizer 횟수와 측정 속도는 SUMMARY.json의 training_counters에 기록한다.', '',
        '## 확정한 조건', '',
        '- 정책2Hz·물리0.1초·warmup60초·제한300초, 73-D, 공통[256,256], SUMO 안전31/512.',
        '- 요청 교통량600vph, 증분 평가900/1200vph, 차량4종 동등 비율. GUI4배 수요/0.02초는 제외.',
        '- 보상과 mask·PPO/BC 계수는 검증된 pilot 구현을 유지한다. 부당 대기 penalty는0이며 별도 원인 지표는 미지원이다.',
        '- 초기HV≥10 후보는 모든 case를 보장하지 못했다. 이를 사후 통과로 고쳐 쓰지 않는다. '
        '낮은 노출 case도 포함하고 초기/최소/시간가중HV·선행차 노출을 전수 보고한다. '
        '지금 고정하는 것은 이 운영적 수요 조건이며 실제 고밀도 상호작용 보장은 아니다.',
        '- 관측만 사용하는 전문가로 새1M pool, BC3seed×10k updates, PPO2방식×3seed×1M. '
        'pilot 모델/자료는 본 학습으로 이월하지 않는다.',
        '- 개발100개·최종수요별100개 패널을 파일과 SHA로 고정한다. 이번 작업은 final을 실행하지 않는다.',
        '- 목표는 지원하는 충돌/적색 판정 기준의 완주율≥0.80을 연속2회 만족. '
        '50k 간격에서 두 평가 중 첫 시점을 기록하고 두번째에서 확인한다. 미달은 censored.',
        '- BC는 최저val loss, B1/B3는 동일actor. PPO 주최종은1M budget-end; 최종평가로 모델을 고르지 않는다.',
        '- 실패 포함 완주/규칙판정·대기·차선실패·seed변동·실제시간/전이 및 BC비용을 같이 비교한다.', '',
        '## 시행 전 남은 운영 작업', '']
    lines += [f'- {item}' for item in protocol['operational_remaining']]
    lines += ['', '설정 확정은 아래 frozen JSON을 기준으로 한다. 기존 KC01 설정은 역사적 후보 및 실행 호환 계약으로 '
        '그대로 보존한다. 새 JSON은 과학 명세이며 기존 KC01 loader의 실행 입력으로 바로 사용할 수 없다.', '',
        '[설정 원본](../../../configs/kcity/main_v1/FROZEN_PROTOCOL.json) · '
        '[집계·원자료 SHA](SUMMARY.json) · [진도](STATUS.json) · [결정 사전기록](REQUEST.json)', '']
    (CHECK/'README.md').write_text('\n'.join(lines))
    for file in ['docs/research/RESEARCH_STATUS.md', 'docs/research/EXPERIMENTS.md', 'docs/specs/EXECUTION_PROTOCOL.md']:
        path = ROOT/file
        text = path.read_text()
        marker = '<!-- KC-SETTINGS-20261115-01 -->'
        require(marker not in text, 'Duplicate settings record')
        title, body = text.split('\n', 1)
        update = (f'\n{marker}\n\n2026-11-15 이후 최신 완료 기록: **추가3seed pilot 집계 및 본 실험 과학 설정 확정 완료**. '
            '[확정 설정·실제 결과](../research_checks/KC-SETTINGS-20261115-01/README.md). '
            '아래 과거 미실행·후속동결 문구는 당시 단계의 이력이다. '
            '**본 데이터 수집/본 BC·PPO 미시작, launch_ready=false**. '
            '본 실행기·GPU 장기재개·저장/원격백업 검증은 다음 운영 단계로 남긴다.\n')
        path.write_text(title+'\n'+update+body)
    path = ROOT/'docs/research_checks/KC-06-SEEDS-20261115-01/README.md'
    path.write_text(path.read_text()+'\n\n## 후속 완료 기록\n\nseed22/33의 학습·평가 완료. '
        '[3seed 집계와 설정 확정](../KC-SETTINGS-20261115-01/README.md)을 따른다. 위 실행 중 문구는 착수 당시 기록이다.\n')
    (ROOT/'configs/kcity/main_v1/README.md').write_text(
        '# K-CITY 본 실험 과학 설정\n\nFROZEN_PROTOCOL.json은 본 실험 설계 확정본이다. '
        'scientific_settings_frozen=true와 training_enabled=false / launch_ready=false는 서로 다른 상태다. '
        '기존 KC01 loader에 바로 넘기지 않는다. 운영 실행기 연결은 다음 단계다.\n\n'
        'cases_dev.json / cases_final.json은 생성만 한 고정 패널이며, final 실행 결과가 아니다. '
        '관측/보상 코드와 맵은 SHA로 참조하고 기존 v1 파일은 변경하지 않았다.\n')


def check_worktree(request):
    require(command('git','rev-parse','HEAD') == request['expected_head'], 'HEAD changed during training; review before publishing')
    require(command('git','branch','--show-current') == 'main', 'Branch changed')
    require(command('git','remote','get-url','origin') == REMOTE, 'Remote changed')
    require(not command('git','diff','--cached','--name-only'), 'Preexisting staged changes')
    for file, expected in request['input_sha256'].items():
        require(sha(ROOT/file) == expected, 'Authorized input edited while waiting: '+file)
    changed = set(command('git','ls-files','--modified','--others','--exclude-standard').splitlines())
    require(changed <= set(request['allowed_paths']), 'Unrelated changes; refusing automatic commit: '+repr(changed-set(request['allowed_paths'])))


def finalize(request, publish):
    check_worktree(request)
    evidence = collect_results()
    write(CHECK/'SUMMARY.json', evidence)
    protocol = build_protocol(request, evidence)
    write_report(evidence, protocol)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1')
    with (CHECK/'TESTS.log').open('w') as log:
        result = subprocess.run([PYTHON,'-B','-m','unittest','discover','-s','tests','-p','test_kcity*.py','-v'],
                                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    require(result.returncode == 0, 'Regression checks failed; not committing')
    require(subprocess.run(['git','diff','--check'],cwd=ROOT).returncode == 0, 'Diff whitespace check failed')
    write(CHECK/'STATUS.json',dict(phase='SETTINGS_FROZEN_CHECKED',updated_at=now(),
        scientific_settings_frozen=True,launch_ready=False,main_training_started=False,
        pilot_completed_seeds=[11,22,33],tests_passed=True,publish_requested=publish))
    if not publish:
        return
    # The allowlist includes only known code, checks and documents; never models/replay.
    require(command('git','rev-parse','HEAD') == request['expected_head'], 'HEAD changed before commit')
    changed = set(command('git','ls-files','--modified','--others','--exclude-standard').splitlines())
    require(changed <= set(request['allowed_paths']), 'Unexpected files before commit')
    command('git','add','--',*sorted(changed))
    command('git','commit','-m','K-CITY 3seed pilot 결과와 본 실험 과학 설정 확정')
    commit = command('git','rev-parse','HEAD')
    for attempt in range(3):
        pushed = subprocess.run(['git','push','origin','main'],cwd=ROOT)
        if pushed.returncode == 0:
            break
        time.sleep(5)
    require(pushed.returncode == 0, 'Normal push rejected/failed; no force push attempted')
    remote = command('git','ls-remote','origin','refs/heads/main').split()[0]
    require(remote == commit, 'Remote commit verification failed')
    # Publication receipt outside Git avoids a commit containing its own hash.
    receipt = dict(phase='PUSHED',completed_at=now(),commit=commit,remote=REMOTE,
                   remote_sha_verified=True,scientific_settings_frozen=True,
                   launch_ready=False,main_training_started=False,
                   report=str(CHECK/'README.md'))
    write(REPLICATES.parent/'SETTINGS_PUBLICATION.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait',action='store_true')
    parser.add_argument('--publish',action='store_true')
    args = parser.parse_args()
    request = read(CHECK/'REQUEST.json')
    request_sha = sha(CHECK/'REQUEST.json')
    owner = REPLICATES.parent/'SETTINGS_WATCHER_OWNER.json'
    if owner.exists():
        previous = read(owner)
        try:
            os.kill(previous['pid'],0)
        except ProcessLookupError:
            owner.unlink()
        else:
            raise RuntimeError('Settings watcher already running')
    with owner.open('x') as stream:
        json.dump(dict(pid=os.getpid(),started_at=now()),stream)
    try:
        while True:
            status = read(REPLICATES/'STATUS.json')
            if status['phase'] == 'COMPLETE':
                break
            require(status['phase'] not in ['FAILED','STOPPED'], 'Pilot failed or stopped; automatic freeze cancelled')
            require(args.wait, 'Pilot still running; use --wait to defer finalization')
            os.kill(status['pid'],0)
            write(CHECK/'STATUS.json',dict(phase='WAITING_FOR_PILOT',checked_at=now(),
                active_seed=status.get('active_seed'),pilot_phase=status['phase'],
                scientific_settings_frozen=False,main_training_started=False,publish_requested=args.publish))
            time.sleep(30)
        require(sha(CHECK/'REQUEST.json') == request_sha, 'Settings decisions changed while waiting')
        finalize(request,args.publish)
    except BaseException as error:
        write(CHECK/'STATUS.json',dict(phase='REVIEW_REQUIRED',updated_at=now(),
            error=type(error).__name__+': '+str(error),main_training_started=False))
        raise
    finally:
        owner.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
