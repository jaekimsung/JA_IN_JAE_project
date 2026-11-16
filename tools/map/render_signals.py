"""Render the signal placement evidence and assumed approach control diagram."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from kcity.common import MAP, sumo_tools

sumolib = sumo_tools()


def main():
    net = sumolib.net.readNet(str(MAP / 'kcity.net.xml'), withInternal=True)
    design = json.loads((MAP / 'reports/signal_design.json').read_text())
    lines = [lane.getShape() for edge in net.getEdges() for lane in edge.getLanes()]
    fig, axes = plt.subplots(1, 2, figsize=(12, 11), constrained_layout=True,
                             gridspec_kw={'width_ratios': [1, 1.15]})
    for ax, bounds, title in zip(axes, [(-185, 185, -550, 550), (-155, 175, -365, 165)],
                                ['Full network', 'Signalized urban area']):
        ax.add_collection(LineCollection(lines, colors='#6b7e90', linewidths=1))
        ax.set(xlim=bounds[:2], ylim=bounds[2:], aspect='equal', title=title,
               xlabel='SUMO local X (m)', ylabel='SUMO local Y (m)')
        ax.set_facecolor('#f5f8fb')
        ax.grid(alpha=.15)
        for signal in design['selected']:
            x, y = signal['sumo_xy']
            if not (bounds[0] < x < bounds[1] and bounds[2] < y < bounds[3]):
                continue
            assumed = signal['junction_id'] in ['112', '176']
            color = '#d8861c' if assumed else '#087f8c'
            ax.scatter(x, y, s=85, color=color, edgecolor='white', zorder=4)
            ax.annotate(signal['junction_id'], (x, y), xytext=(6, 7), textcoords='offset points',
                        fontsize=9, fontweight='bold', zorder=5,
                        bbox=dict(facecolor='white', alpha=.85, edgecolor='none', pad=1))
        for nid in ['477', '747']:
            x, y = net.getNode(nid).getCoord()
            ax.scatter(x, y, s=35, marker='s', color='#b74c54', zorder=4)
        if ax is axes[1]:
            for candidate in design['candidates']:
                for match in candidate['mgeo_matches']:
                    x, y = match['xy']
                    ax.scatter(x, y, marker='+', color='#7e57a2', s=20, zorder=3)
    axes[0].scatter([], [], color='#087f8c', label='12: MGEO signal / stop-node candidates')
    axes[0].scatter([], [], color='#d8861c', label='2: complex-junction assumptions')
    axes[0].scatter([], [], color='#b74c54', marker='s', label='2: retained all-way stops')
    axes[0].legend(loc='lower left', fontsize=8)
    axes[1].scatter([], [], color='#7e57a2', marker='+', label='MGEO reference stop nodes')
    axes[1].legend(loc='lower left', fontsize=8)
    fig.suptitle('K-CITY | 14 demand-actuated signal controllers', fontsize=17, fontweight='bold')
    fig.supxlabel('One approach at a time | Green 6-25 s | Yellow 3 s | All-red 3-7 s\n'
                  'Placement and timing are modeled assumptions; field operation is not verified.', fontsize=10)
    fig.savefig(MAP / 'reports/signal_layout.png', dpi=170)
    plt.close(fig)


if __name__ == '__main__':
    main()
