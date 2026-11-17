"""Occurrence-aware K-CITY Lane corridors and route progress (no TraCI globals)."""
import math

from kcity.env.config import ContractError
from kcity.env.scenarios import internal_chain


class RouteGeometry:
    def __init__(self, net, scenario):
        self.net, self.scenario = net, scenario
        self.max_lanes=max(e.getLaneNumber() for e in net.getEdges()
            if e.getFunction()!='internal' and any(l.allows('passenger') for l in e.getLanes()))
        self.edges = scenario['route_edges']
        self.links, self.prefix = [], [0.0]
        for i, (a, b) in enumerate(zip(self.edges, self.edges[1:])):
            cs = [c for c in net.getEdge(a).getOutgoing().get(net.getEdge(b), [])
                  if c.allows('passenger')]
            if not cs:
                raise ContractError('No passenger route connection')
            opts = []
            for c in sorted(cs, key=lambda x:(x.getFromLane().getID(),x.getToLane().getID())):
                via = internal_chain(net, c)
                opts.append(dict(from_lane=c.getFromLane().getID(), to_lane=c.getToLane().getID(),
                    via=via, length=sum(net.getLane(v).getLength() for v in via),
                    tls=c.getTLSID(), link_index=c.getTLLinkIndex(), direction=c.getDirection(),
                    state=c.getState()))
            self.links.append(opts)
            self.prefix.append(self.prefix[-1] + net.getEdge(a).getLength() + min(x['length'] for x in opts))
        self.start_coordinate = scenario['start']['position_m'] * net.getEdge(self.edges[0]).getLength() / self.net.getEdge(self.edges[0]).getLane(scenario['start']['lane_index']).getLength()
        goal_lane = net.getEdge(self.edges[-1]).getLane(scenario['goal']['lane_index'])
        self.goal_coordinate = self.prefix[-1] + scenario['goal']['arrival_position_m'] * net.getEdge(self.edges[-1]).getLength() / goal_lane.getLength()
        self.total = self.goal_coordinate - self.start_coordinate
        if self.total <= 0:
            raise ContractError('Nonpositive finite route length')

    def locate(self, road_id, lane_id, lane_pos, route_index):
        """Canonical route coordinate; actual traveled distance is a separate field.

        Lane-specific lengths are mapped into a fixed route coordinate so a
        legal Lane change cannot create a jump at every Edge boundary.
        """
        if not road_id.startswith(':'):
            if not 0 <= route_index < len(self.edges) or self.edges[route_index] != road_id:
                raise ContractError('Vehicle left assigned route occurrence')
            lane = self.net.getLane(lane_id)
            coord = self.prefix[route_index] + lane_pos / lane.getLength() * self.net.getEdge(road_id).getLength()
            return coord - self.start_coordinate
        # SUMO route index is normally the entry edge; checking the preceding
        # occurrence also handles index advancement at an internal boundary.
        for idx in [route_index, route_index-1]:
            if not 0 <= idx < len(self.links):
                continue
            for opt in self.links[idx]:
                if lane_id in opt['via']:
                    start = sum(self.net.getLane(v).getLength() for v in opt['via'][:opt['via'].index(lane_id)])
                    fraction = (start + lane_pos) / max(opt['length'],1e-9)
                    nominal = min(o['length'] for o in self.links[idx])
                    coord = self.prefix[idx] + self.net.getEdge(self.edges[idx]).getLength() + fraction*nominal
                    return coord - self.start_coordinate
        raise ContractError('Unexpected internal Lane for route occurrence: '+lane_id)

    def _next(self, lane_id, occurrence):
        if not 0 <= occurrence < len(self.links):
            return None
        if lane_id.startswith(':'):
            for opt in self.links[occurrence]:
                if lane_id in opt['via']:
                    seq=opt['via']+[opt['to_lane']]
                    k=seq.index(lane_id)
                    return seq[k+1], occurrence+(k==len(opt['via'])-1)
        choices=[o for o in self.links[occurrence] if o['from_lane']==lane_id]
        if not choices:
            return None
        # Fixed, route-constrained tie breaking; no future traffic is consulted.
        opt=min(choices,key=lambda x:(x['to_lane'],x['via']))
        return (opt['via'][0] if opt['via'] else opt['to_lane']), occurrence+(not opt['via'])

    def corridor(self, lane_id, position, occurrence, front_range=100., rear_range=50.):
        """Lane segments (id,occurrence,start/end-relative coordinate).

        Includes predecessor lanes connected to this exact route, rather than
        comparing raw lanePos across unrelated Edges.
        """
        lane=self.net.getLane(lane_id)
        segments=[(lane_id,occurrence,-position,lane.getLength()-position)]
        current, index, distance = lane_id, occurrence, lane.getLength()-position
        visited={(lane_id,occurrence)}
        while distance < front_range:
            nxt=self._next(current,index)
            if nxt is None or nxt in visited:
                break
            current,index=nxt;visited.add(nxt)
            length=self.net.getLane(current).getLength()
            segments.append((current,index,distance,distance+length));distance+=length
        # Add all route-permitted predecessors: a merging rear neighbor must
        # not be discarded merely because there are several incoming Lanes.
        stack=[(lane_id,occurrence,-position,set())]
        while stack:
            current,index,end,seen=stack.pop()
            if end <= -rear_range:
                continue
            predecessors=[]
            for idx in [index,index-1]:
                if 0<=idx<len(self.links):
                    for opt in self.links[idx]:
                        seq=[opt['from_lane']]+opt['via']+[opt['to_lane']]
                        if current in seq[1:]:
                            prev=seq[seq.index(current)-1]
                            predecessors.append((prev,idx))
            for previous,idx in sorted(set(predecessors)):
                key=(previous,idx)
                if key in seen:
                    continue
                length=self.net.getLane(previous).getLength()
                segment=(previous,idx,end-length,end)
                if segment not in segments:segments.append(segment)
                stack.append((previous,idx,end-length,seen|{key}))
        return segments

    def lane_features(self, ego, vehicles, offset, front_range=100., rear_range=50.):
        lane=self.net.getLane(ego['lane_id']);edge=lane.getEdge()
        index=ego['lane']+offset
        if edge.getFunction()=='internal':
            if offset:return dict(exists=False)
            target=lane
        elif not 0<=index<edge.getLaneNumber() or not edge.getLane(index).allows('passenger'):
            return dict(exists=False)
        else:target=edge.getLane(index)
        # Adjacent Lane coordinate scales by Lane length, not a raw XY delta.
        pos=ego['lane_pos']/lane.getLength()*target.getLength()
        segments=self.corridor(target.getID(),pos,ego['route_index'],front_range,rear_range)
        front,rear=None,None
        counted=set();forward_count=0
        for vehicle in vehicles:
            if vehicle['id']==ego['id']:continue
            distances=[]
            for lid,_,start,end in segments:
                if vehicle['lane_id']==lid:
                    distance=start+vehicle['lane_pos']
                    if -rear_range<=distance<=front_range:distances.append(distance)
            if not distances:continue
            distance=min(distances,key=abs)
            if 0<distance<=front_range and vehicle['id'] not in counted:
                forward_count+=1;counted.add(vehicle['id'])
            gap=distance-vehicle['length_m'] if distance>=0 else -distance-ego['length_m']
            candidate=dict(gap=max(0.,gap),speed=vehicle['speed'],id=vehicle['id'],rel_pos=distance)
            if distance>=0:
                if front is None or (candidate['gap'],vehicle['id'])<(front['gap'],front['id']):front=candidate
            else:
                if rear is None or (candidate['gap'],vehicle['id'])<(rear['gap'],rear['id']):rear=candidate
        usable=min(front_range,max(s[3] for s in segments))
        connected=self._next(target.getID(),ego['route_index']) is not None
        return dict(exists=True,lane_id=target.getID(),front=front,rear=rear,
            connected=connected,density=min(1.,forward_count/max(usable/7.5,1.)),segments=segments)

    def next_rule(self, ego, stop_only=False):
        """Map-derived approach rule, distance measured through the fixed route."""
        current=self.locate(ego['road_id'],ego['lane_id'],ego['lane_pos'],ego['route_index'])
        for i in range(max(ego['route_index'],0),len(self.links)):
            edge=self.net.getEdge(self.edges[i]);kind=edge.getToNode().getType()
            boundary=self.prefix[i]+edge.getLength()-self.start_coordinate
            if boundary<current-1e-7:continue
            if (stop_only and kind=='allway_stop') or (not stop_only and kind in ['priority','allway_stop','right_before_left']):
                return max(0.,boundary-current)
        return None
