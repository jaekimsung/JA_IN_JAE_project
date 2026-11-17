"""62-D policy observation (KC-OBS62-v1) and detected-vehicle list, built from a privileged SUMO snapshot.

Only what a driver can perceive or read from a route-level map: surrounding vehicles, lanes that exist,
signals, the next turn and road signs. No lane-level route guidance (which lane continues the route) and
no right-of-way decision: those must be learned from reward.

    0        SPEED          ego speed / 8.33
    1-20     CORRIDOR       five lanes (left2, left1, current, right1, right2) x [front gap/100 m, front relative
                            speed, -rear gap/50 m, rear relative speed]; no vehicle = (1, 0, -1, 0)
    21-25    EXISTS         lane exists (1) or not (0)
    26-30    DENSITY        vehicles per 7.5 m within 100 m ahead in that lane
    31       LANE_INDEX     current lane index / (max lanes - 1); 0 inside a junction
    32       ROUTE_LEFT     remaining route distance / 300 m
    33       LANE_LEFT      remaining length of the current lane / 100 m (distance to the next junction)
    34       ACCEL          current acceleration / limit
    35       INSIDE         inside a junction
    36       COOLDOWN       lane-change cooldown remaining (s)
    37       TIME_LEFT      remaining episode time / limit
    38       TLS_DIST       distance to the next signal / 100 m (1 when none within 100 m)
    39-41    TLS_STATE      next signal red / yellow / green, one dimension each (all 0 when none)
    42-44    TURN           next route connection turns left / straight / right
    45       YIELD_SIGN     the next junction is unsignalized and the ego's approach is the minor road
    46       VIA_LENGTH     path length through the next junction / 50 m
    47-61    CONFLICT       three vehicles approaching or inside the next junction from other approaches,
                            nearest first: presence, distance to the junction / 50 m, speed / 8.33,
                            inside the junction, bearing from the ego heading / 180 deg
    62       LANE_ENDS      the current lane physically ends (no connection onward, a lane-drop marking);
                            route-independent road structure
"""
import math
import numpy as np

OBSERVATION_ID = 'KC-OBS63-v1'
OBS_DIM = 63
OFFSETS = (2, 1, 0, -1, -2)
SPEED, CORRIDOR, EXISTS, DENSITY = 0, 1, 21, 26
LANE_INDEX, ROUTE_LEFT, LANE_LEFT, ACCEL, INSIDE, COOLDOWN, TIME_LEFT = 31, 32, 33, 34, 35, 36, 37
TLS_DIST, TLS_RED, TLS_YELLOW, TLS_GREEN = 38, 39, 40, 41
TURN, YIELD_SIGN, VIA_LENGTH, CONFLICT, LANE_ENDS = 42, 45, 46, 47, 62
CONFLICT_SLOTS = 3
CONFLICT_RANGE_M = 50.
BINARY = [*range(EXISTS, EXISTS + 5), INSIDE, TLS_RED, TLS_YELLOW, TLS_GREEN, *range(TURN, TURN + 3), YIELD_SIGN,
          *[CONFLICT + 5 * k + j for k in range(CONFLICT_SLOTS) for j in (0, 3)], LANE_ENDS]
CURRENT, LEFT, RIGHT = 2, 1, 3  # corridor slots


def corridor(obs, slot):
    """(front gap m or None, front rel speed, rear gap m or None, rear rel speed) of one corridor slot."""
    base = CORRIDOR + 4 * slot
    front, rear = float(obs[base]), float(obs[base + 2])
    return (front * 100 if front < 1 else None, float(obs[base + 1]),
            -rear * 50 if rear > -1 else None, float(obs[base + 3]))


def lane_mask(obs):
    """[left, keep, right] lane requests the environment can execute (lane exists, not in a junction, no cooldown)."""
    free = obs[INSIDE] < .5 and obs[COOLDOWN] <= 1e-9
    return [bool(free and obs[EXISTS + LEFT] > .5), True, bool(free and obs[EXISTS + RIGHT] > .5)]


def next_link(geometry, ego):
    """(route occurrence, chosen connection) of the junction the ego is approaching or inside."""
    index = ego['route_index']
    if ego['road_id'].startswith(':'):
        index = next((i for i in [index, index - 1] if 0 <= i < len(geometry.links)
                      and any(ego['lane_id'] in o['via'] for o in geometry.links[i])), None)
    if index is None or not 0 <= index < len(geometry.links):
        return None, None
    options = geometry.links[index]
    chosen = ([o for o in options if o['from_lane'] == ego['lane_id'] or ego['lane_id'] in o['via']] or options)[0]
    return index, chosen


def junction_vehicles(geometry, link, vehicles, ego_id, lanes_key):
    """(distance to junction, id, vehicle, inside) for vehicles on `link[lanes_key]`, nearest first.

    `lanes_key` maps lane -> distance from its end to the junction (None = inside the junction).
    'approach_lanes' are all other approaches (perception); 'priority_lanes' those with right of way (judging).
    """
    found = []
    lanes = link[lanes_key]
    for v in vehicles:
        if v['id'] == ego_id or v['lane_id'] not in lanes:
            continue
        offset = lanes[v['lane_id']]
        if offset is None:
            found.append((0., v['id'], v, True))
        else:
            gap = offset + geometry.net.getLane(v['lane_id']).getLength() - v['lane_pos']
            if gap <= CONFLICT_RANGE_M:
                found.append((gap, v['id'], v, False))
    return sorted(found, key=lambda f: f[:2])


def build_observation(geometry, ego, vehicles, next_tls, remaining_s, horizon_s, cooldown_s, speed_cap=8.33):
    """(observation, detected vehicles, lane mask)."""
    if ego is None:
        return np.zeros(OBS_DIM, dtype=np.float32), [], [False, True, False]
    blocks = [geometry.lane_features(ego, vehicles, o) for o in OFFSETS]
    obs = np.zeros(OBS_DIM, dtype=np.float32)
    obs[SPEED] = ego['speed'] / speed_cap
    for k, block in enumerate(blocks):
        obs[CORRIDOR + 4 * k:CORRIDOR + 4 * k + 4] = [1, 0, -1, 0]
        if not block['exists']:
            continue
        obs[EXISTS + k] = 1
        obs[DENSITY + k] = block['density']
        if block['front'] is not None:
            obs[CORRIDOR + 4 * k] = block['front']['gap'] / 100
            obs[CORRIDOR + 4 * k + 1] = (block['front']['speed'] - ego['speed']) / speed_cap
        if block['rear'] is not None:
            obs[CORRIDOR + 4 * k + 2] = -block['rear']['gap'] / 50
            obs[CORRIDOR + 4 * k + 3] = (block['rear']['speed'] - ego['speed']) / speed_cap
    internal = ego['road_id'].startswith(':')
    progress = geometry.locate(ego['road_id'], ego['lane_id'], ego['lane_pos'], ego['route_index'])
    obs[LANE_INDEX] = 0 if internal else ego['lane'] / max(1, geometry.max_lanes - 1)
    obs[ROUTE_LEFT] = max(0., geometry.total - progress) / 300
    obs[LANE_LEFT] = (geometry.net.getLane(ego['lane_id']).getLength() - ego['lane_pos']) / 100
    obs[ACCEL] = ego['accel_mps2'] / (2 if ego['accel_mps2'] >= 0 else 4.5)
    obs[INSIDE] = internal
    obs[LANE_ENDS] = not internal and not geometry.net.getLane(ego['lane_id']).getOutgoing()
    obs[COOLDOWN] = cooldown_s
    obs[TIME_LEFT] = max(0., remaining_s) / horizon_s
    obs[TLS_DIST] = 1
    near = [t for t in next_tls if 0 <= t[2] <= 100]
    if near:
        _, _, distance, state = near[0]
        if state not in 'ryYGgoOs':
            raise ValueError('Unmapped TLS state: ' + state)
        column = {'r': TLS_RED, 'y': TLS_YELLOW, 'Y': TLS_YELLOW, 'G': TLS_GREEN, 'g': TLS_GREEN}.get(state)
        if column is not None:  # a dark ('o') signal reads as no signal
            obs[TLS_DIST] = distance / 100
            obs[column] = 1
    slots = []
    index, link = next_link(geometry, ego)
    if link is not None:
        category = {'l': 0, 's': 1, 'r': 2}.get(link['direction'].lower())
        if category is not None:
            obs[TURN + category] = 1
        obs[YIELD_SIGN] = bool(not link['tls'] and link['state'] in 'msw')
        obs[VIA_LENGTH] = link['length'] / 50
        if internal or obs[LANE_LEFT] * 100 <= CONFLICT_RANGE_M:
            slots = junction_vehicles(geometry, link, vehicles, ego['id'], 'approach_lanes')[:CONFLICT_SLOTS]
            for k, (gap, _, v, inside) in enumerate(slots):
                bearing = math.degrees(math.atan2(v['x'] - ego['x'], v['y'] - ego['y'])) - ego['angle_deg']
                obs[CONFLICT + 5 * k:CONFLICT + 5 * k + 5] = [1, gap / CONFLICT_RANGE_M, v['speed'] / speed_cap,
                                                              inside, ((bearing + 180) % 360 - 180) / 180]
    mask = lane_mask(obs)
    slotted = {s[1] for s in slots}
    detected = []
    for v in vehicles:
        if v['id'] == ego['id']:
            continue
        projections = []
        in_slot = v['id'] in slotted
        for offset, block in zip(OFFSETS, blocks):
            if not block['exists']:
                continue
            for lid, _, start, _ in block['segments']:
                if v['lane_id'] == lid:
                    rel = start + v['lane_pos']
                    if -50 <= rel <= 100:
                        projections.append((abs(rel), offset, rel))
            in_slot |= any(block[k] and block[k]['id'] == v['id'] for k in ['front', 'rear'])
        if projections:
            _, offset, rel = min(projections)
            relation = 'same_corridor' if offset == 0 else 'adjacent_corridor'
            projected = True
        else:
            edge = geometry.net.getLane(ego['lane_id']).getEdge()
            other = geometry.net.getLane(v['lane_id']).getEdge()
            shared = edge.getToNode() in [other.getFromNode(), other.getToNode()]
            if not (shared or v['id'] in slotted) or math.hypot(v['x'] - ego['x'], v['y'] - ego['y']) > 100:
                continue
            offset = rel = None
            relation, projected = 'crossing', False
        detected.append(dict(id=v['id'], x=v['x'], y=v['y'], rel_pos=rel, speed=v['speed'],
                             lane_offset=offset, edge_id=v['road_id'], lane_id=v['lane_id'],
                             accel_mps2=v['accel_mps2'], rel_speed_mps=v['speed'] - ego['speed'],
                             relation=relation, projection_valid=projected, in_policy_slot=in_slot))
    detected.sort(key=lambda x: (abs(x['rel_pos']) if x['rel_pos'] is not None else math.inf, x['id']))
    obs = np.clip(obs, -1, 1)
    if obs.shape != (OBS_DIM,) or not np.isfinite(obs).all():
        raise ValueError('Invalid policy observation')
    return obs, detected, mask
