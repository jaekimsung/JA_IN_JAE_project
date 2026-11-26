"""Dashboard-only continuous drive on the three evaluation corridors."""
import random

from kcity.env.config import make_case
from kcity.env.env import SumoKCityEnv


class ContinuousDemoEnv(SumoKCityEnv):
    def _make_case(self, namespace, scenario_id, index, demand):
        cases = {sid: make_case(self.contract, namespace, sid, index, demand) for sid in 'ABC'}
        self.first_section = scenario_id[0]
        case = cases[self.first_section]
        a, b, c = [part['scenario']['route_edges'] for part in cases.values()]
        if scenario_id == 'BAC':
            connector = ['-0', '-77', '-54']
            self.a_entry = len(b) + len(connector)
            self.b_entry = 0
            # A ends on C's entry edge. Share that occurrence across both sections.
            route = b + connector + a + c[1:]
            self.c_entry = self.a_entry + len(a) - 1
        elif scenario_id == 'ABC':
            connector = ['-54', '-68', '-33', '9', '3#8', '3#7', '3#6', '3#5',
                         '3#4', '3#3', '3#2', '3#1', '3#0', '49', '80', '11', '19',
                         '-3#0', '-3#1', '-3#2', '-3#3']
            self.a_entry = 0
            self.b_entry = len(a) + len(connector)
            self.c_entry = self.b_entry + len(b) + 1
            route = a + connector + b + ['-0'] + c
        else:
            raise ValueError(f'Unknown continuous route: {scenario_id}')
        self.sections = {sid: part['scenario']['interaction'] for sid, part in cases.items()}
        self.section_rng = {sid: random.Random(part['seeds']['initialization'])
                            for sid, part in cases.items()}
        self.started_sections = set()
        self.merge_staged = False
        self.merge_lane = cases['B']['scenario']['start']['lane_index']
        case.update(scenario_id=scenario_id, scenario=dict(
            case['scenario'], id=scenario_id, name='_'.join(scenario_id) + '_continuous',
            task='continuous_drive', route_edges=route, goal=cases['C']['scenario']['goal'],
            episode_limit_s=sum(part['scenario']['episode_limit_s'] for part in cases.values()),
            interaction=sum(self.sections.values(), []), priority_gap_observation_only=True))
        return case

    def _add_interaction_traffic(self):
        self.interaction_ids = []
        self._start_section(self.first_section)
        self.conn.simulationStep()

    def _start_section(self, section):
        if self.background and section not in self.started_sections:
            self._insert_streams(self.sections[section], self.section_rng[section])
            self.started_sections.add(section)

    def step(self, action):
        state = self._state
        index = state['ego_route_index']
        if self.first_section == 'B' and index >= self.a_entry:
            self._start_section('A')
        if self.first_section == 'A' and index == self.b_entry and state['ego_road_id'] == self.geometry.edges[index]:
            # The only inbound connection feeds the through lane. Stage the ego in
            # B's dropping lane with a normal lane request, then let the policy merge.
            if state['ego_lane'] == self.merge_lane:
                self.merge_staged = True
                self._start_section('B')
            elif not self.merge_staged:
                action = [action[0], -1.]
        if index >= self.c_entry - 1:
            self._start_section('C')
        return super().step(action)
