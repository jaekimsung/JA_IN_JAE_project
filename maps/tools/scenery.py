"""Deterministic decorative townscape; polygons never participate in traffic."""
import collections
import json
import math
from pathlib import Path
import random
import xml.etree.ElementTree as ET

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from kcity.env.common import MAP, sha256, write_json, write_xml


def points(text):
    return [tuple(map(float, p.split(',')[:2])) for p in text.split()]


def make_scenery(out=MAP):
    rng = random.Random(20261102)
    source = ET.parse(out / 'kcity.net.xml').getroot()
    surfaces, lines = [], []
    for filename in ['kcity.net.xml', 'kcity.reference.net.xml']:
        root = ET.parse(out / filename).getroot()
        for edge in root.findall('edge'):
            for lane in edge.findall('lane'):
                line = LineString(points(lane.get('shape')))
                width = float(lane.get('width', '3.5'))
                surfaces.append(line.buffer(width / 2 + .3))
                if filename == 'kcity.net.xml' and edge.get('function') != 'internal':
                    lines.append((line, width))
        for junction in root.findall('junction'):
            coords = points(junction.get('shape', ''))
            if len(coords) >= 3:
                poly = Polygon(coords).buffer(0)
                surfaces.append(poly)
    road = unary_union(surfaces)
    road_clear = road.buffer(3)
    tls_ids = {t.get('id') for t in source.findall('tlLogic')}
    signal_clear = unary_union([Point(float(j.get('x')), float(j.get('y'))).buffer(13)
                               for j in source.findall('junction') if j.get('id') in tls_ids])
    bounds = box(-230, -565, 225, 560)
    root = ET.Element('additional')
    count = collections.Counter()
    buildings, trees, park_shapes = [], [], []

    def poly(shape, kind, color, layer):
        if shape.is_empty:
            return
        if shape.geom_type != 'Polygon':
            for part in getattr(shape, 'geoms', []):
                poly(part, kind, color, layer)
            return
        # SUMO polygons have a single ring; do not fill across geometry holes.
        if shape.interiors:
            from shapely.ops import triangulate
            for triangle in triangulate(shape):
                if shape.covers(triangle):
                    poly(triangle, kind, color, layer)
            return
        count[kind] += 1
        ET.SubElement(root, 'poly', id=f'scenery_{kind}_{count[kind]:04d}', type='decorative.' + kind,
                      color=color, fill='true', layer=str(layer),
                      shape=' '.join(f'{x:.2f},{y:.2f}' for x, y in shape.exterior.coords))

    poly(bounds, 'ground', '#e8eddf', -1000)
    for line, width in lines:
        poly(line.buffer(width/2 + 1.5, quad_segs=3), 'paving', '#d1d5cd', -500)
    for j in source.findall('junction'):
        coords = points(j.get('shape', ''))
        if len(coords) >= 3:
            poly(Polygon(coords).buffer(.8), 'paving', '#d1d5cd', -500)

    # Landscaped open spaces and test-campus green belts; invented, not surveyed.
    for x, y, rx, ry in [(-90, 275, 36, 65), (2, 440, 36, 47), (-40, 260, 22, 55),
                         (-45, -155, 35, 65), (-130, -330, 31, 68), (20, -430, 39, 53),
                         (-190, 115, 24, 82), (195, 265, 17, 170), (-170, 435, 22, 65),
                         (185, -400, 20, 93)]:
        park = affinity.scale(Point(x, y).buffer(1, quad_segs=20), rx, ry).difference(road.buffer(4))
        park_shapes.append(park)
        poly(park, 'lawn', rng.choice(['#cedfbf', '#d6e4c8', '#c9dcb9']), -700)
        path = LineString([(x-8, y-ry*.65), (x+6, y), (x-3, y+ry*.65)]).buffer(1.1)
        poly(path.intersection(park), 'park_path', '#e7deca', -650)

    roofs = ['#b6c7d0', '#d9cab7', '#b9c2c5', '#c7c9b7', '#d1bdb1']
    candidates = []
    # Smaller urban blocks, larger west-side research campus buildings.
    for x in range(-135, 136, 26):
        for y in range(-380, 170, 34):
            candidates.append((x+rng.uniform(-3, 3), y+rng.uniform(-3, 3),
                               rng.uniform(12, 20), rng.uniform(17, 27), 0))
    for x, y in [(-195, -190), (-195, -245), (-195, -300), (-195, -355),
                  (-195, 330), (-195, 380), (-75, 435), (-35, 450), (35, 315), (63, 285)]:
        candidates.append((x, y, 23, 34, 0))
    rng.shuffle(candidates)
    for x, y, w, h, angle in candidates:
        footprint = affinity.rotate(box(x-w/2, y-h/2, x+w/2, y+h/2), angle)
        pad = footprint.buffer(3.8, join_style=2)
        if not bounds.contains(pad) or pad.intersects(road_clear) or pad.intersects(signal_clear):
            continue
        if any(pad.intersects(other.buffer(5)) for other in buildings):
            continue
        if any(park.intersects(pad) for park in park_shapes):
            continue
        buildings.append(footprint)
        poly(pad, 'building_plot', '#e0dfd5', -450)
        poly(affinity.translate(footprint, 1.7, -1.7), 'building_shadow', '#adb5aa', -390)
        poly(footprint, 'building_wall', '#8d9a9f', -380)
        roof = footprint.buffer(-.8, join_style=2)
        poly(roof, 'building_roof', rng.choice(roofs), -370)
        # Roof ridge, skylights and equipment give readable detail when zooming.
        poly(box(x-w*.30, y-1, x+w*.30, y+1), 'roof_ridge', '#dce3e1', -360)
        for yy in [y-h*.24, y+h*.24]:
            poly(box(x-w*.25, yy-1.1, x-w*.05, yy+1.1), 'skylight', '#7696a3', -350)
        poly(box(x+w*.18, y-h*.30, x+w*.34, y-h*.12), 'roof_equipment', '#e7e8e2', -350)

    occupied = unary_union([b.buffer(3) for b in buildings] + [road_clear, signal_clear])

    def tree(x, y, radius):
        crown = Point(x, y).buffer(radius, quad_segs=7)
        if not bounds.contains(crown) or crown.intersects(occupied):
            return
        if any(math.dist((x, y), (a, b)) < radius + r + 1.6 for a, b, r in trees):
            return
        trees.append((x, y, radius))
        poly(affinity.translate(crown, .7, -.9), 'tree_shadow', '#a6b79a', -330)
        poly(crown, 'tree_crown', rng.choice(['#699661', '#76a26c', '#59885c', '#86aa71']), -320)
        poly(Point(x-.45, y+.45).buffer(radius*.62, quad_segs=6), 'tree_highlight', '#93b681', -310)

    for line, width in lines:
        for distance in range(8, int(line.length)-5, 16):
            point = line.interpolate(distance)
            a, b = line.interpolate(distance-.5), line.interpolate(distance+.5)
            length = a.distance(b)
            if length < .01:
                continue
            nx, ny = -(b.y-a.y)/length, (b.x-a.x)/length
            for side in [-1, 1]:
                offset = width/2 + 6.3
                tree(point.x+side*nx*offset, point.y+side*ny*offset, rng.uniform(2.1, 2.8))
    for park in park_shapes:
        x0, y0, x1, y1 = park.bounds
        for _ in range(65):
            x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
            if park.contains(Point(x, y).buffer(3.2)):
                tree(x, y, rng.uniform(2.2, 3.1))
    # Explicit geometric QA of all tall decorative objects.
    assert all(b.distance(road) >= 3 for b in buildings)
    assert all(Point(x, y).buffer(r).distance(road) >= 2.9 for x, y, r in trees)
    write_xml(out / 'kcity.scenery.add.xml', root)
    gui = ET.Element('viewsettings')
    scheme = ET.SubElement(gui, 'scheme', name='K-CITY landscaped')
    ET.SubElement(scheme, 'background', backgroundColor='#e8eddf', showGrid='0')
    edges = ET.SubElement(scheme, 'edges', laneEdgeMode='0', laneShowBorders='1',
                          showLinkDecals='1', showLinkRules='1', hideConnectors='0',
                          widthExaggeration='1', minSize='0')
    colors = ET.SubElement(edges, 'colorScheme', name='uniform')
    ET.SubElement(colors, 'entry', color='#4c5962', name='road')
    junctions = ET.SubElement(scheme, 'junctions', junctionMode='0', drawShape='1')
    palette = ET.SubElement(junctions, 'colorScheme', name='uniform')
    ET.SubElement(palette, 'entry', color='#4c5962')
    ET.SubElement(scheme, 'polys', poly_minSize='0', poly_exaggeration='1',
                  polyName_show='0', polyType_show='0')
    ET.SubElement(gui, 'delay', value='40')
    write_xml(out / 'kcity.gui.xml', gui)
    for filename in ['kcity.sumocfg', 'kcity.reference.sumocfg']:
        cfg = ET.parse(out / filename).getroot()
        element = cfg.find('input/additional-files')
        files = [f for f in element.get('value').split(',') if f != 'kcity.scenery.add.xml']
        element.set('value', ','.join(files + ['kcity.scenery.add.xml']))
        write_xml(out / filename, cfg)
    report = dict(seed=20261102, buildings=len(buildings), trees=len(trees), parks=len(park_shapes),
                  polygons=len(root), counts=dict(count),
                  road_clearance_m=3, signal_clearance_m=13,
                  source='procedural decorative placement; not actual K-CITY building or tree locations',
                  network_sha256=sha256(out / 'kcity.net.xml'),
                  scenery_sha256=sha256(out / 'kcity.scenery.add.xml'),
                  traffic_effect='SUMO drawing polygons only; no collision objects, routes or lane changes')
    write_json(out / 'reports/scenery.json', report)
    print(f"Scenery: {len(buildings)} buildings, {len(trees)} trees, {len(park_shapes)} landscaped spaces")
    return report


if __name__ == '__main__':
    make_scenery()
