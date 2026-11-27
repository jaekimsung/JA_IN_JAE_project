"""Side-by-side numbers for the three problem situations and the three hypotheses.

    python runner/report.py \
        --eval B0=runs/eval/expert --eval B1=runs/eval/B1_seed11 \
        --eval B2=runs/eval/B2_seed11 --eval B3=runs/eval/B3_seed11 \
        --run B2=runs/B2_seed11 --run B3=runs/B3_seed11 --output runs/report.json

--eval takes an output folder of runner/evaluate.py, --run an RL run folder of runner/train_rl.py.

    H1  BC는 정지·출발 시점이 어긋나면 실패하는 상황(신호 정지, 양보)에서 오차가 누적된다.
        → 방법별·상황별 실패율
    H2  사전 데이터 없는 강화학습(B2)은 같은 예산에서 대기에 머물거나 규칙 위반이 많다.
        → 기한 초과·정지 시간, 위반 수, 차선 변경 위치·요청 수
    H3  RLPD(B3)는 적은 환경 경험으로 BC보다 높은 규칙 준수 완주율에 도달한다.
        → dev 곡선의 시작·최저·최종 값, 목표 도달 전이 수

The script only lays the numbers out; it does not declare a winner.
"""
import sys
from pathlib import Path

import argparse
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.evaluation.situations import SITUATIONS


def labelled(text):
    label, _, path = text.partition('=')
    if not label or not path:
        raise argparse.ArgumentTypeError('expected LABEL=PATH')
    return label, Path(path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rate(value):
    return '-' if value is None else f'{100 * value:.1f}%'


def num(value, fmt='.1f'):
    return '-' if value is None else format(value, fmt)


def evaluation_rows(label, folder):
    rows = []
    for path in sorted(folder.glob('demand_*/SUMMARY.json')):
        body = read(path)
        s = body['aggregate']
        rows.append(dict(
            label=label, demand=body['demand_multiplier'], n=s['n_valid'],
            collision_rate=s['collision_rate'], completion_rate=s['completion_rate'],
            compliant_completion_rate=s['compliant_completion_rate'],
            n_deadline=s['n_deadline'], standstill_s_mean=s['stops']['standstill_s_mean'],
            situations=s['situations']))
    if not rows:
        raise SystemExit(f'No demand_*/SUMMARY.json under {folder}')
    return rows


def run_row(label, folder):
    curve = [read(p) for p in sorted(folder.glob('dev/T*/SUMMARY.json'))]
    points = [(c['actual_transitions'], c['aggregate']['compliant_completion_rate'],
               c['aggregate']['collision_rate']) for c in curve]
    known = [p for p in points if p[1] is not None]
    updates = []
    if (folder / 'curve.jsonl').exists():
        updates = [json.loads(line) for line in (folder / 'curve.jsonl').read_text().splitlines() if line]
        updates = [u for u in updates if u.get('metrics')]
    lowest = min(known, key=lambda p: p[1]) if known else None
    first_policy_update = next((u for u in updates if not u['metrics'].get('critic_warmup')), None)
    return dict(
        label=label, dev_points=len(points),
        start=known[0][1] if known else None, start_transitions=known[0][0] if known else None,
        lowest=lowest[1] if lowest else None, lowest_transitions=lowest[0] if lowest else None,
        final=known[-1][1] if known else None, final_transitions=known[-1][0] if known else None,
        final_collision_rate=points[-1][2] if points else None,
        warmup_until=first_policy_update['transitions'] if first_policy_update and updates[0]['metrics'].get('critic_warmup') else None,
        p_lane_change_first=updates[0]['metrics'].get('p_lane_change') if updates else None,
        p_lane_change_last=updates[-1]['metrics'].get('p_lane_change') if updates else None,
        curve=points)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--eval', action='append', type=labelled, default=[], metavar='LABEL=DIR')
    parser.add_argument('--run', action='append', type=labelled, default=[], metavar='LABEL=DIR')
    parser.add_argument('--output', type=Path, help='also write the numbers as JSON')
    args = parser.parse_args()
    if not args.eval and not args.run:
        parser.error('give at least one --eval or --run')
    evaluations = [row for label, folder in args.eval for row in evaluation_rows(label, folder)]
    runs = [run_row(label, folder) for label, folder in args.run]

    if evaluations:
        print('기본 성능')
        print(f"{'method':<10} {'demand':>6} {'n':>4} {'collision':>10} {'completion':>11} {'compliant':>10}")
        for r in evaluations:
            print(f"{r['label']:<10} {r['demand']:>6g} {r['n']:>4} {rate(r['collision_rate']):>10} "
                  f"{rate(r['completion_rate']):>11} {rate(r['compliant_completion_rate']):>10}")
        print('\nH1  상황별 실패율 (그 상황에서 끝난 미완주 Episode / 그 상황을 지난 Episode)')
        print(f"{'method':<10} {'demand':>6} " + ' '.join(f'{name:>16}' for name in SITUATIONS) + f" {'other':>6}")
        for r in evaluations:
            cells = [f"{rate(r['situations'][name]['failure_rate'])} ({r['situations'][name]['n_failed_here']}/"
                     f"{r['situations'][name]['n_exposed']})" for name in SITUATIONS]
            print(f"{r['label']:<10} {r['demand']:>6g} " + ' '.join(f'{c:>16}' for c in cells) +
                  f" {r['situations']['other']['n_failed_here']:>6}")
        print('\nH2  기다림과 차선 변경')
        print(f"{'method':<10} {'demand':>6} {'deadline':>9} {'stop_s':>7} {'sig wait_s':>11} {'LC done':>8} "
              f"{'LC at m':>8} {'LC req':>7} {'LC rej':>7} {'target HV':>10}")
        for r in evaluations:
            signal, lane = r['situations']['signal_chain'], r['situations']['lane_drop']
            print(f"{r['label']:<10} {r['demand']:>6g} {r['n_deadline']:>9} {num(r['standstill_s_mean']):>7} "
                  f"{num(signal['wait_s_mean']):>11} {rate(lane['done_rate']):>8} {num(lane['position_m_mean']):>8} "
                  f"{num(lane['requests_mean']):>7} {num(lane['rejected_mean']):>7} "
                  f"{num(lane['target_lane_hv_mean'], '.2f'):>10}")
        print('\n③  비신호 교차로')
        print(f"{'method':<10} {'demand':>6} {'passes':>7} {'cross traffic':>14} {'min dist m':>11} {'collisions':>11}")
        for r in evaluations:
            u = r['situations']['unsignalized']
            print(f"{r['label']:<10} {r['demand']:>6g} {u['passes']:>7} {rate(u['cross_traffic_fraction']):>14} "
                  f"{num(u['min_distance_m']):>11} {u['collisions']:>11}")
    if runs:
        print('\nH3  학습 중 dev 규칙 준수 완주율 (시작 → 최저 → 최종)')
        print(f"{'run':<10} {'evals':>6} {'start':>8} {'lowest':>8} {'at T':>9} {'final':>8} {'at T':>9} "
              f"{'warm-up to':>11} {'p(LC) first':>12} {'p(LC) last':>11}")
        for r in runs:
            print(f"{r['label']:<10} {r['dev_points']:>6} {rate(r['start']):>8} {rate(r['lowest']):>8} "
                  f"{num(r['lowest_transitions'], 'd'):>9} {rate(r['final']):>8} {num(r['final_transitions'], 'd'):>9} "
                  f"{num(r['warmup_until'], 'd'):>11} {num(r['p_lane_change_first'], '.3f'):>12} "
                  f"{num(r['p_lane_change_last'], '.3f'):>11}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(evaluations=evaluations, runs=runs), ensure_ascii=False, indent=2) + '\n',
                               encoding='utf-8')


if __name__ == '__main__':
    main()
