"""Plot existing and live log snapshots without running learners or saving images."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runner.plot_training import load_run, make_figures, series


class PlotTrainingTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_live_tail_resume_duplicate_and_corrupt_interior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'curve.jsonl'
            path.write_text('{"updates": 2, "training": {"loss": 9}}\n'
                            '{"updates": 1, "training": {"loss": 3}}\n'
                            '{"updates": 2, "training": {"loss": 1}}\n{"updates":')
            with self.assertWarnsRegex(UserWarning, 'incomplete last line'):
                run = load_run(path)
            self.assertEqual([r['updates'] for r in run['rows']], [1, 2])
            self.assertEqual(run['rows'][-1]['training']['loss'], 1)
            path.write_text('BROKEN\n{"updates": 1}\n')
            with self.assertRaisesRegex(ValueError, ':1: invalid JSON'):
                load_run(path)

    def test_bc_rl_unknown_metrics_warmup_dev_and_no_saved_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bc, rl = root/'bc', root/'rl'
            bc.mkdir(); rl.mkdir()
            (bc/'curve.jsonl').write_text(json.dumps(dict(updates=10,
                training=dict(loss=.2, lane_mse=.1), validation=dict(loss=.3)))+'\n')
            (bc/'BEST.json').write_text(json.dumps(dict(path='update-000010', loss=.3)))
            (rl/'curve.jsonl').write_text('\n'.join(map(json.dumps, [
                dict(transitions=5, updates=0, metrics=None),
                dict(transitions=10, updates=5, metrics=dict(critic_loss=4., custom_metric=-2.))]))+'\n')
            dev = rl/'dev/T0000010'
            dev.mkdir(parents=True)
            (dev/'SUMMARY.json').write_text(json.dumps(dict(actual_transitions=10,
                aggregate=dict(compliant_completion_rate=.5, collision_rate=0., nested=dict(count=3)))))
            before = set(root.rglob('*'))
            runs = [load_run(bc), load_run(rl)]
            x, y = series(runs[1]['rows'], 'transitions', 'metrics', 'critic_loss')
            self.assertEqual(x, [5, 10])
            self.assertTrue(math.isnan(y[0]))
            self.assertEqual(y[1], 4.)
            figures = make_figures(runs)
            self.assertEqual(len(figures), 3)
            titles = [ax.get_title() for fig in figures for ax in fig.axes]
            self.assertIn('custom metric', titles)
            loss_ax = figures[0].axes[1]  # sorted BC metrics: lane_mse, loss
            self.assertEqual(len(loss_ax.lines), 2)
            self.assertEqual(len(loss_ax.collections), 1)  # recorded best marker
            for fig in figures:
                fig.canvas.draw()
            self.assertEqual(set(root.rglob('*')), before)


if __name__ == '__main__':
    unittest.main()
