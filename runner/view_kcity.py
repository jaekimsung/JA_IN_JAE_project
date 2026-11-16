#!/usr/bin/env python3
"""Open the K-CITY map demo in SUMO GUI (red demo ego + continuous background traffic), headless check or netedit."""
import argparse
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.env.common import MAP, sumo_tools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netedit", action="store_true")
    parser.add_argument("--nogui", action="store_true")
    parser.add_argument("--reference", action="store_true", help="Use source-only priority junctions, without synthetic TLS")
    parser.add_argument("--aerial", action="store_true", help="Overlay JJ's georeferenced aerial reference (GUI only)")
    parser.add_argument("--baseline", action="store_true", help="Run the original finite 177-vehicle validation scenario")
    parser.add_argument("--seconds", type=float, default=None, help="Simulation duration; live GUI defaults to unlimited")
    parser.add_argument("--traffic-period", type=float, default=3.0, help="Live HV insertion interval in seconds")
    parser.add_argument("--max-traffic", type=int, default=60, help="Live HV limit including pending insertions")
    parser.add_argument("--angle", type=float, default=90, help="Live view rotation in degrees")
    parser.add_argument("--follow-ego", action="store_true", help="Keep the red demo_ego centered in the live GUI")
    parser.add_argument("--zoom", type=float, help="Live GUI zoom; default 500 when following, otherwise 100")
    parser.add_argument("--delay", type=float, default=100, help="Live GUI delay per 0.1 s step, in milliseconds")
    parser.add_argument("--report", help="Write live demo metrics to this JSON path")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.follow_ego and (args.nogui or args.baseline or args.reference or args.netedit):
        parser.error("--follow-ego requires the live GUI mode")
    if args.zoom is not None and args.zoom <= 0:
        parser.error("--zoom must be positive")
    if args.seconds is not None and args.seconds <= 0:
        parser.error("--seconds must be positive")
    if args.traffic_period < 0.1 or args.max_traffic < 1 or args.delay < 0:
        parser.error("Require --traffic-period >= 0.1, --max-traffic >= 1, --delay >= 0")
    if not (args.baseline or args.reference or args.netedit):
        if args.nogui and args.seconds is None:
            parser.error("Use --seconds with --nogui to bound the continuous simulation")
        from live_demo import run
        print("K-City live: persistent red IDM demo_ego; replenished yellow traffic.", flush=True)
        run(args)
        return
    sumolib = sumo_tools()
    profile = "kcity.reference" if args.reference else "kcity"
    if args.netedit:
        command = [sumolib.checkBinary("netedit"), "-s", str(MAP / f"{profile}.net.xml")]
    else:
        command = [sumolib.checkBinary("sumo" if args.nogui else "sumo-gui"),
                   "-c", str(MAP / f"{profile}.sumocfg"), "--seed", str(args.seed),
                   "--end", str(args.seconds if args.seconds is not None else 1800)]
        if args.nogui:
            command += ["--no-step-log", "true", "--duration-log.statistics", "true"]
        elif args.aerial:
            command += ["--gui-settings-file", str(MAP / "kcity.aerial.gui.xml")]
            # Decorative buildings/trees belong to the non-aerial view only.
            cfg = ET.parse(MAP / f'{profile}.sumocfg').getroot()
            files = cfg.find('input/additional-files').get('value').split(',')
            command += ['--additional-files', ','.join(str(MAP / f) for f in files
                                                       if f != 'kcity.scenery.add.xml')]
    print("K-City: synthetic traffic; red demo_ego is IDM, not a trained AV.", flush=True)
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
