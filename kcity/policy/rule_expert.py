"""B0 rule expert: the source of the prior (demonstration) data. Deterministic and memoryless.

It sees exactly the 63-D observation the learned policies see; no SUMO handle, full State or route-lane
knowledge. It never acts while a learned policy drives. Rules:
  following      IDM-style gap keeping to the leader in the current lane (SUMO does not keep the gap)
  signal         stop for red; on yellow continue only if full braking cannot stop before the line
  blocked exit   do not enter a junction when the leader is stopped just beyond it
  lane drop      when the current lane ends, move to an adjacent lane once front/rear gaps are sufficient,
                 otherwise wait at the lane end
  yield          with a yield sign, stop at the junction entry while a vehicle from another approach is inside
                 or would arrive before the ego has cleared the junction
"""
from copy import deepcopy
import math
import numpy as np

from kcity.env.observation import (CONFLICT, CONFLICT_SLOTS, CURRENT, EXISTS, INSIDE, LANE_ENDS, LANE_LEFT, LEFT,
                                   OBS_DIM, RIGHT, SPEED, TLS_DIST, TLS_RED, TLS_YELLOW, VIA_LENGTH, YIELD_SIGN,
                                   corridor, lane_mask)

EXPERT_ID = 'KC-B0-OBS63-v1'
DEFAULT_EXPERT = dict(speed_cap_mps=8.33, cruise_mps=7.5, accel_mps2=2., decel_mps2=4.5,
                      following_decel_mps2=3., time_headway_s=1.5, min_gap_m=3.,
                      lane_front_gap_m=8., lane_rear_gap_m=8., lane_time_gap_s=1.5, stop_buffer_m=2.,
                      yield_margin_s=2.5, yield_min_speed_mps=3., vehicle_length_m=5., waiting_speed_mps=.5)


class KCityRuleExpert:
    def __init__(self, config=None):
        self.config = deepcopy(DEFAULT_EXPERT if config is None else config)
        if set(self.config) != set(DEFAULT_EXPERT) or any(not math.isfinite(v) or v <= 0 for v in self.config.values()):
            raise ValueError('Invalid expert configuration')

    def decision(self, observation):
        o = np.asarray(observation, dtype=np.float32)
        if o.shape != (OBS_DIM,) or not np.isfinite(o).all() or (np.abs(o) > 1).any():
            raise ValueError('Expert requires a bounded finite observation')
        c = self.config
        v = float(o[SPEED]) * c['speed_cap_mps']
        inside = bool(o[INSIDE] > .5)
        mask = lane_mask(o)
        requested, reasons = 0, []
        lane_ends = bool(o[LANE_ENDS] > .5) and not inside
        if lane_ends:
            for cmd, slot, category in [(1, LEFT, 0), (-1, RIGHT, 2)]:
                if o[EXISTS + slot] < .5 or not mask[category]:
                    continue
                front, _, rear, rear_rel = corridor(o, slot)
                rear_speed = max(0., v + rear_rel * c['speed_cap_mps'])
                front_ok = front is None or front >= max(c['lane_front_gap_m'], v * c['lane_time_gap_s'])
                rear_ok = rear is None or rear >= max(c['lane_rear_gap_m'], rear_speed * c['lane_time_gap_s'])
                if front_ok and rear_ok:
                    requested = cmd
                    reasons.append('lane_drop_merge')
                    break
        target = min(c['cruise_mps'], c['speed_cap_mps'])
        a = c['accel_mps2'] * (1 - (v / target) ** 4)
        leader_gap, leader_rel, _, _ = corridor(o, CURRENT)
        leader_speed = None
        if leader_gap is not None:
            leader_gap = max(.1, leader_gap)
            closing = -leader_rel * c['speed_cap_mps']
            leader_speed = max(0., v - closing)
            desired = c['min_gap_m'] + max(0., v * c['time_headway_s'] + v * closing /
                                           (2 * math.sqrt(c['accel_mps2'] * c['following_decel_mps2'])))
            a -= c['accel_mps2'] * (desired / leader_gap) ** 2
            # SUMO does not keep the gap: never approach faster than full braking can stop behind the leader.
            room = max(0., leader_gap - c['min_gap_m'])
            a = min(a, (math.sqrt(2 * c['decel_mps2'] * room) + leader_speed - v) / .5)
            reasons.append('following')
        stops = []
        entry = float(o[LANE_LEFT]) * 100  # distance to the end of the current lane (junction entry)
        if o[TLS_RED] > .5 or o[TLS_YELLOW] > .5:
            distance = float(o[TLS_DIST]) * 100
            committed = o[TLS_YELLOW] > .5 and v * v / (2 * c['decel_mps2']) > distance - .5
            if not inside and not committed:
                stops.append(max(0., distance - c['stop_buffer_m']))
                reasons.append('signal_stop')
        if (not inside and leader_gap is not None and leader_speed < 1.
                and entry < leader_gap < entry + float(o[VIA_LENGTH]) * 50 + c['vehicle_length_m'] + c['min_gap_m']):
            stops.append(max(0., entry - c['stop_buffer_m']))
            reasons.append('blocked_exit')
        if lane_ends and not requested:
            stops.append(max(0., entry - c['stop_buffer_m']))
            reasons.append('lane_end_wait')
        if o[YIELD_SIGN] > .5 and not inside:
            clear = (entry + float(o[VIA_LENGTH]) * 50 + c['vehicle_length_m']) / max(v, c['yield_min_speed_mps'])
            for k in range(CONFLICT_SLOTS):
                present, gap, speed, foe_inside = o[CONFLICT + 5 * k:CONFLICT + 5 * k + 4]
                if present < .5:
                    continue
                speed = float(speed) * c['speed_cap_mps']
                gap = float(gap) * 50
                # A vehicle standing on another approach is itself waiting and does not block the ego.
                arriving = speed > c['waiting_speed_mps'] and gap / speed < clear + c['yield_margin_s']
                if foe_inside > .5 or arriving:
                    stops.append(max(0., entry - c['stop_buffer_m']))
                    reasons.append('yield')
                    break
        for distance in stops:
            a = min(a, (math.sqrt(2 * c['following_decel_mps2'] * distance) - v) / .5)
        a = float(np.clip(a, -c['decel_mps2'], c['accel_mps2']))
        normalized = a / (c['accel_mps2'] if a >= 0 else c['decel_mps2'])
        return np.array([normalized, float(requested)], dtype=np.float32), dict(
            reasons=reasons, lane_mask=mask, requested_acceleration_mps2=a)

    def predict(self, observation, deterministic=True):
        return self.decision(observation)[0]
