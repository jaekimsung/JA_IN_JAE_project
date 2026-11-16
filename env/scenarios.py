"""Validate KC-01 geometry/seed contracts; optional bounded scripted route smoke.

No map generation, Gym environment, expert dataset, BC or PPO training.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from env.config import (ContractError, DEFAULT_PROTOCOL, canonical_bytes, digest,
    file_sha256, load_contract, make_case, positive, repository_path,
    traffic_requests, validate_settings)


def sumo_library():
    # Existing map helper is imported read-only, without starting SUMO.
    from env.common import sumo_tools
    return sumo_tools()


def internal_chain(net, connection):
    """Preserve each via Lane, including multiple internal pieces, until exit."""
    target = connection.getToLane().getID()
    first = connection.getViaLaneID()
    if not first:
        return []
    def walk(lane_id, seen):
        if lane_id == target:
            return []
        if lane_id in seen:
            raise ContractError('Cycle in internal Lane connection: ' + lane_id)
        lane = net.getLane(lane_id)
        if lane.getEdge().getFunction() != 'internal':
            raise ContractError('Unexpected non-internal via Lane: ' + lane_id)
        for nxt in lane.getOutgoing():
            if nxt.getToLane().getID() == target:
                follow = nxt.getViaLaneID() or target
                return [lane_id] + walk(follow, seen | {lane_id})
        raise ContractError('No internal continuation to target: ' + lane_id)
    return walk(first, set())


def validate_contract(spec):
    validate_settings(spec)
    sumolib = sumo_library()
    net = sumolib.net.readNet(str(repository_path(spec['protocol']['assets']['network']['path'])),
                              withInternal=True)
    signal_root = ET.parse(repository_path(spec['protocol']['assets']['signals']['path'])).getroot()
    programs = {p.get('id'): p for p in signal_root.findall('tlLogic')}
    routes_root = ET.parse(repository_path(spec['protocol']['assets']['routes']['path'])).getroot()
    background = {}
    for r in routes_root.findall('route'):
        if r.get('id').startswith(spec['protocol']['traffic']['route_prefix']):
            background[r.get('id')] = r.get('edges').split()
    types = {v.get('id') for v in routes_root.findall('vType')}
    if not set(spec['protocol']['traffic']['vehicle_types']) <= types:
        raise ContractError('Declared background vType missing')

    def edges_for(ids):
        if not ids:
            raise ContractError('Route cannot be empty')
        for eid in ids:
            if not net.hasEdge(eid) or net.getEdge(eid).getFunction() == 'internal':
                raise ContractError('Missing or internal route Edge: ' + eid)
        return [net.getEdge(eid) for eid in ids]

    def connections_for(a, b):
        cs = [c for c in a.getOutgoing().get(b, []) if c.allows('passenger')]
        if not cs:
            raise ContractError('No passenger connection: ' + a.getID() + ' -> ' + b.getID())
        return cs

    for name, ids in background.items():
        edges = edges_for(ids)
        for a, b in zip(edges, edges[1:]):
            connections_for(a, b)
    if not background:
        raise ContractError('No valid background routes')
    report = {}
    for row in spec['scenario_manifest']['scenarios']:
        sid = row['id']
        if row['vehicle_class'] != 'passenger':
            raise ContractError('Research scenarios must use passenger permissions')
        edges = edges_for(row['route_edges'])
        lengths, short, links, tls = {}, [], [], set()
        positive(row['episode_limit_s'], 'episode_limit_s')
        for label, edge, pos_key in [('start', edges[0], 'position_m'),
                                      ('goal', edges[-1], 'arrival_position_m')]:
            end = row[label]
            if end['edge'] != edge.getID():
                raise ContractError(sid + ': start/goal Edge does not match route')
            li = end['lane_index']
            if isinstance(li, bool) or not isinstance(li, int) or not 0 <= li < edge.getLaneNumber():
                raise ContractError(sid + ': invalid ' + label + ' Lane')
            lane = edge.getLane(li)
            pos = end[pos_key]
            if isinstance(pos, bool) or not isinstance(pos, (int, float)) or not math.isfinite(pos):
                raise ContractError(sid + ': invalid ' + label + ' position')
            if not lane.allows('passenger') or not 0 <= pos < lane.getLength():
                raise ContractError(sid + ': ' + label + ' outside permitted Lane length')
            lengths[label] = dict(lane_id=lane.getID(), lane_length_m=lane.getLength(), position_m=pos)
        speed = row['start']['speed_mps']
        positive(speed, 'depart speed')
        if speed > min(edges[0].getLane(row['start']['lane_index']).getSpeed(),
                       spec['protocol']['control']['speed_cap_mps']):
            raise ContractError(sid + ': depart speed exceeds declared limit')
        for edge in edges:
            if edge.getLength() < 1:
                short.append(dict(id=edge.getID(), length_m=edge.getLength()))
        for index, (a, b) in enumerate(zip(edges, edges[1:])):
            options = []
            for c in connections_for(a, b):
                via = internal_chain(net, c)
                if c.getTLSID():
                    tid, idx = c.getTLSID(), c.getTLLinkIndex()
                    if tid not in programs or not all(0 <= idx < len(p.get('state'))
                        for p in programs[tid].findall('phase')):
                        raise ContractError(sid + ': missing TLS program/link index')
                    tls.add(tid)
                options.append(dict(from_lane=c.getFromLane().getID(),
                    to_lane=c.getToLane().getID(), via_lanes=via,
                    via_length_m=sum(net.getLane(v).getLength() for v in via),
                    tls_id=c.getTLSID() or None, link_index=c.getTLLinkIndex()))
            links.append(dict(route_occurrence=index, from_edge=a.getID(),
                              to_edge=b.getID(), options=options))
        if tls != set(row['required_tls_ids']):
            raise ContractError(sid + ': required TLS set does not match route')
        required = row['required_lane_change']
        if sid in ['B', 'C'] and not required:
            raise ContractError(sid + ': required Lane-change task cannot be omitted')
        if required:
            if (required['edge'], required['next_edge']) != tuple(row['route_edges'][:2]):
                raise ContractError(sid + ': required Lane constraint not on start connection')
            cs = connections_for(edges[0], edges[1])
            permitted = {c.getFromLane().getIndex() for c in cs}
            departure = row['start']['lane_index']
            if required['depart_lane'] != departure or departure in permitted:
                raise ContractError(sid + ': declared start Lane does not require a change')
            if sorted(permitted) != required['required_exit_lanes']:
                raise ContractError(sid + ': required exit Lanes mismatch')
            if not any(abs(departure - li) == 1 for li in permitted):
                raise ContractError(sid + ': required change is not one adjacent Lane')
        report[sid] = dict(start=lengths['start'], goal=lengths['goal'],
            normal_edge_length_sum_m=sum(e.getLength() for e in edges),
            short_normal_edges=short, connections=links, TLS_ids=sorted(tls),
            required_lane_change_geometry_valid=bool(required),
            runtime_feasibility='not tested by static validation')
    # Fixed-seed equality and stream independence are data-contract checks only.
    case = make_case(spec, 'contract_check', 'C', 0)
    repeated = traffic_requests(spec, case, background)
    duplicate = traffic_requests(spec, make_case(spec, 'contract_check', 'C', 0), background)
    other = traffic_requests(spec, make_case(spec, 'contract_check', 'C', 1), background)
    if canonical_bytes(repeated) != canonical_bytes(duplicate) or repeated == other:
        raise ContractError('Request reproducibility/different-seed check failed')
    return dict(scenarios=report, background_routes_checked=len(background),
        seed_checks=dict(same_case_request_sha256=digest(repeated),
            changed_case_request_sha256=digest(other), same_case_equal=True,
            different_case_differs=True, generated_requests=len(repeated)),
        errors=[], contract_sha256=digest(spec)), background


def route_smoke(spec, row, folder):
    """Empty-road IDM longitudinal smoke + one explicit required Lane request.

    It is not a research expert, learned AV, traffic-demand or Gym test.
    """
    folder.mkdir()
    sumolib = sumo_library()
    import traci
    routes = ET.Element('routes')
    ctl = spec['protocol']['control']
    ET.SubElement(routes, 'vType', id='smoke_IDM', vClass='passenger',
        carFollowModel='IDM', length='4.5', width='1.8', accel=str(ctl['max_accel_mps2']),
        decel=str(ctl['max_decel_mps2']), emergencyDecel='8', tau='1.5',
        maxSpeed=str(ctl['speed_cap_mps']), speedFactor='1', speedDev='0')
    ET.SubElement(routes, 'route', id='task', edges=' '.join(row['route_edges']))
    ET.SubElement(routes, 'vehicle', id='kc01_probe', type='smoke_IDM', route='task',
        depart='0', departLane=str(row['start']['lane_index']),
        departPos=str(row['start']['position_m']), departSpeed=str(row['start']['speed_mps']),
        arrivalLane=str(row['goal']['lane_index']), arrivalPos=str(row['goal']['arrival_position_m']))
    ET.indent(routes)
    ET.ElementTree(routes).write(folder/'routes.rou.xml', encoding='utf-8', xml_declaration=True)
    assets = spec['protocol']['assets']
    seed = make_case(spec, 'contract_check', row['id'], 0)['seeds']['sumo']
    cmd = [sumolib.checkBinary('sumo'), '-n', str(repository_path(assets['network']['path'])),
        '-r', str(folder/'routes.rou.xml'), '-a', str(repository_path(assets['signals']['path'])),
        '--seed', str(seed), '--step-length', str(spec['protocol']['timing']['sumo_step_s']),
        '--end', str(row['episode_limit_s']), '--no-step-log', 'true',
        '--time-to-teleport', '-1', '--collision.action', 'warn',
        '--collision.check-junctions', 'true', '--error-log', str(folder/'warnings.log'),
        '--tripinfo-output', str(folder/'tripinfo.xml')]
    label = 'kc01_' + uuid.uuid4().hex
    start = time.monotonic()
    seen, collisions, teleports, modes = set(), set(), set(), {}
    arrived, departed, changed, request_sent = False, False, False, False
    last_position, last_edge, active_programs = None, None, {}
    initial_snapshot = None
    with (folder/'stdout.log').open('w') as stdout, (folder/'trace.jsonl').open('w') as trace:
        traci.start(cmd, label=label, stdout=stdout)
        conn = traci.getConnection(label)
        try:
            active_programs = {t:conn.trafficlight.getProgram(t) for t in conn.trafficlight.getIDList()}
            while conn.simulation.getTime() < row['episode_limit_s']:
                conn.simulationStep()
                departed |= 'kc01_probe' in conn.simulation.getDepartedIDList()
                arrived |= 'kc01_probe' in conn.simulation.getArrivedIDList()
                collisions.update(conn.simulation.getCollidingVehiclesIDList())
                teleports.update(conn.simulation.getStartingTeleportIDList())
                if 'kc01_probe' in conn.vehicle.getIDList():
                    if not modes:
                        initial_snapshot = dict(edge=conn.vehicle.getRoadID('kc01_probe'),
                            lane_index=conn.vehicle.getLaneIndex('kc01_probe'),
                            position_m=conn.vehicle.getLanePosition('kc01_probe'),
                            speed_mps=conn.vehicle.getSpeed('kc01_probe'))
                        conn.vehicle.setSpeedMode('kc01_probe', ctl['speed_mode'])
                        conn.vehicle.setLaneChangeMode('kc01_probe', ctl['lane_change_mode'])
                        modes = dict(speedMode=conn.vehicle.getSpeedMode('kc01_probe'),
                                     laneChangeMode=conn.vehicle.getLaneChangeMode('kc01_probe'))
                    edge = conn.vehicle.getRoadID('kc01_probe')
                    lane = conn.vehicle.getLaneIndex('kc01_probe')
                    pos = conn.vehicle.getLanePosition('kc01_probe')
                    seen.add(edge)
                    required = row['required_lane_change']
                    if required and edge == required['edge']:
                        if not request_sent and pos >= 10:
                            conn.vehicle.changeLane('kc01_probe', required['required_exit_lanes'][0],
                                                    ctl['lane_command_duration_s'])
                            request_sent = True
                        changed |= lane in required['required_exit_lanes']
                    last_position, last_edge = pos, edge
                    trace.write(json.dumps(dict(time_s=conn.simulation.getTime(), edge=edge,
                        lane_id=conn.vehicle.getLaneID('kc01_probe'), lane_index=lane,
                        lane_pos_m=pos, speed_mps=conn.vehicle.getSpeed('kc01_probe'),
                        next_TLS=conn.vehicle.getNextTLS('kc01_probe')))+'\n')
                if arrived or collisions or teleports or (departed and not conn.vehicle.getIDList()):
                    break
            sim_end = conn.simulation.getTime()
        finally:
            conn.close()
    trips = ET.parse(folder/'tripinfo.xml').findall('tripinfo')
    trip = next((t for t in trips if t.get('id') == 'kc01_probe'), None)
    goal_ok = bool(trip is not None and float(trip.get('arrival', '-1')) >= 0 and
                   trip.get('arrivalLane') == row['goal']['edge'] + '_' + str(row['goal']['lane_index']) and
                   math.isclose(float(trip.get('arrivalPos')), row['goal']['arrival_position_m'], abs_tol=.011))
    start_ok = bool(initial_snapshot and initial_snapshot['edge'] == row['start']['edge'] and
        initial_snapshot['lane_index'] == row['start']['lane_index'] and
        math.isclose(initial_snapshot['position_m'], row['start']['position_m'], abs_tol=.011) and
        math.isclose(initial_snapshot['speed_mps'], row['start']['speed_mps'], abs_tol=.011))
    modes_ok = modes == dict(speedMode=ctl['speed_mode'], laneChangeMode=ctl['lane_change_mode'])
    passed = arrived and goal_ok and start_ok and modes_ok and not collisions and not teleports and (
        row['required_lane_change'] is None or request_sent and changed)
    return dict(scenario_id=row['id'], passed=passed, arrived=arrived,
        goal_position_and_lane_match=goal_ok, start_matches_contract=start_ok,
        initial_snapshot=initial_snapshot, modes_match_contract=modes_ok, departed=departed,
        required_lane_request_sent=request_sent, required_lane_observed=changed,
        modes=modes, last_observed_edge=last_edge, last_observed_position_m=last_position,
        sampled_edges=sorted(seen), collision_vehicle_ids=sorted(collisions),
        teleport_vehicle_ids=sorted(teleports), active_signal_programs=active_programs,
        sim_end_s=sim_end, wall_seconds=time.monotonic()-start, command=cmd,
        limitations=['no background traffic', 'IDM longitudinal + scripted required Lane change',
            'not research B0/learned AV/Gym evaluation',
            '0.1s sampled trace can miss very short Edge occupancy; static topology retains them'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--protocol', type=Path, default=DEFAULT_PROTOCOL)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--smoke', action='store_true')
    args = ap.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    begun = datetime.now().astimezone().isoformat()
    spec = load_contract(args.protocol)
    report, routes = validate_contract(spec)
    version = subprocess.check_output(['sumo', '--version'], text=True).splitlines()[0]
    if version != 'Eclipse SUMO sumo ' + spec['protocol']['expected_sumo_version']:
        raise ContractError('Installed SUMO version differs from pinned KC-01 contract')
    case = make_case(spec, 'contract_check', 'C', 0)
    (output/'CASE_C.json').write_text(json.dumps(case, ensure_ascii=False, indent=2)+'\n')
    (output/'TRAFFIC_REQUESTS_C.json').write_text(json.dumps(
        traffic_requests(spec, case, routes), ensure_ascii=False, indent=2)+'\n')
    smoke = []
    if args.smoke:
        for row in spec['scenario_manifest']['scenarios']:
            result = route_smoke(spec, row, output/row['id'])
            (output/(row['id']+'.result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
            smoke.append(result)
    report.update(started_at=begun, ended_at=datetime.now().astimezone().isoformat(),
        sumo_version=version, scripted_smoke=smoke,
        passed=all(r['passed'] for r in smoke), training_ready=False,
        learning_updates=0, expert_transitions_collected=0,
        protocol_sha256=file_sha256(args.protocol),
        source_SHA256={str(p.relative_to(ROOT)):file_sha256(p) for p in
            [ROOT/'kcity/env/config.py', Path(__file__).resolve()]})
    (output/'SUMMARY.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'], training_ready=False,
        static_scenarios=list(report['scenarios']),
        scripted_smoke=[{k:r[k] for k in ['scenario_id','passed','arrived']} for r in smoke]), indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
