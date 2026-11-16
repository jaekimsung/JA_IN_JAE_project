#!/usr/bin/env python3
"""Build K-City from local, hash-checked snapshots. Never modify source workspaces."""
import argparse
import collections
import csv
import json
import math
from pathlib import Path
import random
import subprocess
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from env.common import MAP, sha256, sumo_tools, write_json, write_xml
from prune_lanes import prune_network
from signals import apply_signals

sumolib = sumo_tools()
EXCLUDED_SOURCE_ROADS = {"69": "isolated source road with no predecessor/successor; removed at user request"}


def import_network(source, output, audit, tls=(), node_patch=None):
    cmd = [sumolib.checkBinary("netconvert"), "--opendrive-files", str(source),
           "--output-file", str(output), "--opendrive.curve-resolution", "0.5",
           "--opendrive.internal-shapes", "false", "--opendrive.lane-shapes", "true",
           "--output.original-names", "true", "--offset.disable-normalization", "true",
           "--remove-edges.explicit", ",".join(EXCLUDED_SOURCE_ROADS),
           "--error-log", str(audit)]
    if tls:
        cmd += ["--tls.set", ",".join(tls), "--tls.default-type", "static",
                "--tls.green.time", "20", "--tls.yellow.time", "3", "--tls.allred.time", "2"]
    if node_patch:
        cmd += ["--node-files", str(node_patch)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    audit.with_suffix(".stdout.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return cmd


def qualifier_route(net, csv_path):
    """Match by original road/lane identity, then fill only short intervening sections."""
    lanes = collections.defaultdict(list)
    for edge in net.getEdges(withInternal=True):
        for lane in edge.getLanes():
            for orig in lane.getParam("origId", "").split():
                lanes[orig].append(lane)
    matched = []
    edge_sequence = []
    regular_matches = []
    with csv_path.open() as stream:
        for row in csv.DictReader(stream):
            key = row["road_id"] + "_" + row["lane_id"]
            point = (float(row["x"]), -float(row["y"]))
            options = [(sumolib.geomhelper.polygonOffsetAndDistanceToPoint(point, lane.getShape()), lane)
                       for lane in lanes[key]]
            if not options:
                raise ValueError(f"Missing original lane {key}")
            (offset, distance), lane = min(options, key=lambda item: item[0][1])
            record = dict(index=int(row["index"]), orig_id=key, lane=lane.getID(),
                          distance_m=distance, offset_m=offset,
                          internal=lane.getEdge().getFunction() == "internal")
            matched.append(record)
            if not record["internal"]:
                regular_matches.append(record)
                if not edge_sequence or edge_sequence[-1] != lane.getEdge():
                    edge_sequence.append(lane.getEdge())
    result = [edge_sequence[0]]
    bridges = []
    for target in edge_sequence[1:]:
        path, cost = net.getShortestPath(result[-1], target, vClass="passenger")
        if not path:
            raise ValueError(f"Disconnected qualifier route: {result[-1].getID()} -> {target.getID()}")
        if len(path) > 2:
            length = sum(edge.getLength() for edge in path[1:-1])
            if length > 30:
                raise ValueError(f"Unexpected qualifier detour: {length:.1f} m")
            bridges.append(dict(before=result[-1].getID(), after=target.getID(),
                                inserted=[e.getID() for e in path[1:-1]], length_m=length))
        result.extend(path[1:])
    return result, dict(matched_rows=matched, inserted_sections=bridges,
                        depart_pos=regular_matches[0]["offset_m"],
                        arrival_pos=regular_matches[-1]["offset_m"],
                        depart_lane=net.getLane(regular_matches[0]["lane"]).getIndex())


def coverage_routes(net, plan_path, seed=20261101):
    """Preserve authored traffic routes when changing the map."""
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan['source_xodr_sha256'] != sha256(plan_path.parent / 'source' / 'kcity.xodr'):
            raise ValueError('Traffic plan belongs to a different source map')
        routes, witnesses = {}, {}
        for name, record in plan['routes'].items():
            routes[name] = [net.getEdge(edge) for edge in record['edges']]
            witnesses[name] = record['target']
        expected = {e.getID() for e in net.getEdges(withInternal=False) if e.allows('passenger')}
        if set(witnesses.values()) != expected:
            raise ValueError('Traffic plan does not cover the current network')
        return routes, witnesses
    rng = random.Random(seed)
    edges = sorted((e for e in net.getEdges(withInternal=False) if e.allows("passenger")), key=lambda e: e.getID())
    endpoints = [e for e in edges if e.getLength() >= 30]
    routes = {}
    witnesses = {}
    for i, target in enumerate(edges):
        candidates = endpoints[:]
        rng.shuffle(candidates)
        prefix = suffix = None
        for endpoint in candidates:
            if prefix is None:
                path, cost = net.getShortestPath(endpoint, target, vClass="passenger")
                if path and 150 <= cost <= 1000:
                    prefix = path
            if suffix is None:
                path, cost = net.getShortestPath(target, endpoint, vClass="passenger")
                if path and 150 <= cost <= 1000:
                    suffix = path
            if prefix and suffix:
                break
        path = list(prefix or [target]) + list(suffix or [target])[1:]
        route_id = f"coverage_{i:03d}"
        routes[route_id] = path
        witnesses[route_id] = target.getID()
    return routes, witnesses


def network_inventory(net, source):
    import networkx as nx
    edges = net.getEdges(withInternal=False)
    graph = nx.DiGraph()
    graph.add_nodes_from(e.getID() for e in edges)
    for edge in edges:
        graph.add_edges_from((edge.getID(), other.getID()) for other in edge.getOutgoing())
    xodr = ET.parse(source).getroot()
    originals = set()
    for edge in net.getEdges(withInternal=True):
        for lane in edge.getLanes():
            originals.update(orig.rsplit("_", 1)[0] for orig in lane.getParam("origId", "").split())
    source_ids = {r.get("id") for r in xodr.findall("road")}
    return dict(
        source_roads=len(source_ids), source_junctions=len(xodr.findall("junction")),
        source_signals=len(xodr.findall(".//signal")),
        source_speed_values=dict(collections.Counter(f"{s.get('max')} {s.get('unit')}" for s in xodr.findall(".//speed"))),
        regular_edges=len(edges), regular_lanes=sum(e.getLaneNumber() for e in edges),
        internal_edges=len(net.getEdges(withInternal=True)) - len(edges),
        junctions=len(net.getNodes()), tls_ids=sorted(tls.getID() for tls in net.getTrafficLights()),
        represented_source_road_ids=sorted(originals),
        intentionally_excluded_source_roads=EXCLUDED_SOURCE_ROADS,
        unrepresented_source_road_ids=sorted(source_ids - originals - set(EXCLUDED_SOURCE_ROADS)),
        weak_components=[sorted(c) for c in sorted(nx.weakly_connected_components(graph), key=len, reverse=True)],
        strong_component_sizes=sorted(map(len, nx.strongly_connected_components(graph)), reverse=True),
        roundabouts=[dict(nodes=r.getNodes(), edges=r.getEdges()) for r in net.getRoundabouts()],
        road_lane_length_m=sum(l.getLength() for e in edges for l in e.getLanes()),
        bounding_box=net.getBoundary(),
    )


def main():
    import json
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-dir", type=Path, default=MAP)
    args = parser.parse_args()
    out = args.map_dir.resolve()
    source = out / "source"
    for folder in ["audit", "reports"]:
        (out / folder).mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source / "manifest.json").read_text())
    for record in manifest["files"]:
        if sha256(source / record["snapshot"]) != record["sha256"]:
            raise ValueError(f"Source snapshot hash mismatch: {record['snapshot']}")
    xodr = source / "kcity.xodr"
    reference = out / "kcity.reference.net.xml"
    command_reference = import_network(xodr, reference, out / "audit" / "reference_warnings.log")
    net = sumolib.net.readNet(str(reference), withInternal=True)
    cfg = yaml.safe_load((source / "qualifier.yaml").read_text())
    signals = []
    for key in ["Q_SIGNAL1", "Q_SIGNAL2"]:
        point = cfg["triggers"][key]["center"]
        x, y = point["x"], -point["y"]
        distance, node = min(((math.dist((x, y), n.getCoord()), n) for n in net.getNodes()
                              if len(n.getIncoming()) >= 3), key=lambda pair: pair[0])
        if distance > 20:
            raise ValueError(f"Signal reference {key} too far from a junction: {distance}")
        signals.append(dict(source_trigger=key, junction_id=node.getID(), distance_m=distance,
                            source_carla_xy=[point["x"], point["y"]], sumo_xy=[x, y],
                            mapping_status="nearest complex junction; requires site verification",
                            phase_status="SUMO-generated synthetic static program; not measured"))
    # Four ambiguous multi-leg junctions reported by netconvert. Explicit conservative
    # simulation rules, NOT assertions about the physical site's stop signs.
    stop_nodes = ["112", "176", "477", "747"]
    node_patch = ET.Element("nodes")
    for node_id in stop_nodes:
        node = net.getNode(node_id)
        x, y = node.getCoord()
        ET.SubElement(node_patch, "node", id=node_id, x=str(x), y=str(y), type="allway_stop")
    write_xml(out / "kcity.junctions.nod.xml", node_patch)
    command_demo = import_network(xodr, out / "kcity.net.xml", out / "audit" / "demo_warnings.log",
                                  tls=[s["junction_id"] for s in signals], node_patch=out / "kcity.junctions.nod.xml")
    net = sumolib.net.readNet(str(out / "kcity.net.xml"), withInternal=True)
    qualifier, q_info = qualifier_route(net, source / "qualifier.csv")
    # Match source CSV before intentional pruning: it describes lane-level source
    # points, while the SUMO demo follows the preserved edge route, not those lanes.
    pruning = {}
    policy_path = out / 'lane_pruning.json'
    if policy_path.exists():
        for path in [reference, out / 'kcity.net.xml']:
            pruning[path.name] = prune_network(path, policy_path)
        mapping = pruning['kcity.net.xml']['lane_id_mapping']
        for row in q_info['matched_rows']:
            row['baseline_lane'] = row.pop('lane')
            row['lane'] = mapping.get(row['baseline_lane'])
            row['status'] = ('internal source reference; IDs regenerated' if row['internal']
                             else 'retained' if row['lane'] else 'removed by lane pruning policy')
        start = next(r for r in q_info['matched_rows'] if not r['internal'])
        if start['lane'] is None:
            raise ValueError('Qualifier departure lane was removed')
        q_info['depart_lane'] = int(start['lane'].rsplit('_', 1)[1])
        net = sumolib.net.readNet(str(out / 'kcity.net.xml'), withInternal=True)
        qualifier = [net.getEdge(e.getID()) for e in qualifier]
    if (out / 'signal_policy.json').exists():
        signals = apply_signals(out)
        stop_nodes = [n for n in stop_nodes if n not in {s['junction_id'] for s in signals}]
        net = sumolib.net.readNet(str(out / 'kcity.net.xml'), withInternal=True)
        qualifier = [net.getEdge(e.getID()) for e in qualifier]
    routes, witnesses = coverage_routes(net, out / "traffic_plan.json")
    routes["qualifier"] = qualifier
    root = ET.Element("routes")
    # Synthetic demonstration speeds/flow. Original 40 mph road metadata stays intact.
    for model in ["Krauss", "IDM", "EIDM", "ACC"]:
        ET.SubElement(root, "vType", id=f"hv_{model}", carFollowModel=model, length="4.5", width="1.8",
                      accel="2.0", decel="4.5", emergencyDecel="8.0", tau="1.5", minGap="2.5",
                      maxSpeed="8.33", speedFactor="1.0", speedDev="0.05", vClass="passenger")
    ET.SubElement(root, "vType", id="demo_ego", carFollowModel="IDM", length="4.5", width="1.8",
                  accel="2.0", decel="4.5", tau="1.5", maxSpeed="8.33", color="1,0.1,0.1",
                  vClass="passenger")
    for name, path in routes.items():
        ET.SubElement(root, "route", id=name, edges=" ".join(e.getID() for e in path))
    for name in sorted(witnesses):
        i = int(name.rsplit('_', 1)[1])  # Keep other vehicle IDs/types/departures unchanged.
        ET.SubElement(root, "vehicle", id=f"hv_{i:03d}", type=f"hv_{['Krauss','IDM','EIDM','ACC'][i % 4]}",
                      route=name, depart=f"{i * 6.0:.1f}", departLane="best", departSpeed="0")
    # Must keep vehicle departures sorted in SUMO input.
    demo = ET.Element("vehicle", id="demo_ego", type="demo_ego", route="qualifier", depart="10",
                      departLane=str(q_info["depart_lane"]), departPos=f"{q_info['depart_pos']:.3f}",
                      arrivalPos=f"{q_info['arrival_pos']:.3f}", departSpeed="0")
    root.append(demo)
    vehicles = list(root.findall("vehicle"))
    for vehicle in vehicles:
        root.remove(vehicle)
    root.extend(sorted(vehicles, key=lambda v: float(v.get("depart"))))
    write_xml(out / "kcity.rou.xml", root)
    # Reference markers are annotations, not stop-line enforcement.
    additional = ET.Element("additional")
    for key, item in cfg["triggers"].items():
        p = item["center"]
        ET.SubElement(additional, "poi", id=key, x=str(p["x"]), y=str(-p["y"]),
                      color="0.95,0.55,0.05", type="CARLA reference marker", layer="10")
    write_xml(out / "kcity.add.xml", additional)
    gui = ET.Element("viewsettings")
    ET.SubElement(gui, "scheme", name="real world")
    ET.SubElement(gui, "delay", value="40")
    write_xml(out / "kcity.gui.xml", gui)
    for profile, network in [("kcity", "kcity.net.xml"), ("kcity.reference", "kcity.reference.net.xml")]:
        config = ET.Element("configuration")
        inputs = ET.SubElement(config, "input")
        for tag, value in [("net-file", network), ("route-files", "kcity.rou.xml"),
                           ("additional-files", "kcity.add.xml,kcity.signals.add.xml"
                            if profile == 'kcity' and (out / 'signal_policy.json').exists() else "kcity.add.xml")]:
            ET.SubElement(inputs, tag, value=value)
        time = ET.SubElement(config, "time")
        ET.SubElement(time, "step-length", value="0.1")
        ET.SubElement(time, "end", value="1800")
        processing = ET.SubElement(config, "processing")
        ET.SubElement(processing, "time-to-teleport", value="-1")
        ET.SubElement(processing, "collision.action", value="warn")
        ET.SubElement(processing, "collision.check-junctions", value="true")
        gui_config = ET.SubElement(config, "gui_only")
        ET.SubElement(gui_config, "gui-settings-file", value="kcity.gui.xml")
        write_xml(out / f"{profile}.sumocfg", config)
    inventory = network_inventory(net, xodr)
    pruned_ids = pruning.get('kcity.net.xml', {}).get('source_road_ids_removed_by_pruning', [])
    inventory['intentionally_pruned_source_road_ids'] = pruned_ids
    inventory['unrepresented_source_road_ids'] = sorted(set(inventory['unrepresented_source_road_ids']) - set(pruned_ids))
    inventory.update(signals=signals, synthetic_allway_stop_nodes=stop_nodes,
                     lane_pruning=pruning,
                     route_count=len(routes), traffic_vehicles=len(vehicles),
                     coverage_targets=witnesses, qualifier=dict(
                         edges=[e.getID() for e in qualifier],
                         total_edge_length_m=sum(e.getLength() for e in qualifier), **q_info),
                     source_hashes={r["snapshot"]: r["sha256"] for r in manifest["files"]},
                     network_sha256=sha256(out / "kcity.net.xml"),
                     netconvert_version=subprocess.check_output(["netconvert", "--version"], text=True).splitlines()[0],
                     commands=[command_reference, command_demo],
                     assumptions=["source contains no signals; demo TLS placements use MGEO proximity, CARLA references and explicit engineering assumptions",
                                  "signal cycles are synthetic demand-actuated; not measured field timing",
                                  "remaining ambiguous unsignalized junctions use synthetic all-way-stop rules",
                                  "all source speeds are 40 mph, not verified site limits; demo vehicle speed capped at 8.33 m/s",
                                  "intersection shapes generated by SUMO due to 4-31 m endpoint gaps in original-shape import",
                                  "traffic is synthetic coverage traffic, not measured K-City demand",
                                  "demo_ego uses SUMO IDM, not a trained AV policy",
                                  "MGeo and JJ image are references only; no cross-version road stitching"])
    write_json(out / "reports" / "build.json", inventory)
    from scenery import make_scenery
    make_scenery(out)
    print(f"Built {inventory['regular_edges']} edges / {inventory['regular_lanes']} lanes / "
          f"{len(routes)} routes in {out}")


if __name__ == "__main__":
    main()
