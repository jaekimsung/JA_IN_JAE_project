"""Evidence-linked, explicitly assumed K-City traffic control design."""
import collections
import copy
import json
import math
import subprocess
import xml.etree.ElementTree as ET

import pyproj
import yaml

from common import sha256, sumo_tools, write_json, write_xml

sumolib = sumo_tools()


def evidence(map_dir, net):
    source = map_dir / 'source'
    info = json.loads((source / 'mgeo_global_info.json').read_text())
    transform = pyproj.Transformer.from_crs(info['global_coordinate_system'], net.getGeoProj().srs,
                                          always_xy=True)
    nodes = json.loads((source / 'mgeo_node_set.json').read_text())
    links = json.loads((source / 'mgeo_link_set.json').read_text())
    lanes = [l for e in net.getEdges() for l in e.getLanes()]
    matches = collections.defaultdict(list)
    unmatched = []
    for node in nodes:
        if not node.get('on_stop_line') or not node.get('traffic_light_id'):
            continue
        x, y = transform.transform(node['point'][0] + info['local_origin_in_global'][0],
                                   node['point'][1] + info['local_origin_in_global'][1])
        distance, lane = min(((math.dist((x, y), l.getShape()[-1][:2]), l) for l in lanes),
                             key=lambda pair: pair[0])
        record = dict(mgeo_node=node['idx'], signal_id=node['traffic_light_id'], xy=[x, y],
                      nearest_lane=lane.getID(), endpoint_distance_m=distance,
                      junction=lane.getEdge().getToNode().getID(),
                      status='spatial candidate only; cross-edition identity not established')
        (matches[record['junction']] if distance <= 20 else unmatched).append(record)
    cfg = yaml.safe_load((source / 'qualifier.yaml').read_text())
    carla = []
    for name, record in cfg['scenario']['qualifier']['traffic_lights'].items():
        point = record['location']
        xy = [point['x'], -point['y']]
        distance, node = min(((math.dist(xy, n.getCoord()), n) for n in net.getNodes()
                              if len(n.getIncoming()) >= 3), key=lambda pair: pair[0])
        carla.append(dict(id=name, xy=xy, junction=node.getID(), distance_m=distance,
                          evidence='scenario actor location; not field signal timing'))
    candidates = []
    for node in net.getNodes():
        if len(node.getIncoming()) < 3:
            continue
        candidates.append(dict(junction=node.getID(), xy=node.getCoord(),
                               approaches=[e.getID() for e in node.getIncoming()],
                               minimum_approach_length_m=min(e.getLength() for e in node.getIncoming()),
                               mgeo_matches=matches[node.getID()]))
    return dict(candidates=candidates, unmatched_mgeo_signal_nodes=unmatched,
                carla_scenario_positions=carla,
                mgeo_stop_nodes=sum(bool(n.get('on_stop_line')) for n in nodes),
                mgeo_signal_nodes=sum(bool(n.get('traffic_light_id')) for n in nodes),
                related_signal_counts=dict(collections.Counter(str(l.get('related_signal')) for l in links)),
                limitations=['20 m endpoint proximity is not a surveyed alignment',
                             'MGEO traffic_light_set and intersection_controller files are absent locally',
                             'CARLA server was not running; actor group/timing could not be read',
                             'MORAI tlList state snapshots do not provide a complete phase schedule',
                             'source OpenDRIVE has no signal or controller definitions'])


def apply_signals(map_dir):
    policy = json.loads((map_dir / 'signal_policy.json').read_text())
    network = map_dir / 'kcity.net.xml'
    original = ET.parse(network).getroot()
    net = sumolib.net.readNet(str(network))
    audit = evidence(map_dir, net)
    selected = set(policy['junctions'])
    nodes = ET.Element('nodes')
    for nid in sorted(selected):
        node = net.getNode(nid)
        if len(node.getIncoming()) < 3:
            raise ValueError(f'Signal requires a real junction: {nid}')
        ET.SubElement(nodes, 'node', id=nid, type='traffic_light', tlType='actuated')
    folder = map_dir / 'audit/signal_design'
    folder.mkdir(parents=True, exist_ok=True)
    patch = folder / 'signals.nod.xml'
    write_xml(patch, nodes)
    output = folder / 'signalized.net.xml'
    command = ['netconvert', '-s', str(network), '-n', str(patch), '-o', str(output),
               '--tls.rebuild', 'true', '--tls.default-type', 'actuated',
               '--tls.layout', 'incoming', '--tls.green.time', '15',
               '--tls.min-dur', str(policy['min_green_s']),
               '--tls.max-dur', str(policy['max_green_s']),
               '--tls.yellow.time', str(policy['yellow_s']), '--tls.allred.time', '2']
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (folder / 'netconvert.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    root = ET.parse(output).getroot()
    def topology(r):
        return {(c.get('from'), c.get('to'), c.get('fromLane'), c.get('toLane'))
                for c in r.findall('connection') if not c.get('from').startswith(':')}
    if topology(root) != topology(original):
        raise ValueError('Signal design changed road connectivity')
    def regular(r):
        return {l.get('id'): l.attrib for e in r.findall('edge')
                if e.get('function') != 'internal' for l in e.findall('lane')}
    before, after = regular(original), regular(root)
    if before != after:
        raise ValueError('Signal design changed regular lane geometry or attributes')
    lanes = {l.get('id'): l for e in root.findall('edge') for l in e.findall('lane')}
    internal_next = {c.get('from') + '_' + c.get('fromLane'): c.get('via')
                     for c in root.findall('connection') if c.get('from').startswith(':')}
    programs = ET.Element('additional')
    report = []
    for tls in root.findall('tlLogic'):
        nid = tls.get('id')
        if nid not in selected:
            raise ValueError(f'Unexpected signal {nid}')
        logic = copy.deepcopy(tls)
        logic.set('programID', 'assumed_actuated_v1')
        logic.set('type', 'actuated')
        controlled = [c for c in root.findall('connection') if c.get('tl') == nid]
        lengths, clearance_times = {}, {}
        for c in controlled:
            via, length, travel_time = c.get('via'), 0, 0
            slowest = policy['clearance_speed_mps']
            while via:
                segment = float(lanes[via].get('length'))
                speed = min(policy['clearance_speed_mps'], float(lanes[via].get('speed')))
                length += segment
                travel_time += segment / speed
                slowest = min(slowest, speed)
                via = internal_next.get(via)
            lengths[int(c.get('linkIndex'))] = length
            clearance_times[int(c.get('linkIndex'))] = travel_time + policy['vehicle_length_m'] / slowest
        phases = logic.findall('phase')
        groups = []
        for i, phase in enumerate(phases):
            state = phase.get('state')
            if 'G' not in state and 'g' not in state:
                continue
            active = [j for j, color in enumerate(state) if color in 'Gg']
            distance = max(lengths[j] for j in active)
            clearance = max(2, math.ceil(max(clearance_times[j] for j in active)))
            phase.set('minDur', str(policy['min_green_s']))
            phase.set('maxDur', str(policy['max_green_s']))
            phase.set('name', 'approach_' + '_'.join(sorted({c.get('from') for c in controlled
                                                           if int(c.get('linkIndex')) in active})))
            yellow = phases[(i + 1) % len(phases)]
            red = phases[(i + 2) % len(phases)]
            if 'y' not in yellow.get('state') or set(red.get('state')) != {'r'}:
                raise ValueError('Expected green/yellow/all-red sequence')
            yellow.set('duration', str(policy['yellow_s']))
            red.set('duration', str(clearance))
            groups.append(dict(name=phase.get('name'), indices=active,
                               longest_internal_path_m=distance, all_red_s=clearance))
        for key, value in {'max-gap': '3', 'detector-gap': '1', 'jam-threshold': '30',
                           'show-detectors': 'false', 'inactive-threshold': '60'}.items():
            ET.SubElement(logic, 'param', key=key, value=value)
        # Always clear the outgoing approach first, then select a demanded green.
        # Cyclic order breaks ties; aging gives long-waiting approaches priority.
        green_indices = [i for i, p in enumerate(phases) if 'G' in p.get('state')]
        for number, index in enumerate(green_indices):
            order = green_indices[number + 1:] + green_indices[:number + 1]
            phases[index + 2].set('next', ' '.join(map(str, order)))
        programs.append(logic)
        candidate = next(c for c in audit['candidates'] if c['junction'] == nid)
        report.append(dict(junction_id=nid, sumo_xy=net.getNode(nid).getCoord(),
                           rationale=policy['junctions'][nid], mgeo_matches=candidate['mgeo_matches'],
                           groups=groups, program=logic.attrib,
                           phase_status='assumed demand-actuated, not measured field timing'))
    output.replace(network)
    write_xml(map_dir / 'kcity.signals.add.xml', programs)
    audit.update(selected=report, policy=policy, command=command,
                 topology_and_regular_lanes_unchanged=True, network_sha256=sha256(network),
                 programs_sha256=sha256(map_dir / 'kcity.signals.add.xml'))
    write_json(map_dir / 'reports/signal_design.json', audit)
    return report
