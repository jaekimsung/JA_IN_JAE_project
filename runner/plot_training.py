"""Display reusable training-log comparisons; save selected figures with the window toolbar.

    python runner/plot_training.py
    python runner/plot_training.py --run runs/bc_main_seed11 --run runs/bc_main_seed22
    python runner/plot_training.py --run 'BC 11=runs/bc_main_seed11'
    python runner/plot_training.py --root runs/new_experiment

With no --run, recursively discover curve.jsonl under --root (default: runs).
No images or other output files are written by this script.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import warnings


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_run(path, label=None):
    """Read a snapshot, tolerating only a partially written final JSONL record."""
    path = Path(path)
    curve = path if path.is_file() else path / 'curve.jsonl'
    text = curve.read_text(encoding='utf-8')
    lines = text.splitlines()
    groups = {'BC': [], 'RL': []}
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == len(lines)-1 and not text.endswith('\n'):
                warnings.warn(f'{curve}: ignoring incomplete last line', stacklevel=2)
                continue
            raise ValueError(f'{curve}:{index+1}: invalid JSON') from exc
        if not isinstance(row, dict):
            raise ValueError(f'{curve}:{index+1}: expected an object')
        if finite(row.get('transitions')):
            groups['RL'].append(row)
        elif finite(row.get('updates')):
            groups['BC'].append(row)
        else:
            warnings.warn(f'{curve}:{index+1}: no updates/transitions; skipping', stacklevel=2)
    if not any(groups.values()):
        raise ValueError(f'{curve}: no training records yet')
    if all(groups.values()):
        raise ValueError(f'{curve}: mixed BC and RL records')
    kind = 'RL' if groups['RL'] else 'BC'
    axis = 'transitions' if kind == 'RL' else 'updates'
    # A restarted log may repeat a point. Keep the most recently recorded value.
    rows = sorted({row[axis]: row for row in groups[kind]}.values(), key=lambda row: row[axis])
    dev = []
    for summary in sorted(curve.parent.glob('dev/T*/SUMMARY.json')):
        body = json.loads(summary.read_text(encoding='utf-8'))
        if finite(body.get('actual_transitions')) and isinstance(body.get('aggregate'), dict):
            dev.append(body)
    best = None
    best_path = curve.parent / 'BEST.json'
    if best_path.exists():
        best = json.loads(best_path.read_text(encoding='utf-8'))
    return dict(label=label or curve.parent.name, kind=kind, axis=axis, rows=rows,
                dev=dev, best=best, folder=curve.parent)


def metric_names(runs, sections):
    return sorted({key for run in runs for row in run['rows'] for section in sections
                   for key, value in (row.get(section) or {}).items() if finite(value)})


def series(rows, axis, section, metric):
    """Missing metrics remain gaps, including RL's no-update warmup."""
    return ([row[axis] for row in rows],
            [(row.get(section) or {}).get(metric) if finite((row.get(section) or {}).get(metric))
             else math.nan for row in rows])


def make_figures(runs):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import StrMethodFormatter

    figures = []

    def grid(title, metrics, xlabel):
        columns = min(3, len(metrics))
        rows = math.ceil(len(metrics)/columns)
        fig, axes = plt.subplots(rows, columns, squeeze=False,
                                 figsize=(5.2*columns, 3.8*rows), constrained_layout=True)
        fig.canvas.manager.set_window_title(title)
        fig.suptitle(title + '\nSave selected figures using the toolbar Save button', fontsize=12)
        flat = list(axes.flat)
        for ax, metric in zip(flat, metrics):
            ax.set_title(metric.replace('_', ' '))
            ax.set_xlabel(xlabel)
            ax.set_ylabel(metric)
            ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
            ax.grid(alpha=.25)
        for ax in flat[len(metrics):]:
            ax.set_visible(False)
        figures.append(fig)
        return flat

    for kind in ('BC', 'RL'):
        selected = [run for run in runs if run['kind'] == kind]
        sections = ('training', 'validation') if kind == 'BC' else ('metrics',)
        metrics = metric_names(selected, sections)
        if not metrics:
            if selected:
                warnings.warn(f'{kind}: no numeric loss/metric records yet (possibly warmup)', stacklevel=2)
            continue
        axes = grid(f'{kind} training logs', metrics,
                    'Optimizer updates' if kind == 'BC' else 'Environment transitions')
        for ax, metric in zip(axes, metrics):
            for number, run in enumerate(selected):
                color = plt.get_cmap('tab20')(number % 20)
                for section in sections:
                    x, y = series(run['rows'], run['axis'], section, metric)
                    if not any(math.isfinite(value) for value in y):
                        continue
                    style = '--' if section == 'validation' else '-'
                    label = f'{run["label"]} / {section}'
                    ax.plot(x, y, style, color=color, marker='.', markersize=4, label=label)
                # Identify the recorded BC best without selecting a new checkpoint.
                if kind == 'BC' and metric == 'loss' and run['best']:
                    chosen = run['best'].get('path', '')
                    for row in run['rows']:
                        val = (row.get('validation') or {}).get('loss')
                        if chosen == f'update-{row["updates"]:06d}' and finite(val):
                            ax.scatter([row['updates']], [val], marker='*', s=100,
                                       color=color, edgecolors='black', linewidths=.5, zorder=5)
            ax.legend(fontsize=8)

    evaluated = [run for run in runs if run['dev']]
    metrics = sorted({key for run in evaluated for row in run['dev']
                      for key, value in row['aggregate'].items()
                      if key.endswith('_rate') and finite(value)})
    if metrics:
        axes = grid('RL dev evaluation rates', metrics, 'Environment transitions')
        for ax, metric in zip(axes, metrics):
            for run in evaluated:
                points = sorted((row['actual_transitions'], row['aggregate'].get(metric))
                                for row in run['dev'])
                ax.plot([x for x, y in points],
                        [y if finite(y) else math.nan for x, y in points],
                        marker='.', label=run['label'])
            ax.set_ylim(-.02, 1.02)
            ax.legend(fontsize=8)
    return figures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run', action='append', default=[], metavar='[LABEL=]PATH',
                        help='run folder or curve.jsonl; repeat to compare runs')
    parser.add_argument('--root', type=Path, default=Path('runs'),
                        help='recursively discover logs here when --run is omitted')
    args = parser.parse_args(argv)
    inputs = []
    if args.run:
        for item in args.run:
            label, sep, path = item.partition('=')
            inputs.append((Path(path) if sep else Path(item), label if sep else None))
    else:
        if not args.root.is_dir():
            parser.error(f'Log root does not exist: {args.root}')
        inputs = [(p, p.parent.relative_to(args.root).as_posix())
                  for p in sorted(args.root.rglob('curve.jsonl'))]
    if not inputs:
        parser.error('No curve.jsonl files found. Use --run PATH or --root DIR.')
    runs = []
    for path, label in inputs:
        try:
            run = load_run(path, label)
        except (OSError, ValueError) as exc:
            if args.run:
                parser.error(str(exc))
            warnings.warn(str(exc), stacklevel=2)
            continue
        runs.append(run)
        print(f'{run["kind"]}: {run["label"]} | {len(run["rows"])} points | {run["folder"]}', flush=True)
    if not runs:
        parser.error('No readable training records found.')
    try:
        import matplotlib
        import matplotlib.pyplot as plt
    except ImportError:
        parser.error('Matplotlib is required: python -m pip install matplotlib')
    # Refuse a silent noninteractive run instead of writing images as a fallback.
    if matplotlib.get_backend().lower() not in {name.lower() for name in matplotlib.rcsetup.interactive_bk}:
        parser.error(f'Backend {matplotlib.get_backend()} cannot open graph windows. '
                     'Run in a desktop terminal with MPLBACKEND=TkAgg (Tk required).')
    with plt.rc_context({'axes.spines.top': False, 'axes.spines.right': False}):
        figures = make_figures(runs)
        if not figures:
            parser.error('No numeric metrics to plot yet.')
        print('Close all graph windows to exit. Use toolbar Save to save a selected figure. '
              'This is a snapshot; rerun to read newer logs.', flush=True)
        plt.show()


if __name__ == '__main__':
    main()
