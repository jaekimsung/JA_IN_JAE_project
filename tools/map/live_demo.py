"""Continuous recording demo: one persistent IDM ego and replenished HV traffic."""
import copy
import json
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from env.common import MAP, sumo_tools, write_xml, write_json, sha256


def run(args):
    sumolib = sumo_tools()
    import traci

    source = ET.parse(MAP / 'kcity.rou.xml').getroot()
    net = sumolib.net.readNet(str(MAP / 'kcity.net.xml'))
    qualifier = source.find("route[@id='qualifier']").get('edges').split()
    back, _ = net.getShortestPath(net.getEdge(qualifier[-1]),
                                  net.getEdge(qualifier[0]), vClass='passenger')
    if not back:
        raise RuntimeError('No passenger-car return route for demo_ego')
    loop = qualifier + [edge.getID() for edge in back][1:]
    for a, b in zip(loop, loop[1:]):
        if not any(c.allows('passenger') for c in
                   net.getEdge(a).getOutgoing().get(net.getEdge(b), [])):
            raise RuntimeError(f'Invalid ego connection: {a} -> {b}')

    routes = ET.Element('routes')
    for element in source:
        if element.tag in ('vType', 'route'):
            routes.append(copy.deepcopy(element))
    ET.SubElement(routes, 'route', id='ego_loop', edges=' '.join(loop))
    ego = copy.deepcopy(source.find("vehicle[@id='demo_ego']"))
    ego.set('route', 'ego_loop')
    ego.set('depart', '0')
    ego.attrib.pop('arrivalPos', None)
    routes.append(ego)
    hv_routes = [r.get('id') for r in source.findall('route')
                 if r.get('id').startswith('coverage_')]
    hv_types = [v.get('id') for v in source.findall('vType')
                if v.get('id').startswith('hv_')]
    summary = dict(seed=args.seed, hv_period_s=args.traffic_period,
                   hv_limit_including_pending=args.max_traffic,
                   ego_loop=loop, ego_route_extensions=0, ego_departures=0,
                   ego_arrivals=0, ego_missing_steps_after_departure=0,
                   ego_distance_m=0, ego_max_continuous_wait_s=0,
                   collisions=0, teleports=0, max_hv_running=0,
                   hv_requested=0, hv_arrived=0, completed=False,
                   net_sha256=sha256(MAP / 'kcity.net.xml'),
                   signals_sha256=sha256(MAP / 'kcity.signals.add.xml'))
    active_sum = active_count = 0
    zoom = args.zoom if args.zoom is not None else (500 if args.follow_ego else 100)
    with tempfile.TemporaryDirectory(prefix='kcity-live-') as directory:
        directory = Path(directory)
        write_xml(directory / 'traffic.rou.xml', routes)
        gui = ET.parse(MAP / ('kcity.aerial.gui.xml' if args.aerial else 'kcity.gui.xml'))
        view = gui.getroot().find('viewport')
        if view is not None:
            gui.getroot().remove(view)
        xmin, ymin, xmax, ymax = net.getBoundary()
        ET.SubElement(gui.getroot(), 'viewport', x=str((xmin + xmax) / 2),
                      y=str((ymin + ymax) / 2), zoom=str(zoom), angle=str(args.angle))
        # Make relative aerial texture paths independent of the temporary directory.
        for decal in gui.getroot().iter('decal'):
            filename = decal.get('filename')
            if filename and not Path(filename).is_absolute():
                decal.set('filename', str(MAP / filename))
        for scheme in gui.getroot().findall('scheme'):
            vehicles = scheme.find('vehicles')
            if vehicles is None:
                vehicles = ET.SubElement(scheme, 'vehicles')
            vehicles.set('vehicleMode', '0')
            vehicles.set('vehicle_exaggeration', '1')
            vehicles.set('vehicle_minSize', '1')
            vehicles.set('vehicleQuality', '2')
        write_xml(directory / 'view.xml', gui.getroot())
        command = [sumolib.checkBinary('sumo' if args.nogui else 'sumo-gui'),
                   '-c', str(MAP / 'kcity.sumocfg'), '--route-files', str(directory / 'traffic.rou.xml'),
                   '--seed', str(args.seed), '--end', '-1', '--no-step-log', 'true',
                   '--duration-log.disable', 'true']
        if args.aerial:
            command += ['--additional-files', ','.join(str(MAP / f) for f in
                        ('kcity.add.xml', 'kcity.signals.add.xml'))]
        if not args.nogui:
            command += ['--gui-settings-file', str(directory / 'view.xml'),
                        '--start', '--quit-on-end', '--delay', str(args.delay), '--window-size', '1920,1080']
        traci.start(command)
        conn = traci.getConnection()
        next_depart = 0.0
        tracking_started = False
        try:
            while args.seconds is None or conn.simulation.getTime() < args.seconds:
                now = conn.simulation.getTime()
                ids = conn.vehicle.getIDList()
                if now + 1e-6 >= next_depart:
                    pending = conn.simulation.getPendingVehicles()
                    hv_count = sum(v != 'demo_ego' for v in ids) + sum(v != 'demo_ego' for v in pending)
                    if hv_count < args.max_traffic:
                        i = summary['hv_requested']
                        vid = f'live_hv_{i:06d}'
                        conn.vehicle.add(vid, hv_routes[i % len(hv_routes)],
                                         typeID=hv_types[i % len(hv_types)], departLane='best')
                        conn.vehicle.setColor(vid, (255, 255, 0, 255))
                        summary['hv_requested'] += 1
                    next_depart = now + args.traffic_period
                conn.simulationStep()
                summary['time_s'] = conn.simulation.getTime()
                departed = conn.simulation.getDepartedIDList()
                arrived = conn.simulation.getArrivedIDList()
                summary['ego_departures'] += int('demo_ego' in departed)
                summary['ego_arrivals'] += int('demo_ego' in arrived)
                summary['hv_arrived'] += sum(v != 'demo_ego' for v in arrived)
                summary['collisions'] += conn.simulation.getCollidingVehiclesNumber()
                summary['teleports'] += conn.simulation.getStartingTeleportNumber()
                ids = conn.vehicle.getIDList()
                count = sum(v != 'demo_ego' for v in ids)
                summary['max_hv_running'] = max(summary['max_hv_running'], count)
                if summary['time_s'] >= 300 and abs(summary['time_s'] - round(summary['time_s'])) < 1e-5:
                    active_sum += count
                    active_count += 1
                if 'demo_ego' in ids:
                    if args.follow_ego and not tracking_started:
                        view_id = conn.gui.DEFAULT_VIEW
                        conn.gui.trackVehicle(view_id, 'demo_ego')
                        conn.gui.setZoom(view_id, zoom)
                        conn.gui.setAngle(view_id, args.angle)
                        tracking_started = True
                        print(f"Camera tracking: {conn.gui.getTrackedVehicle(view_id)}; "
                              f"zoom={conn.gui.getZoom(view_id):g}; "
                              f"angle={conn.gui.getAngle(view_id):g}", flush=True)
                    summary['ego_distance_m'] = conn.vehicle.getDistance('demo_ego')
                    summary['ego_max_continuous_wait_s'] = max(
                        summary['ego_max_continuous_wait_s'], conn.vehicle.getWaitingTime('demo_ego'))
                    route = conn.vehicle.getRoute('demo_ego')
                    index = conn.vehicle.getRouteIndex('demo_ego')
                    if index >= len(route) - 4 and not conn.vehicle.getRoadID('demo_ego').startswith(':'):
                        # Keep the current edge and suffix, then append another connected lap.
                        # This preserves ID, position and speed without removing/reinserting the car.
                        conn.vehicle.setRoute('demo_ego', list(route[index:]) + loop[1:])
                        summary['ego_route_extensions'] += 1
                elif summary['ego_departures']:
                    summary['ego_missing_steps_after_departure'] += 1
                    raise RuntimeError('demo_ego disappeared unexpectedly')
            summary['completed'] = True
        except KeyboardInterrupt:
            summary['stopped_by_user_or_connection_closed'] = True
        except traci.exceptions.FatalTraCIError:
            summary['stopped_by_user_or_connection_closed'] = True
            if args.nogui:
                raise
        finally:
            try:
                conn.close()
            except traci.exceptions.FatalTraCIError:
                pass
            summary['mean_hv_running_after_300s'] = (
                active_sum / active_count if active_count else None)
            if args.report:
                write_json(Path(args.report), summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
