"""Drive a policy in SUMO GUI and optionally record an mp4 (inference only, no learning).

    python runner/record_video.py --policy expert --scenario C --output runs/video/expert_C --once
    python runner/record_video.py --policy runs/B3_seed11/.../T000300000-... --scenario C \
        --output runs/video/B3_C --video --once

The AV is red, HVs are yellow. --video saves one GUI screenshot per simulation tick and
encodes <output>/drive.mp4 with ffmpeg (frames are kept if ffmpeg is unavailable).
Presentation dynamics: --demo-step 0.02 renders smoother motion; it is not the evaluation tick.
"""
import sys
from pathlib import Path

import argparse
import json
from importlib.util import find_spec
import os
from datetime import datetime
import shutil
import subprocess
import time
from unittest.mock import patch
import xml.etree.ElementTree as ET

def use_dashboard_environment():
    # The stdlib-only dashboard may run under the system Python.
    required = ("gymnasium", "torch", "numpy")
    if sys.prefix != sys.base_prefix or all(find_spec(name) for name in required):
        return
    root = Path(__file__).resolve().parents[1]
    candidates = [root / ".venv", root / "venv"]
    candidates.extend(sorted((Path.home() / ".cache").glob("kcity-research-audit-*/venv"), reverse=True))
    for environment in candidates:
        python = environment / "bin/python"
        if not (environment / "pyvenv.cfg").is_file() or not os.access(python, os.X_OK):
            continue
        probe = subprocess.run([str(python), "-c", "import gymnasium, torch, numpy"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            # exec retains the status pipe passed by the running dashboard.
            os.execv(python, [str(python), "-u", "-B", *sys.argv])
    raise SystemExit("SUMO 데모용 Python 환경을 찾을 수 없습니다. "
                     "학습 가상환경의 Python을 --demo-python 옵션으로 지정하세요.")


if __name__ == "__main__" and "--status-fd" in sys.argv:
    use_dashboard_environment()

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.data.dataset import atomic_json
from kcity.env.config import ROOT
from kcity.env.env import SumoKCityEnv
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.policy.checkpoint import load_policy

AV_COLOR, HV_COLOR = (255, 30, 30, 255), (255, 215, 0, 255)


def encode(frames, fps, target):
    ffmpeg = shutil.which('ffmpeg')
    command = [ffmpeg or 'ffmpeg', '-y', '-loglevel', 'error', '-framerate', f'{fps:g}', '-i', str(frames / 'frame_%06d.png'),
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', str(target)]
    if ffmpeg is None:
        return dict(encoded=False, command=' '.join(command))
    subprocess.run(command, check=True)
    return dict(encoded=True, path=str(target))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--policy', required=True, help="'expert' or a learner bundle directory")
    ap.add_argument('--scenario', choices=['A', 'B', 'C'], default='C')
    ap.add_argument('--case-index', type=int, default=1000000)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--speed', type=float, default=2.5, help='display speed relative to real time')
    ap.add_argument('--demand-multiplier', type=float, default=1.)
    ap.add_argument('--warmup', type=float, default=60.)
    ap.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    ap.add_argument('--demo-step', type=float, choices=[.1, .02], default=.1)
    ap.add_argument('--zoom', type=float, default=500.)
    ap.add_argument('--overview', action='store_true', help='show the whole map instead of tracking the AV')
    ap.add_argument('--once', action='store_true', help='stop after one Episode')
    ap.add_argument('--video', action='store_true', help='record frames and encode <output>/drive.mp4')
    ap.add_argument('--status-fd', type=int, help='send demo status to an inherited pipe instead of STATUS.json')
    args = ap.parse_args()
    status_pipe = os.fdopen(args.status_fd, 'w') if args.status_fd is not None else None

    def report(state):
        nonlocal status_pipe
        if args.status_fd is None:
            atomic_json(args.output / 'STATUS.json', state)
        elif status_pipe is not None:
            try:
                update = dict(phase=state['phase'], message=state.get('message', ''),
                              completed=len(state['episodes']))
                print(json.dumps(update), file=status_pipe, flush=True)
            except BrokenPipeError:
                # The GUI can outlive a dashboard restart.
                status_pipe = None

    if args.speed <= 0 or args.demand_multiplier <= 0 or args.warmup < 0:
        ap.error('Invalid speed/demand/warmup')
    torch.set_num_threads(1)
    args.output.mkdir(parents=True, exist_ok=False)
    if args.policy == 'expert':
        model, source = KCityRuleExpert(), 'expert'
    else:
        model, _ = load_policy(args.policy, args.device)
        source = str(Path(args.policy).resolve())
    view = ET.parse(ROOT / 'maps/kcity/kcity.gui.xml')
    for scheme in view.getroot().findall('scheme'):
        vehicles = ET.SubElement(scheme, 'vehicles')
        for key, value in [('vehicleMode', '0'), ('vehicle_exaggeration', '1'), ('vehicle_minSize', '1'), ('vehicleQuality', '2')]:
            vehicles.set(key, value)
    view.write(args.output / 'view.xml', encoding='utf-8', xml_declaration=True)
    env = SumoKCityEnv(gui=True, background=True, scenario_id=args.scenario, debug_warmup_s=args.warmup)
    # Presentation-only dynamics variant held in memory; on-disk configs are not changed.
    env.contract['protocol']['timing']['sumo_step_s'] = args.demo_step
    env.contract['protocol']['timing']['substeps'] = round(.5 / args.demo_step)
    original_start = env.traci.start

    def gui_start(cmd, **kwargs):
        cmd = list(cmd)
        idx = cmd.index('-a') + 1
        cmd[idx] += ',' + str(ROOT / 'maps/kcity/kcity.add.xml') + ',' + str(ROOT / 'maps/kcity/kcity.scenery.add.xml')
        cmd += ['--gui-settings-file', str((args.output / 'view.xml').resolve()), '--delay', '0',
                '--window-size', '1600,950', '--window-pos', '40,40']
        return original_start(cmd, **kwargs)

    info = dict(policy=source, scenario=args.scenario, namespace='dev', case_index=args.case_index,
                display_speed=args.speed, demand_multiplier=args.demand_multiplier, warmup_s=args.warmup,
                demo_physics_tick_s=args.demo_step, policy_decision_period_s=.5,
                variant='presentation demo; not the evaluation run', episodes=[])
    report(dict(phase='STARTING_GUI', **info))
    frames = args.output / 'frames'
    try:
        while True:
            with patch.object(env.traci, 'start', side_effect=gui_start):
                obs, reset = env.reset(options=dict(namespace='dev', scenario_id=args.scenario, case_index=args.case_index,
                                                    demand_multiplier=args.demand_multiplier))
            conn = env.conn
            view_id = conn.gui.getIDList()[0]
            conn.gui.setAngle(view_id, 90.)
            native_step = conn.simulationStep
            frame = [0]
            if args.video:
                frames.mkdir(exist_ok=True)

            def paced_step(*step_args, **step_kwargs):
                started = time.monotonic()
                result = native_step(*step_args, **step_kwargs)
                if args.video:
                    frame[0] += 1
                    conn.gui.screenshot(view_id, str((frames / f'frame_{frame[0]:06d}.png').resolve()))
                time.sleep(max(0., env.dt / args.speed - (time.monotonic() - started)))
                return result
            conn.simulationStep = paced_step
            if args.overview:
                xmin, ymin, xmax, ymax = env.net.getBoundary()
                conn.gui.setBoundary(view_id, xmin, ymin, xmax, ymax)
            else:
                conn.gui.trackVehicle(view_id, env.ego_id)
                conn.gui.setZoom(view_id, args.zoom)
            colored = set()
            for t in range(601):
                current = set(conn.vehicle.getIDList())
                for vid in current - colored:
                    conn.vehicle.setColor(vid, AV_COLOR if vid == env.ego_id else HV_COLOR)
                colored = current
                obs, reward, term, trunc, step = env.step(model.predict(obs, deterministic=True))
                if t % 10 == 0:
                    state = step['next_state']
                    report(dict(phase='DRIVING', decision=t + 1,
                        episode_time_s=step['episode_time_s'], ego_speed_mps=state['ego_speed'],
                        ego_road=state['ego_road_id'], running_hv=state['traffic']['running_hv'],
                        detected_hv=len(env.get_detected_vehicles()), **info))
                if term or trunc:
                    info['episodes'].append(dict(ended_at=datetime.now().astimezone().isoformat(),
                                                 end_reason=step['end_reason'], episode_time_s=step['episode_time_s'],
                                                 frames=frame[0]))
                    break
            report(dict(phase='EPISODE_ENDED', **info))
            if args.once:
                break
            time.sleep(3.)
    except (KeyboardInterrupt, env.traci.exceptions.FatalTraCIError) as error:
        report(dict(phase='CLOSED', message=str(error), **info))
    finally:
        env.close()
    if args.video and frames.exists():
        # One frame per simulation tick; play back at --speed times real time.
        result = encode(frames, args.speed / args.demo_step, args.output / 'drive.mp4')
        atomic_json(args.output / 'VIDEO.json', dict(frames=len(list(frames.glob('frame_*.png'))),
                                                     seconds=len(list(frames.glob('frame_*.png'))) * args.demo_step / args.speed,
                                                     **result))
        print(result)


if __name__ == '__main__':
    main()
