#!/usr/bin/env python3
"""Bounded traffic validation. Never treats network traffic as trained-AV performance."""
import argparse
import collections
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from kcity.env.common import MAP, sha256, sumo_tools, write_json

sumolib = sumo_tools()
import traci


def topology_check(map_dir):
    net = sumolib.net.readNet(str(map_dir / "kcity.net.xml"), withInternal=True)
    root = ET.parse(map_dir / "kcity.rou.xml").getroot()
    errors = []
    routes = {}
    for route in root.findall("route"):
        ids = route.get("edges").split()
        routes[route.get("id")] = ids
        for edge_id in ids:
            if not net.hasEdge(edge_id) or net.getEdge(edge_id).getFunction() == "internal":
                errors.append(f"Invalid external route edge: {edge_id}")
        for a, b in zip(ids, ids[1:]):
            if net.getEdge(b) not in net.getEdge(a).getOutgoing():
                errors.append(f"Disconnected route {route.get('id')}: {a} -> {b}")
    build = json.loads((map_dir / "reports" / "build.json").read_text())
    if len(build['weak_components']) != 1:
        errors.append('Network must have one weakly connected component')
    for edge_id in build.get('intentionally_excluded_source_roads', {}):
        if net.hasEdge(edge_id):
            errors.append(f'Excluded edge still exists: {edge_id}')
    for route, target in build["coverage_targets"].items():
        if target not in routes[route]:
            errors.append(f"Coverage target absent: {route} / {target}")
    return dict(route_count=len(routes), coverage_target_count=len(build["coverage_targets"]), errors=errors)


def run(map_dir, seed, seconds, profile="kcity"):
    output = map_dir / "reports" / f"{profile}_seed{seed}"
    output.mkdir(parents=True, exist_ok=True)
    label = f"kcity_validation_{seed}"
    command = [sumolib.checkBinary("sumo"), "-c", str(map_dir / f"{profile}.sumocfg"),
               "--seed", str(seed), "--end", str(seconds), "--no-step-log", "true",
               "--duration-log.disable", "true", "--error-log", str(output / "warnings.log"),
               "--tripinfo-output", str(output / "tripinfo.xml"),
               "--tripinfo-output.write-unfinished", "true"]
    start = time.monotonic()
    stdout = (output / "stdout.log").open("w")
    traci.start(command, label=label, stdout=stdout)
    connection = traci.getConnection(label)
    signal_ids = list(connection.trafficlight.getIDList())
    for tid in signal_ids:
        connection.trafficlight.subscribe(tid, [traci.constants.TL_CURRENT_PROGRAM,
                                               traci.constants.TL_RED_YELLOW_GREEN_STATE])
    signal_states = {tid: set() for tid in signal_ids}
    signal_programs = {tid: set() for tid in signal_ids}
    departed, arrived, collided, teleporting, visited = set(), set(), set(), set(), set()
    max_running = 0
    peak_time = 0
    max_wait = collections.defaultdict(float)
    events = []
    previous_lanes = {}
    lane_changes = 0
    demo = dict(departed=False, arrived=False, collided=False, max_wait_s=0)
    try:
        while connection.simulation.getTime() < seconds:
            connection.simulationStep()
            now = connection.simulation.getTime()
            departed.update(connection.simulation.getDepartedIDList())
            arrived.update(connection.simulation.getArrivedIDList())
            collisions = connection.simulation.getCollidingVehiclesIDList()
            teleports = connection.simulation.getStartingTeleportIDList()
            if collisions or teleports:
                events.append(dict(time_s=now, collisions=list(collisions), teleports=list(teleports)))
            collided.update(collisions)
            teleporting.update(teleports)
            ids = connection.vehicle.getIDList()
            if len(ids) > max_running:
                max_running, peak_time = len(ids), now
            # Sample states every second, collision/arrival events every 0.1 s.
            if abs(now - round(now)) < 1e-5:
                for tid, values in connection.trafficlight.getAllSubscriptionResults().items():
                    signal_states[tid].add(values[traci.constants.TL_RED_YELLOW_GREEN_STATE])
                    signal_programs[tid].add(values[traci.constants.TL_CURRENT_PROGRAM])
                for vid in ids:
                    edge = connection.vehicle.getRoadID(vid)
                    lane = connection.vehicle.getLaneIndex(vid)
                    if edge and not edge.startswith(":"):
                        visited.add(edge)
                    wait = connection.vehicle.getWaitingTime(vid)
                    max_wait[vid] = max(max_wait[vid], wait)
                    if vid in previous_lanes and previous_lanes[vid][0] == edge and previous_lanes[vid][1] != lane:
                        lane_changes += 1
                    previous_lanes[vid] = (edge, lane)
            if connection.simulation.getMinExpectedNumber() == 0:
                break
        running = list(connection.vehicle.getIDList())
        remaining = connection.simulation.getMinExpectedNumber()
        sim_end = connection.simulation.getTime()
        for key, group in [("departed", departed), ("arrived", arrived), ("collided", collided)]:
            demo[key] = "demo_ego" in group
        demo["max_wait_s"] = max_wait.get("demo_ego", 0)
    finally:
        connection.close()
        stdout.close()
    root = ET.parse(output / "tripinfo.xml").getroot()
    finished = [t for t in root.findall("tripinfo") if float(t.get("arrival", "-1")) >= 0]
    # Tripinfo includes every visited regular edge only indirectly; dynamic coverage below is sampled.
    route_root = ET.parse(map_dir / "kcity.rou.xml").getroot()
    build = json.loads((map_dir / "reports" / "build.json").read_text())
    completed_targets = sorted({build["coverage_targets"][v.get("route")]
                                for v in route_root.findall("vehicle") if v.get("id") in arrived
                                and v.get("route") in build["coverage_targets"]})
    warnings = (output / "warnings.log").read_text()
    result = dict(seed=seed, profile=profile, simulated_seconds=sim_end,
                  wall_seconds=time.monotonic() - start, departed=len(departed), arrived=len(arrived),
                  remaining_expected=remaining, running_at_end=running,
                  collided_vehicle_ids=sorted(collided), teleport_vehicle_ids=sorted(teleporting),
                  collision_event_steps=len([e for e in events if e["collisions"]]),
                  events=events, peak_running=max_running, peak_time_s=peak_time,
                  sampled_visited_edges=sorted(visited), sampled_lane_changes=lane_changes,
                  max_continuous_wait_s=max(max_wait.values(), default=0),
                  longest_waits=sorted(max_wait.items(), key=lambda x: x[1], reverse=True)[:10],
                  mean_trip_duration_s=sum(float(t.get("duration")) for t in finished) / max(1, len(finished)),
                  completed_witness_targets=completed_targets,
                  emergency_braking_warnings=warnings.count("performs emergency braking"),
                  demo_ego=demo, network_sha256=sha256(map_dir / f"{profile}.net.xml"),
                  routes_sha256=sha256(map_dir / "kcity.rou.xml"),
                  signals_sha256=sha256(map_dir / 'kcity.signals.add.xml') if profile == 'kcity' and (map_dir / 'kcity.signals.add.xml').exists() else None,
                  signal_programs={k: sorted(v) for k, v in signal_programs.items()},
                  signal_states_observed={k: sorted(v) for k, v in signal_states.items()},
                  sumo_version=__import__("subprocess").check_output([sumolib.checkBinary("sumo"), "--version"], text=True).splitlines()[0],
                  passed=not collided and not teleporting and remaining == 0 and demo["arrived"],
                  limitations=["SUMO built-in car-following controllers, not AV learning evaluation",
                               "finite synthetic traffic/seeds; no real traffic demand validation",
                               "edge occupancy sampled at 1 s can miss very short edges"])
    write_json(output / "result.json", result)
    print(json.dumps({k: result[k] for k in ["seed", "profile", "departed", "arrived", "remaining_expected",
                                            "collision_event_steps", "peak_running", "max_continuous_wait_s", "passed"]}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-dir", type=Path, default=MAP)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--profile", choices=["kcity", "kcity.reference"], default="kcity")
    args = parser.parse_args()
    out = args.map_dir.resolve()
    topology = topology_check(out)
    if topology["errors"]:
        raise ValueError(topology["errors"])
    runs = [run(out, s, args.seconds, args.profile) for s in args.seeds]
    write_json(out / "reports" / f"validation_{args.profile}.json",
               dict(topology=topology, runs=runs, passed=all(r["passed"] for r in runs)))
    if not all(r["passed"] for r in runs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
