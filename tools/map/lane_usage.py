"""Measure every regular/internal lane over the fixed demonstration seeds."""
import concurrent.futures
import subprocess
import xml.etree.ElementTree as ET

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from kcity.common import MAP, sha256, sumo_tools, write_json, write_xml

sumo_tools()
EVENTS = ['departed', 'arrived', 'entered', 'left', 'laneChangedFrom', 'laneChangedTo']


def run(seed):
    folder = MAP / 'reports/lane_usage_after_pruning' / f'seed{seed}'
    folder.mkdir(parents=True, exist_ok=True)
    additional = ET.Element('additional')
    ET.SubElement(additional, 'laneData', id='coverage', file=str(folder / 'lanes.xml'),
                  period='1800', begin='0', end='1800', excludeEmpty='false',
                  withInternal='true', minSamples='0')
    write_xml(folder / 'measure.add.xml', additional)
    command = ['sumo', '-c', str(MAP / 'kcity.sumocfg'), '--additional-files',
               ','.join(str(p) for p in [MAP / 'kcity.add.xml', MAP / 'kcity.signals.add.xml',
                                         folder / 'measure.add.xml'] if p.exists()),
               '--seed', str(seed), '--end', '1800', '--no-step-log', 'true',
               '--duration-log.disable', 'true', '--precision', '6']
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (folder / 'stdout.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return seed, {l.get('id'): dict(sampled_seconds=float(l.get('sampledSeconds', 0)),
                                   events={k: int(l.get(k, 0)) for k in EVENTS})
                  for l in ET.parse(folder / 'lanes.xml').findall('.//lane')}


def main():
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        runs = dict(pool.map(run, [0, 1, 2]))
    net = ET.parse(MAP / 'kcity.net.xml').getroot()
    lanes = {}
    for edge in net.findall('edge'):
        for lane in edge.findall('lane'):
            lid = lane.get('id')
            measures = {str(seed): rows[lid] for seed, rows in runs.items()}
            lanes[lid] = dict(internal=edge.get('function') == 'internal', runs=measures,
                             used=any(m['sampled_seconds'] > 0 or any(m['events'].values())
                                      for m in measures.values()))
    unused = [lid for lid, record in lanes.items() if not record['used']]
    result = dict(network_sha256=sha256(MAP / 'kcity.net.xml'),
                  signals_sha256=sha256(MAP / 'kcity.signals.add.xml') if (MAP / 'kcity.signals.add.xml').exists() else None,
                  routes_sha256=sha256(MAP / 'kcity.rou.xml'), seeds=[0, 1, 2],
                  regular_lanes=sum(not r['internal'] for r in lanes.values()),
                  internal_lanes=sum(r['internal'] for r in lanes.values()),
                  unused=unused, lanes=lanes)
    write_json(MAP / 'reports/lane_usage_after_pruning/summary.json', result)
    print({k: v for k, v in result.items() if k != 'lanes'})
    if unused:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
