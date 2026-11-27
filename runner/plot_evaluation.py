"""Show evaluation comparisons without saving images.

    python runner/plot_evaluation.py --root runs/eval/bc_all_seeds_dev_20261121_163315
    python runner/plot_evaluation.py --eval BC11=path/to/evaluation --eval BC22=another/evaluation

Uses SUMMARY.json and EPISODES.json. The root may contain multiple runs; per-demand
copies are skipped when a run already has its own summary. Save with the GUI toolbar.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import warnings

import numpy as np


def load_evaluations(root):
    root = Path(root)
    summaries = [root/'SUMMARY.json'] if (root/'SUMMARY.json').exists() else []
    summaries += sorted(root.rglob('SUMMARY.json'), key=lambda p: (len(p.parts), p))  # parents before demand copies
    found, runs = set(), []
    for path in summaries:
        if path.resolve() in found:
            continue
        found.add(path.resolve())
        body = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(body.get('aggregate'), dict) or not (path.parent/'EPISODES.json').exists():
            continue
        if any(parent/'SUMMARY.json' in [run['summary_path'] for run in runs]
               for parent in path.parent.parents if parent != path.parent):
            continue
        records = json.loads((path.parent/'EPISODES.json').read_text(encoding='utf-8'))
        uids = [r['requested_case_uid'] for r in records]
        if len(uids) != len(set(uids)):
            raise ValueError(f'{path}: duplicate evaluation cases')
        valid = [r for r in records if r['attempt_valid']]
        if len(valid) != body['aggregate']['n_valid']:
            raise ValueError(f'{path}: summary/episode count mismatch')
        runs.append(dict(label=path.parent.relative_to(root).as_posix() if path.parent != root else root.name,
                         summary_path=path, body=body, records=records, valid=valid))
    return runs


def make_figures(runs):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    figures = []
    labels = [r['label'] for r in runs]
    colors = [plt.get_cmap('tab10')(i % 10) for i in range(len(runs))]

    def figure(title, cols=1):
        fig, axes = plt.subplots(1, cols, figsize=(7*cols, 5.5), squeeze=False, constrained_layout=True)
        fig.canvas.manager.set_window_title(title)
        fig.suptitle(title+'\nSnapshot of recorded evaluations | Save using the toolbar', fontsize=12)
        figures.append(fig)
        return list(axes[0])

    rate_ax, reasons_ax = figure('Evaluation overview', 2)
    x = np.arange(len(runs)); width = .25
    for offset, (key, title, color) in enumerate([
            ('completion_rate', 'Completion', '#3d8d99'),
            ('compliant_completion_rate', 'Rule-compliant completion', '#3458a4'),
            ('collision_rate', 'Collision', '#d75c4c')]):
        values = [r['body']['aggregate'].get(key) for r in runs]
        values = [v if v is not None else math.nan for v in values]
        bars = rate_ax.bar(x+(offset-1)*width, values, width, label=title, color=color)
        rate_ax.bar_label(bars, labels=[f'{v:.0%}' if math.isfinite(v) else 'n/a' for v in values], fontsize=8, padding=3)
    rate_ax.set_xticks(x, labels); rate_ax.set_ylim(0, 1.15)
    rate_ax.yaxis.set_major_formatter(PercentFormatter(1)); rate_ax.set_ylabel('Rate among valid cases')
    rate_ax.legend(fontsize=8, loc='upper center'); rate_ax.grid(axis='y', alpha=.2)
    counts = [Counter(r['primary_end_reason'] for r in run['valid']) for run in runs]
    reasons = sorted(set().union(*(c.keys() for c in counts)))
    reason_colors = {'arrival':'#3d8d99', 'collision':'#d75c4c', 'red_entry':'#e6a43b',
                     'yield_violation':'#9562b7', 'deadline':'#727c89'}
    left = np.zeros(len(runs))
    for reason in reasons:
        values = np.array([c[reason] for c in counts])
        bars = reasons_ax.barh(labels, values, left=left, label=reason, color=reason_colors.get(reason))
        reasons_ax.bar_label(bars, labels=[str(v) if v else '' for v in values], label_type='center', fontsize=9)
        left += values
    reasons_ax.set_xlabel('Valid episodes (one primary end reason per episode)')
    reasons_ax.legend(fontsize=8, loc='upper center', bbox_to_anchor=(.5, -.13), ncol=3)
    reasons_ax.set_title('All attempts: '+', '.join(f'{r["label"]}: {len(r["valid"])}/{len(r["records"])} valid' for r in runs), fontsize=9)

    scenarios = sorted({r['scenario_id'] for run in runs for r in run['valid']})
    matrix = np.full((len(runs), len(scenarios)), np.nan)
    notes = {}
    for i, run in enumerate(runs):
        for j, scenario in enumerate(scenarios):
            records = [r for r in run['valid'] if r['scenario_id'] == scenario]
            # Unknown rule-check status must not become a zero-success measurement.
            if records and all(r.get('compliant_completion') is not None for r in records):
                successes = sum(r['compliant_completion'] is True for r in records)
                matrix[i,j] = successes/len(records)
                notes[i,j] = f'{matrix[i,j]:.1%}\n{successes}/{len(records)}'
    ax, = figure('Rule-compliant completion by scenario')
    im = ax.imshow(np.ma.masked_invalid(matrix), vmin=0, vmax=1, cmap='YlGnBu', aspect='auto')
    ax.set_xticks(range(len(scenarios)), [dict(A='A: signals', B='B: lane merge', C='C: yield').get(s,s) for s in scenarios])
    ax.set_yticks(range(len(runs)), labels)
    for i in range(len(runs)):
        for j in range(len(scenarios)):
            ax.text(j,i,notes.get((i,j),'n/a'),ha='center',va='center',
                    color='white' if matrix[i,j]>.65 else 'black',fontsize=12)
    ax.figure.colorbar(im,ax=ax,format=PercentFormatter(1),label='Rule-compliant completion')

    lane_runs = [(run,color) for run,color in zip(runs,colors)
                 if any(r.get('situations',{}).get('lane_drop',{}).get('required') for r in run['valid'])]
    if lane_runs:
        pos_ax, wait_ax = figure('Scenario B: merge timing and waiting',2)
        thresholds = set()
        for run,color in lane_runs:
            records = [r for r in run['valid'] if r['situations']['lane_drop']['required']]
            lane = [r['situations']['lane_drop'] for r in records]
            indices = [r['case_index'] for r in records]
            pos_ax.scatter(indices,[r['position_m'] if r['position_m'] is not None else math.nan for r in lane],
                           color=color,label=f'{run["label"]} (changed {sum(r["done"] is True for r in lane)}/{len(lane)})',alpha=.8)
            wait_ax.plot(indices,[r['wait_s'] for r in lane],'.',color=color,label=run['label'],alpha=.8)
            threshold = run['body'].get('diagnostics',{}).get('B_late_change_threshold_m')
            if threshold is not None: thresholds.add(threshold)
        for threshold in sorted(thresholds):
            pos_ax.axhline(threshold,color='#d75c4c',ls='--',lw=1,label=f'Last 1 m starts at {threshold:g} m')
        pos_ax.set_ylabel('Position along approach lane at change (m)')
        pos_ax.set_title('Higher position means a later merge')
        wait_ax.set_ylabel('Standstill time before required lane change (s)')
        wait_ax.set_title('Includes waiting for traffic; not all waiting is unjustified')
        for ax in (pos_ax,wait_ax):
            ax.set_xlabel('Fixed case index');ax.grid(alpha=.2);ax.legend(fontsize=8)
    # Avoid silently implying that evaluations used paired conditions when they did not.
    panels = [{r['requested_case_uid'] for r in run['records']} for run in runs]
    if panels and any(p != panels[0] for p in panels[1:]):
        warnings.warn('Runs contain different case panels; compare conditions before interpreting differences.',stacklevel=2)
    return figures


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root',type=Path,help='evaluation root containing one or more runs')
    parser.add_argument('--eval',action='append',default=[],metavar='LABEL=DIR')
    args=parser.parse_args()
    runs=[]
    try:
        if args.eval:
            for item in args.eval:
                label,sep,path=item.partition('=')
                if not sep or not label: parser.error('--eval requires LABEL=DIR')
                selected=load_evaluations(path)
                for run in selected:
                    run['label']=label if len(selected)==1 else f'{label}/{run["label"]}'
                runs.extend(selected)
        elif args.root:
            runs=load_evaluations(args.root)
        else:parser.error('Give --root DIR or repeat --eval LABEL=DIR')
        if not runs:parser.error('No matching SUMMARY.json and EPISODES.json found')
    except (OSError,ValueError) as exc:parser.error(str(exc))
    import matplotlib
    import matplotlib.pyplot as plt
    if matplotlib.get_backend().lower() not in {s.lower() for s in matplotlib.rcsetup.interactive_bk}:
        parser.error('Interactive backend required. Run from a desktop terminal with MPLBACKEND=TkAgg.')
    with plt.rc_context({'axes.spines.top':False,'axes.spines.right':False}):
        figures=make_figures(runs)
        print(f'Displaying {len(figures)} graph windows for {len(runs)} evaluations. '
              'Nothing is saved automatically; use toolbar Save.',flush=True)
        plt.show()


if __name__=='__main__':main()
