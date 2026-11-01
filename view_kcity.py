#!/usr/bin/env python3
"""Open the isolated K-City network. Does not regenerate the highway training map."""
import argparse
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts" / "kcity"))
from common import MAP, sumo_tools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netedit", action="store_true")
    parser.add_argument("--nogui", action="store_true")
    parser.add_argument("--reference", action="store_true", help="Use source-only priority junctions, without synthetic TLS")
    parser.add_argument("--aerial", action="store_true", help="Overlay JJ's georeferenced aerial reference (GUI only)")
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    sumolib = sumo_tools()
    profile = "kcity.reference" if args.reference else "kcity"
    if args.netedit:
        command = [sumolib.checkBinary("netedit"), "-s", str(MAP / f"{profile}.net.xml")]
    else:
        command = [sumolib.checkBinary("sumo" if args.nogui else "sumo-gui"),
                   "-c", str(MAP / f"{profile}.sumocfg"), "--seed", str(args.seed),
                   "--end", str(args.seconds)]
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
