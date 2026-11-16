"""View a trained KC-06 checkpoint in SUMO GUI. Inference only, no learning."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import xml.etree.ElementTree as ET

import torch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from kcity.training import KCityPPO,read_bundle
from kcity.env.env import SumoKCityEnv
from kcity.env.config import file_sha256
from kcity.data.dataset import atomic_json


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--checkpoint',type=Path,required=True)
    ap.add_argument('--scenario',choices=['A','B','C'],default='C')
    ap.add_argument('--case-index',type=int,default=1000000)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--speed',type=float,default=2.5)
    ap.add_argument('--demand-multiplier',type=float,default=1.)
    ap.add_argument('--warmup',type=float,default=60.)
    ap.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    ap.add_argument('--demo-step',type=float,choices=[.1,.02],default=.1)
    ap.add_argument('--zoom',type=float,default=500.)
    ap.add_argument('--overview',action='store_true')
    ap.add_argument('--once',action='store_true')
    args=ap.parse_args()
    if args.speed<=0 or args.demand_multiplier<=0 or args.warmup<0:ap.error('Invalid speed/demand/warmup')
    torch.set_num_threads(1);args.output.mkdir(parents=True,exist_ok=False)
    meta=json.loads((args.checkpoint/'metadata.json').read_text())
    payload=read_bundle(args.checkpoint,meta['kind'],meta['config'])
    model=KCityPPO(meta['config']['policy'],seed=11,device=args.device)
    model.policy.load_state_dict(payload['agent']['policy'],strict=True);model.policy.eval()
    view=ET.parse(ROOT/'maps/kcity/kcity.gui.xml')
    for scheme in view.getroot().findall('scheme'):
        vehicles=ET.SubElement(scheme,'vehicles')
        vehicles.set('vehicleMode','0');vehicles.set('vehicle_exaggeration','1');vehicles.set('vehicle_minSize','1')
        vehicles.set('vehicleQuality','2')
    view.write(args.output/'view.xml',encoding='utf-8',xml_declaration=True)
    env=SumoKCityEnv(gui=True,background=True,scenario_id=args.scenario,debug_warmup_s=args.warmup)
    # Explicit presentation dynamics variant; never alter pinned on-disk configs.
    env.contract['protocol']['timing']['sumo_step_s']=args.demo_step
    env.contract['protocol']['timing']['substeps']=round(.5/args.demo_step)
    original_start=env.traci.start
    def gui_start(cmd,**kwargs):
        cmd=list(cmd);idx=cmd.index('-a')+1
        cmd[idx]+=','+str(ROOT/'maps/kcity/kcity.add.xml')+','+str(ROOT/'maps/kcity/kcity.scenery.add.xml')
        cmd+=['--gui-settings-file',str((args.output/'view.xml').resolve()),'--delay','0',
              '--window-size','1600,950','--window-pos','40,40']
        return original_start(cmd,**kwargs)
    info=dict(checkpoint=str(args.checkpoint.resolve()),checkpoint_sha256=file_sha256(args.checkpoint/'SHA256.json'),
        scenario=args.scenario,namespace='dev',case_index=args.case_index,learning_updates=0,
        display_speed=args.speed,demand_multiplier=args.demand_multiplier,warmup_s=args.warmup,
        demo_physics_tick_s=args.demo_step,original_evaluation_tick_s=.1,policy_decision_period_s=.5,
        variant='interactive traffic demonstration; not original evaluation',
        policy='deterministic trained actor; normal SUMO safety',visual_only='scenery,colors,camera,time pacing',episodes=[])
    atomic_json(args.output/'STATUS.json',dict(phase='STARTING_GUI',**info))
    try:
        while True:
            with patch.object(env.traci,'start',side_effect=gui_start):
                obs,reset=env.reset(options=dict(namespace='dev',scenario_id=args.scenario,case_index=args.case_index,demand_multiplier=args.demand_multiplier))
            conn=env.conn;view_id=conn.gui.getIDList()[0];conn.gui.setAngle(view_id,90.)
            # Per-tick display pacing; native GUI delay is zero to avoid double waits. No
            # catch-up bursts or pauses at the0.5s policy decision boundary.
            native_step=conn.simulationStep;rendered_at=[]
            def observed_step(*step_args,**step_kwargs):
                started=time.monotonic()
                result=native_step(*step_args,**step_kwargs)
                time.sleep(max(0.,env.dt/args.speed-(time.monotonic()-started)))
                if len(rendered_at)<101:
                    rendered_at.append(time.monotonic())
                    if len(rendered_at)==101:
                        gaps=[b-a for a,b in zip(rendered_at,rendered_at[1:])]
                        atomic_json(args.output/'PACING.json',dict(native_tick_s=env.dt,
                            policy_period_s=.5,speed=args.speed,samples=len(gaps),
                            pacing='per-tick minimum interval,no catch-up,native GUI delay0',target_gui_delay_ms=0,
                            target_wall_interval_s=env.dt/args.speed,
                            mean_wall_interval_s=sum(gaps)/len(gaps),
                            min_wall_interval_s=min(gaps),max_wall_interval_s=max(gaps)))
                return result
            conn.simulationStep=observed_step
            if args.overview:
                xmin,ymin,xmax,ymax=env.net.getBoundary();conn.gui.setBoundary(view_id,xmin,ymin,xmax,ymax)
            else:
                conn.gui.trackVehicle(view_id,env.ego_id);conn.gui.setZoom(view_id,args.zoom)
            for vid in conn.vehicle.getIDList():conn.vehicle.setColor(vid,(255,30,30,255) if vid==env.ego_id else (255,215,0,255))
            atomic_json(args.output/'STATUS.json',dict(phase='DRIVING',tracked=conn.gui.getTrackedVehicle(view_id),
                sim_time_s=conn.simulation.getTime(),running_npc=reset['state']['traffic']['running_hv'],**info))
            conn.gui.screenshot(view_id,str((args.output/'driving.png').resolve()))
            colored=set(conn.vehicle.getIDList())
            for t in range(601):
                action=model.predict(obs,deterministic=True)
                obs,reward,term,trunc,step=env.step(action)
                current=set(conn.vehicle.getIDList())
                for vid in current-colored:conn.vehicle.setColor(vid,(255,30,30,255) if vid==env.ego_id else (255,215,0,255))
                colored=current
                if t==20:conn.gui.screenshot(view_id,str((args.output/'interaction.png').resolve()))
                if t%10==0:
                    atomic_json(args.output/'STATUS.json',dict(phase='DRIVING',decision=t+1,
                        episode_time_s=step['episode_time_s'],ego_speed_mps=step['next_state']['ego_speed'],
                        ego_road=step['next_state']['ego_road_id'],tracked=conn.gui.getTrackedVehicle(view_id),
                        running_npc=step['next_state']['traffic']['running_hv'],
                        detected_npc=len(env.get_detected_vehicles()),
                        closest_npc_m=min(( ((v['x']-step['next_state']['ego_x'])**2+(v['y']-step['next_state']['ego_y'])**2)**.5
                            for v in step['next_state']['vehicles'] if not v['is_ego']),default=None) if step['next_state']['ego_alive'] else None,**info))
                if term or trunc:
                    info['episodes'].append(dict(ended_at=datetime.now().astimezone().isoformat(),
                        end_reason=step['end_reason'],episode_time_s=step['episode_time_s']))
                    atomic_json(args.output/'STATUS.json',dict(phase='EPISODE_ENDED',**info));break
            if args.once:break
            time.sleep(3.)
    except (KeyboardInterrupt,env.traci.exceptions.FatalTraCIError) as error:
        atomic_json(args.output/'STATUS.json',dict(phase='CLOSED',message=str(error),**info))
    finally:env.close()


if __name__=='__main__':main()
