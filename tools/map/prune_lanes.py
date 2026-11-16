"""Apply the reviewed lane/turn exclusions through SUMO PlainXML, not net.xml edits."""
import json
import subprocess
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from env.common import sha256, write_json, write_xml


def turn(element):
    return (element.get('from'), element.get('to'),
            int(element.get('fromLane')), int(element.get('toLane')))


def prune_network(network, policy_path):
    policy = json.loads(policy_path.read_text())
    if sha256(policy_path.parent / 'source/kcity.xodr') != policy['source_xodr_sha256']:
        raise ValueError('Lane pruning policy source mismatch')
    folder = network.parent / 'audit' / ('pruning_' + network.stem)
    folder.mkdir(parents=True, exist_ok=True)
    prefix = folder / 'plain'
    commands = []

    def run(command):
        commands.append(command)
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        (folder / f'command_{len(commands)}.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    original = ET.parse(network).getroot()
    original_lanes = {l.get('id'): l for e in original.findall('edge') for l in e.findall('lane')}
    for lane_id, orig_id in policy['regular_lanes'].items():
        lane = original_lanes[lane_id]
        if lane.find("param[@key='origId']").get('value') != orig_id:
            raise ValueError(f'Pruning identity mismatch: {lane_id}')
    run(['netconvert', '-s', str(network), '--plain-output-prefix', str(prefix),
         '--plain-output.lanes', 'true'])
    # Overlay deletions retain SUMO's imported geometry and remap dependent links.
    edges = ET.Element('edges')
    mapping = {}
    for edge in original.findall('edge'):
        if edge.get('function') == 'internal':
            continue
        lanes = edge.findall('lane')
        for lane in reversed(lanes):
            if lane.get('id') in policy['regular_lanes']:
                ET.SubElement(edges, 'delete', id=edge.get('id'), index=lane.get('index'))
        kept = [l for l in lanes if l.get('id') not in policy['regular_lanes']]
        if not kept:
            raise ValueError('Pruning would remove an entire edge')
        mapping.update({l.get('id'): edge.get('id') + '_' + str(i) for i, l in enumerate(kept)})
    write_xml(folder / 'delete.edg.xml', edges)
    excluded = {(c['from_edge'], c['to_edge'], c['from_lane'], c['to_lane'])
                for c in policy['connections']}
    connections = ET.Element('connections')
    expected, found = set(), set()
    for connection in original.findall('connection'):
        if connection.get('from').startswith(':'):
            continue
        key = turn(connection)
        a = connection.get('from') + '_' + connection.get('fromLane')
        b = connection.get('to') + '_' + connection.get('toLane')
        if key in excluded:
            found.add(key)
            # Connections incident to deleted lanes are removed automatically.
            if a in mapping and b in mapping:
                ET.SubElement(connections, 'delete', {
                    'from': key[0], 'to': key[1],
                    'fromLane': mapping[a].rsplit('_', 1)[1],
                    'toLane': mapping[b].rsplit('_', 1)[1]})
            continue
        expected.add((key[0], key[1], int(mapping[a].rsplit('_', 1)[1]),
                      int(mapping[b].rsplit('_', 1)[1])))
    if found != excluded:
        raise ValueError(f'Excluded turns missing: {excluded - found}')
    write_xml(folder / 'delete.con.xml', connections)
    output = folder / 'pruned.net.xml'
    run(['netconvert', '-s', str(network), '-e', str(folder / 'delete.edg.xml'),
         '-x', str(folder / 'delete.con.xml'), '-o', str(output),
         '--tls.rebuild', 'true', '--tls.green.time', '20',
         '--tls.yellow.time', '3', '--tls.allred.time', '2'])
    result = ET.parse(output).getroot()
    actual = {turn(c) for c in result.findall('connection') if not c.get('from').startswith(':')}
    if actual != expected:
        raise ValueError(f'Unexpected turns after rebuild: added={actual-expected}, missing={expected-actual}')
    new_lanes = {l.get('id'): l for e in result.findall('edge')
                 if e.get('function') != 'internal' for l in e.findall('lane')}
    if set(new_lanes) != set(mapping.values()):
        raise ValueError('Unexpected regular lanes after rebuild')
    geometry_changes = []
    for old, new in mapping.items():
        if original_lanes[old].find("param[@key='origId']").get('value') != new_lanes[new].find("param[@key='origId']").get('value'):
            raise ValueError(f'Retained lane identity changed: {old}')
        if original_lanes[old].get('shape') != new_lanes[new].get('shape'):
            geometry_changes.append(dict(old=old, new=new,
                                         old_shape=original_lanes[old].get('shape'),
                                         new_shape=new_lanes[new].get('shape')))
    output.replace(network)
    def represented_roads(root):
        return {orig.rsplit('_', 1)[0] for param in root.findall('edge/lane/param')
                if param.get('key') == 'origId' for orig in param.get('value').split()}
    report = dict(removed_regular_lanes=policy['regular_lanes'],
                  removed_baseline_internal_lanes=policy['internal_lanes'],
                  removed_connections=len(excluded), lane_id_mapping=mapping,
                  regular_lanes=len(new_lanes),
                  internal_lanes=sum(len(e.findall('lane')) for e in result.findall('edge')
                                     if e.get('function') == 'internal'),
                  retained_identity_verified=True, rebuilt_lane_shapes=geometry_changes, network_sha256=sha256(network), commands=commands)
    report['source_road_ids_removed_by_pruning'] = sorted(represented_roads(original) - represented_roads(result))
    write_json(folder / 'report.json', report)
    return report
