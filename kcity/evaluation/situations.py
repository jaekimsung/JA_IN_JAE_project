"""The three decision problems of the K-CITY routes and their per-Episode measurements.

    signal_chain  ① 연속 감응식 신호 통과   시나리오 A: 신호 647 → 268 → 764 → 169, 간격 26~34 m, 녹색 6~25초 가변
    lane_drop     ② 혼잡 속 필수 차선 변경   시나리오 B: Edge -3#4 (68.6 m)의 끝나는 차로에서 통과 차로의 차량 흐름 사이로 합류
    unsignalized  ③ 비신호 교차로 양보       시나리오 C: 759 합류(우선 흐름에 양보)와 464 비보호 좌회전

Locations come from maps/kcity/kcity.net.xml (tests check them against the network).
All measurements are derived from the transition trace (events, substep samples, full State),
so collection, evaluation and dataset validation produce the same values.
"""
import math

SITUATIONS = dict(
    signal_chain=dict(
        title='① 연속 감응식 신호 통과',
        junctions=('647', '268', '764', '169'),
        approach_edges=('-13', '-71', '-31', '-42'),
    ),
    lane_drop=dict(title='② 혼잡 속 필수 차선 변경', junctions=(), approach_edges=('-3#4',)),
    unsignalized=dict(
        title='③ 비신호 교차로 교차 차량 양보',
        junctions=('759', '464'),
        approach_edges=('-77', '-54'),
    ),
)
STANDSTILL_MPS = 0.1
SIGNAL_WAIT_RANGE_M = 50.0


def junction_of(road_id):
    """Junction ID for a SUMO internal Edge (':464_3' -> '464'); None on a normal Edge."""
    if not road_id or not road_id.startswith(':'):
        return None
    return road_id[1:].rsplit('_', 1)[0]


def situation_of(road_id):
    """Which problem situation a road location belongs to (None elsewhere)."""
    junction = junction_of(road_id)
    for name, spec in SITUATIONS.items():
        if (junction in spec['junctions']) if junction else (road_id in spec['approach_edges']):
            return name
    return None


def new_state():
    """JSON-able accumulator; lives inside EpisodeMetrics so it survives checkpoints."""
    return dict(
        visited=[],
        last_situation=None,
        signal_crossings=0,
        signal_red_entries=0,
        signal_yellow_entries=0,
        signal_wait_s=0.0,
        signal_box_stop_s=0.0,
        lane_drop_requests=0,
        lane_drop_rejected=0,
        lane_drop_done=False,
        lane_drop_position_m=None,
        lane_drop_wait_s=0.0,
        lane_drop_target_hv_sum=0,
        lane_drop_decisions=0,
        unsignalized_passes=0,
        unsignalized_conflict_passes=0,
        unsignalized_min_distance_m=None,
        unsignalized_collisions=0,
        unsignalized_yield_violations=0,
        inside=None,
        inside_conflict=False,
    )


def update(s, case, info):
    """Accumulate one decision interval (`info` is the env step info or a dataset row)."""
    before, after = info.get('state') or {}, info.get('next_state') or {}
    road, next_road = before.get('ego_road_id'), after.get('ego_road_id')
    here = situation_of(road)
    if here is not None:
        s['last_situation'] = here
        if here not in s['visited']:
            s['visited'].append(here)
    dt = info['control_dt_s']
    events = info['events']

    # ① signals: what the light showed at each stop line, waiting at red, stopping inside the box
    for event in events:
        if event['type'] == 'tls_crossing' and event.get('tls_id') in SITUATIONS['signal_chain']['junctions']:
            s['signal_crossings'] += 1
            s['signal_red_entries'] += bool(event.get('red_entry'))
            s['signal_yellow_entries'] += event.get('signal_before') in ('y', 'Y')
    for sample in info['substep_samples']:
        if (
            sample.get('speed_mps') is not None
            and sample['speed_mps'] < STANDSTILL_MPS
            and sample.get('next_tls_state') in ('r', 'y', 'Y')
            and sample.get('next_tls_distance_m') is not None
            and sample['next_tls_distance_m'] <= SIGNAL_WAIT_RANGE_M
        ):
            s['signal_wait_s'] += sample['dt_s']
    speed = after.get('ego_speed')
    stopped = speed is not None and speed < STANDSTILL_MPS
    if stopped and junction_of(next_road) in SITUATIONS['signal_chain']['junctions']:
        s['signal_box_stop_s'] += dt

    # ② lane drop: requests, the gap it had to find, where the change happened, stalling at the lane end
    required = case['scenario'].get('required_lane_change')
    if required and road == required['edge'] and not s['lane_drop_done']:
        action = info['action']
        s['lane_drop_requests'] += action['lane_change'] != 0
        s['lane_drop_rejected'] += bool(action['lane_change'] != 0 and action['known_rejection_reasons'])
        s['lane_drop_decisions'] += 1
        s['lane_drop_target_hv_sum'] += sum(
            1
            for v in before.get('vehicles') or []
            if not v['is_ego'] and v['road_id'] == road and v['lane'] in required['required_exit_lanes']
        )
        changed = any(
            e['type'] == 'lane_change' and e['from_lane'].rsplit('_', 1)[0] == road for e in events
        )
        if changed and after.get('ego_lane') in required['required_exit_lanes']:
            s['lane_drop_done'] = True
            s['lane_drop_position_m'] = before.get('ego_lane_pos')
        elif stopped:
            s['lane_drop_wait_s'] += dt

    # ③ unsignalized junctions: passes, whether another vehicle shared the junction, closest approach
    junction = junction_of(next_road)
    if junction not in SITUATIONS['unsignalized']['junctions']:
        junction = None
    if junction != s['inside']:
        if s['inside'] is not None:
            s['unsignalized_passes'] += 1
            s['unsignalized_conflict_passes'] += s['inside_conflict']
        s['inside'], s['inside_conflict'] = junction, False
    if junction is not None:
        ego = next((v for v in after.get('vehicles') or [] if v['is_ego']), None)
        for v in after.get('vehicles') or []:
            if ego is None or v['is_ego'] or junction_of(v['road_id']) != junction:
                continue
            s['inside_conflict'] = True
            distance = math.hypot(v['x'] - ego['x'], v['y'] - ego['y'])
            if s['unsignalized_min_distance_m'] is None or distance < s['unsignalized_min_distance_m']:
                s['unsignalized_min_distance_m'] = distance
    if any(e['type'] == 'collision' for e in events) and situation_of(next_road or road) == 'unsignalized':
        s['unsignalized_collisions'] += 1
    s['unsignalized_yield_violations'] += sum(e['type'] == 'yield_violation' for e in events)


def finish(s, case, completed):
    """Per-Episode record. `failure_situation` is where a non-completed Episode ended."""
    passes = s['unsignalized_passes'] + (s['inside'] is not None)
    conflicts = s['unsignalized_conflict_passes'] + bool(s['inside'] is not None and s['inside_conflict'])
    required = bool(case['scenario'].get('required_lane_change'))
    decisions = s['lane_drop_decisions']
    return dict(
        visited=list(s['visited']),
        failure_situation=None if completed else (s['last_situation'] or 'other'),
        signal_chain=dict(
            crossings=s['signal_crossings'],
            red_entries=s['signal_red_entries'],
            yellow_entries=s['signal_yellow_entries'],
            wait_s=s['signal_wait_s'],
            box_stop_s=s['signal_box_stop_s'],
        ),
        lane_drop=dict(
            required=required,
            done=s['lane_drop_done'] if required else None,
            position_m=s['lane_drop_position_m'],
            requests=s['lane_drop_requests'],
            rejected=s['lane_drop_rejected'],
            wait_s=s['lane_drop_wait_s'],
            target_lane_hv_mean=s['lane_drop_target_hv_sum'] / decisions if decisions else None,
        ),
        unsignalized=dict(
            passes=passes,
            passes_with_cross_traffic=conflicts,
            min_distance_m=s['unsignalized_min_distance_m'],
            collisions=s['unsignalized_collisions'],
            yield_violations=s['unsignalized_yield_violations'],
        ),
    )


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def summary(records):
    """Aggregate over valid Episode records: exposure, outcome and failures of each situation."""
    rows = [r for r in records if r.get('situations')]
    result = {}
    for name, spec in SITUATIONS.items():
        exposed = [r for r in rows if name in r['situations']['visited']]
        failed = [r for r in rows if r['situations']['failure_situation'] == name]
        reasons = {}
        for r in failed:
            reasons[r['primary_end_reason']] = reasons.get(r['primary_end_reason'], 0) + 1
        item = dict(
            title=spec['title'],
            n_exposed=len(exposed),
            n_failed_here=len(failed),
            failure_rate=len(failed) / len(exposed) if exposed else None,
            failure_reasons=reasons,
        )
        parts = [r['situations'][name] for r in exposed]
        if name == 'signal_chain':
            crossings = sum(p['crossings'] for p in parts)
            item.update(
                crossings=crossings,
                red_entries=sum(p['red_entries'] for p in parts),
                yellow_entry_fraction=sum(p['yellow_entries'] for p in parts) / crossings if crossings else None,
                wait_s_mean=_mean(p['wait_s'] for p in parts),
                box_stop_s_mean=_mean(p['box_stop_s'] for p in parts),
            )
        elif name == 'lane_drop':
            needed = [p for p in parts if p['required']]
            item.update(
                n_required=len(needed),
                done_rate=sum(bool(p['done']) for p in needed) / len(needed) if needed else None,
                position_m_mean=_mean(p['position_m'] for p in needed),
                requests_mean=_mean(p['requests'] for p in needed),
                rejected_mean=_mean(p['rejected'] for p in needed),
                wait_s_mean=_mean(p['wait_s'] for p in needed),
                target_lane_hv_mean=_mean(p['target_lane_hv_mean'] for p in needed),
            )
        else:
            passes = sum(p['passes'] for p in parts)
            distances = [p['min_distance_m'] for p in parts if p['min_distance_m'] is not None]
            item.update(
                passes=passes,
                cross_traffic_fraction=sum(p['passes_with_cross_traffic'] for p in parts) / passes if passes else None,
                min_distance_m=min(distances, default=None),
                collisions=sum(p['collisions'] for p in parts),
                yield_violations=sum(p['yield_violations'] for p in parts),
            )
        result[name] = item
    result['other'] = dict(
        title='그 외 구간', n_failed_here=sum(r['situations']['failure_situation'] == 'other' for r in rows)
    )
    return result
