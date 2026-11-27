"""Paired finite-demand tests of old and new signals, plus independent OD routes."""
import argparse
import concurrent.futures
import copy
import json
from pathlib import Path
import random
import subprocess
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from kcity.env.common import MAP, sha256, sumo_tools, write_json, write_xml

sumolib = sumo_tools()


def structural():
    root = ET.parse(MAP / 'kcity.net.xml').getroot()
    programs = ET.parse(MAP / 'kcity.signals.add.xml').getroot()
    errors = []
    for logic in programs.findall('tlLogic'):
        nid = logic.get('id')
        junction = root.find(f"junction[@id='{nid}']")
        requests = {int(r.get('index')): r.get('foes')[::-1] for r in junction.findall('request')}
        connections = [c for c in root.findall('connection') if c.get('tl') == nid]
        indices = {int(c.get('linkIndex')) for c in connections}
        covered = set()
        phases = logic.findall('phase')
        for number, phase in enumerate(phases):
            state = phase.get('state')
            if len(state) != max(indices) + 1:
                errors.append(f'{nid}: wrong state length')
            active = {i for i, s in enumerate(state) if s == 'G'}
            if active:
                yellow, red = phases[(number+1) % len(phases)], phases[(number+2) % len(phases)]
                if 'y' not in yellow.get('state') or set(red.get('state')) != {'r'}:
                    errors.append(f'{nid}: missing mandatory clearance transition')
                if float(yellow.get('duration')) < 3 or float(red.get('duration')) < 2:
                    errors.append(f'{nid}: insufficient configured clearance minimum')
                if phase.get('next') or yellow.get('next'):
                    errors.append(f'{nid}: clearance may be bypassed')
                for nxt in red.get('next', '').split():
                    if 'G' not in phases[int(nxt)].get('state'):
                        errors.append(f'{nid}: invalid demand selection target')
            covered |= active
            for i in active:
                for j in active:
                    if i < j and requests[i][j] == '1':
                        errors.append(f'{nid}: conflicting priority greens {i}/{j}')
            by_lane = {}
            for c in connections:
                key = (c.get('from'), c.get('fromLane'))
                by_lane.setdefault(key, set()).add(state[int(c.get('linkIndex'))])
            if any(len(colors) > 1 for colors in by_lane.values()):
                errors.append(f'{nid}: shared lane movements have inconsistent signals')
        if covered != indices:
            errors.append(f'{nid}: unserved connection')
    if errors:
        raise ValueError(errors)
    return dict(signal_count=len(programs.findall('tlLogic')), errors=errors,
                checked=['no conflicting priority greens', 'all connections served',
                         'consistent indication for shared turn/straight lanes',
                         'mandatory yellow and all-red before every change of approach'])


def routes(folder, demand, seed):
    root = ET.parse(MAP / 'kcity.rou.xml').getroot()
    if demand == 'random_od':
        rng = random.Random(20261101 + seed)
        net = sumolib.net.readNet(str(MAP / 'kcity.net.xml'))
        endpoints = [e for e in net.getEdges() if e.getLength() >= 40]
        new = ET.Element('routes')
        for t in root.findall('vType'):
            new.append(copy.deepcopy(t))
        for i in range(177):
            for _ in range(10000):
                start, end = rng.sample(endpoints, 2)
                path, distance = net.getShortestPath(start, end, vClass='passenger')
                if path and 300 <= distance <= 1500:
                    break
            else:
                raise ValueError('Cannot generate valid OD route')
            name = f'od_{i:03d}'
            ET.SubElement(new, 'route', id=name, edges=' '.join(e.getID() for e in path))
            ET.SubElement(new, 'vehicle', id=name, route=name,
                          type='hv_' + ['Krauss', 'IDM', 'EIDM', 'ACC'][i % 4],
                          depart=str(i * 6), departLane='best', departSpeed='0')
        root = new
    else:
        scale = float(demand)
        for vehicle in root.findall('vehicle'):
            vehicle.set('depart', str(float(vehicle.get('depart')) / scale))
    path = folder / 'traffic.rou.xml'
    write_xml(path, root)
    return path


def run(job):
    base, profile, demand, seed = job
    folder = base / f'{profile}_{demand}_seed{seed}'
    folder.mkdir(parents=True, exist_ok=True)
    route = routes(folder, demand, seed)
    network = MAP / ('audit/before_signal_design/kcity.net.xml' if profile == 'before' else 'kcity.net.xml')
    additional = [MAP / 'kcity.add.xml']
    if profile == 'after':
        additional.append(MAP / 'kcity.signals.add.xml')
    cmd = ['sumo', '-n', str(network), '-r', str(route), '-a', ','.join(map(str, additional)),
           '--seed', str(seed), '--step-length', '0.1', '--end', '3600',
           '--time-to-teleport', '-1', '--collision.action', 'warn',
           '--collision.check-junctions', 'true', '--no-step-log', 'true',
           '--duration-log.disable', 'true', '--statistic-output', str(folder / 'statistics.xml'),
           '--tripinfo-output', str(folder / 'trips.xml'), '--tripinfo-output.write-unfinished', 'true',
           '--tripinfo-output.write-undeparted', 'true', '--collision-output', str(folder / 'collisions.xml'),
           '--queue-output', str(folder / 'queues.xml'), '--queue-output.period', '5']
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    (folder / 'stdout.log').write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    stats = ET.parse(folder / 'statistics.xml').getroot()
    trips = ET.parse(folder / 'trips.xml').findall('tripinfo')
    finished = [t for t in trips if float(t.get('arrival')) >= 0]
    collisions = ET.parse(folder / 'collisions.xml').findall('collision')
    queues = ET.parse(folder / 'queues.xml').findall('.//lane')
    max_queue = max((float(q.get('queueing_length', 0)) for q in queues), default=0)
    result = dict(profile=profile, demand=demand, seed=seed, expected=177, arrived=len(finished),
                  unfinished=[t.get('id') for t in trips if float(t.get('arrival')) < 0],
                  collisions=[c.attrib for c in collisions],
                  teleports=stats.find('teleports').attrib,
                  mean_duration_s=sum(float(t.get('duration')) for t in finished)/max(1, len(finished)),
                  mean_wait_s=sum(float(t.get('waitingTime')) for t in finished)/max(1, len(finished)),
                  mean_time_loss_s=sum(float(t.get('timeLoss')) for t in finished)/max(1, len(finished)),
                  mean_depart_delay_s=sum(float(t.get('departDelay')) for t in finished)/max(1, len(finished)),
                  maximum_trip_wait_s=max((float(t.get('waitingTime')) for t in finished), default=0),
                  max_sampled_queue_m=max_queue,
                  emergency_braking_warnings=proc.stderr.count('performs emergency braking'),
                  network_sha256=sha256(network), routes_sha256=sha256(route),
                  signals_sha256=sha256(MAP / 'kcity.signals.add.xml') if profile == 'after' else None)
    result['passed'] = len(finished) == 177 and not collisions and not any(int(x) for x in result['teleports'].values())
    write_json(folder / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='signals_validation')
    parser.add_argument('--profiles', nargs='+', default=['before', 'after'])
    parser.add_argument('--demands', nargs='+', default=['1', '2', '3', 'random_od'])
    parser.add_argument('--seeds', nargs='+', type=int, default=[0, 1, 2])
    args = parser.parse_args()
    checks = structural()
    base = MAP / 'reports' / args.output
    jobs = [(base, p, d, s) for p in args.profiles for d in args.demands for s in args.seeds]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(run, jobs))
    write_json(base / 'summary.json', dict(structural=checks, runs=results,
                                          passed=all(r['passed'] for r in results if r['profile']=='after')))
    for r in results:
        print({k:r[k] for k in ['profile','demand','seed','arrived','passed','mean_wait_s','max_sampled_queue_m']})
    if any(not r['passed'] for r in results if r['profile'] == 'after'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
