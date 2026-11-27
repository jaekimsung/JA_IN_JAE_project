"""Drive B0 on contract_check seeds and measure local decision exposure before learning."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcity.env.env import SumoKCityEnv, YIELD_GAP_S
from kcity.env.observation import (observed_foes, LANE_LEFT, YIELD_SIGN, INSIDE, LEFT,
                                   corridor, junction_vehicles, next_link)
from kcity.policy.rule_expert import KCityRuleExpert


def audit(job):
    protocol, sid, index = job
    env = SumoKCityEnv(protocol=protocol)
    expert = KCityRuleExpert.from_protocol(env.contract['protocol'])
    try:
        obs, reset = env.reset(options=dict(scenario_id=sid, case_index=index, namespace='contract_check'))
        row = dict(scenario=sid, index=index, case_uid=reset['case']['case_uid'])
        if sid == 'B':
            front, fs, rear, rs = corridor(obs, LEFT)
            speed = reset['state']['ego_speed']
            row.update(front_gap_m=front, rear_gap_m=rear, merge_s=None,
                       moving_pair=front is not None and rear is not None and
                       min(speed + fs * 8.33, speed + rs * 8.33) > .5)
        signals, entries = {}, []
        omitted = omitted_near_entry = 0
        last_foes = {}
        last_rolling = []
        braking = set()
        first_approach_ids = set()
        first_entered_ids = set()
        first_entry_edge = reset['case']['scenario']['start']['edge']
        priority_lanes = env.geometry.links[0][0]['priority_lanes'] if sid == 'C' else {}

        def track_priority_passages(state):
            for vehicle in state['vehicles']:
                lane = vehicle['lane_id']
                if lane not in priority_lanes:
                    continue
                if priority_lanes[lane] is not None:
                    first_approach_ids.add(vehicle['id'])
                elif vehicle['id'] in first_approach_ids:
                    first_entered_ids.add(vehicle['id'])
        while True:
            before = env._state
            priority = []
            if sid == 'C' and before['ego_road_id'] == first_entry_edge:
                track_priority_passages(before)
            if sid == 'C' and obs[YIELD_SIGN] and not obs[INSIDE] and obs[LANE_LEFT] <= .5:
                vehicles = before['vehicles']
                ego = next(v for v in vehicles if v['is_ego'])
                _, link = next_link(env.geometry, ego)
                priority = junction_vehicles(env.geometry, link, vehicles, ego['id'], 'priority_lanes')
                visible = {f[1] for f in observed_foes(env.geometry, link, vehicles, ego['id'])}
                if not env.step_count:
                    row['initial_visible_moving_priority'] = sum(
                        vid in visible and not inside and v['speed'] > .5 for _, vid, v, inside in priority)
                    row['initial_min_tta_s'] = min((gap / v['speed'] for gap, _, v, inside in priority
                                                    if not inside and v['speed'] > .5), default=None)
                missed = any(vid not in visible and (inside or (v['speed'] > .5 and gap/v['speed'] < YIELD_GAP_S))
                             for gap, vid, v, inside in priority)
                omitted += missed
                omitted_near_entry += missed and obs[LANE_LEFT] < .05 and before['ego_speed'] > .5
                now = before['sim_time_s']
                for gap, vid, vehicle, inside in priority:
                    if vehicle['speed'] > .5 and (inside or gap < 20):
                        last_foes[(before['ego_road_id'], vid)] = now
                    if vehicle['accel_mps2'] <= -4.5:
                        braking.add(vid)
            last_rolling = (last_rolling + [before['ego_speed']])[-6:]
            if sid == 'A':
                lights = env.conn.vehicle.getNextTLS(env.ego_id)
                if lights and 0 <= lights[0][2] <= 40:
                    tid, _, _, color = lights[0]
                    sequence = signals.setdefault(tid, [])
                    if not sequence or sequence[-1] != color.lower():
                        sequence.append(color.lower())
            obs, _, done, truncated, step = env.step(expert.predict(obs))
            if sid == 'B' and row['merge_s'] is None and step['action']['lane_change_executed']:
                row['merge_s'] = step['episode_time_s']
            if sid == 'C' and before['ego_road_id'] in ('-77', '-54') and (
                    step['next_state']['ego_road_id'] != before['ego_road_id']):
                moving = [(gap, v['speed']) for gap, _, v, inside in priority if not inside and v['speed'] > .5]
                entries.append(dict(edge=before['ego_road_id'], ego_mps=before['ego_speed'],
                                    moving_priority=len(moving), min_tta_s=min((g/v for g,v in moving),default=None),
                                    rolling_last_3s=min(last_rolling) > .5,
                                    recent_moving_foe=any(edge == before['ego_road_id'] and
                                                          before['sim_time_s'] - t <= 3 for (edge, _),t in last_foes.items())))
                if before['ego_road_id'] == first_entry_edge:
                    entries[-1].update(priority_entered_before_ego=len(first_entered_ids),
                                       entry_time_s=step['episode_time_s'])
            if done or truncated:
                row['end_reason'] = step['end_reason']
                break
        if sid == 'A':
            row['approaches_within_40m'] = signals
        if sid == 'C':
            row.update(entries=entries, critical_foe_omitted_steps=omitted,
                       omitted_within_5m_rolling_steps=int(omitted_near_entry),
                       hard_braking_priority_vehicles=len(braking))
        return row
    finally:
        env.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--cases-per-scenario', type=int, default=12)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--scenarios', nargs='+', choices=list('ABC'), default=list('ABC'))
    args = parser.parse_args()
    if args.cases_per_scenario < 1:
        parser.error('--cases-per-scenario must be positive')
    jobs = [(args.protocol, sid, i) for i in range(args.start_index, args.start_index + args.cases_per_scenario) for sid in args.scenarios]
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(audit, jobs))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, allow_nan=False)+'\n')
    print(dict(Counter((r['scenario'], r['end_reason']) for r in rows)), flush=True)


if __name__ == '__main__':
    main()
