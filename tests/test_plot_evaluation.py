"""Evaluation plots preserve episode counts and never save figures automatically."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runner.plot_evaluation import load_evaluations,make_figures


class EvaluationPlotTests(unittest.TestCase):
    def tearDown(self):
        plt.close('all')

    def test_discovery_skips_demand_copies_and_draws_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'BC_seed11';demand=run/'demand_1';demand.mkdir(parents=True)
            records=[dict(requested_case_uid='case1',scenario_id='B',case_index=1,
                attempt_valid=True,primary_end_reason='arrival',compliant_completion=True,
                situations=dict(lane_drop=dict(required=True,position_m=68.59,wait_s=20.,done=True)))]
            summary=dict(aggregate=dict(n_valid=1,completion_rate=1.,compliant_completion_rate=1.,collision_rate=0.),
                         diagnostics=dict(B_late_change_threshold_m=67.59))
            for folder in (run,demand):
                (folder/'SUMMARY.json').write_text(json.dumps(summary))
                (folder/'EPISODES.json').write_text(json.dumps(records))
            before=set(root.rglob('*'))
            runs=load_evaluations(root)
            self.assertEqual(len(runs),1)
            self.assertEqual(runs[0]['label'],'BC_seed11')
            figures=make_figures(runs)
            self.assertEqual(len(figures),3)
            matrix=figures[1].axes[0].images[0].get_array()
            self.assertEqual(float(matrix[0,0]),1.)
            for fig in figures:fig.canvas.draw()
            self.assertEqual(before,set(root.rglob('*')))
            (run/'EPISODES.json').write_text(json.dumps(records*2))
            with self.assertRaisesRegex(ValueError,'duplicate'):
                load_evaluations(root)


if __name__=='__main__':unittest.main()
