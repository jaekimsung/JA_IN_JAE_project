#!/usr/bin/env python3
"""Audit source coverage and render georeferenced map comparisons offline."""
import collections
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pyproj
from scipy.spatial import cKDTree

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 저장소 루트
from kcity.env.common import MAP, sumo_tools, write_json, write_xml

sumolib = sumo_tools()


def sample_polyline(points, spacing=0.5):
    result = []
    for a, b in zip(points, points[1:]):
        a, b = np.array(a[:2]), np.array(b[:2])
        count = max(1, int(np.ceil(np.linalg.norm(b - a) / spacing)))
        result.extend(a + (b - a) * i / count for i in range(count))
    if points:
        result.append(points[-1][:2])
    return result


def connector_audit(net_path, source_path, build):
    net = ET.parse(net_path).getroot()
    source = ET.parse(source_path).getroot()
    roads = {r.get("id"): r for r in source.findall("road")}
    lanes = {(e.get("id"), l.get("index")): l.find('param[@key="origId"]').get("value")
             for e in net.findall("edge") for l in e.findall("lane")
             if l.find('param[@key="origId"]') is not None}
    pairs = set()
    for c in net.findall("connection"):
        if c.get("from").startswith(":"):
            continue
        a = lanes.get((c.get("from"), c.get("fromLane")), "")
        b = lanes.get((c.get("to"), c.get("toLane")), "")
        pairs.update((x, y) for x in a.split() for y in b.split())
    records = []
    for rid in build["unrepresented_source_road_ids"]:
        road = roads[rid]
        pred, succ = road.find("link/predecessor"), road.find("link/successor")
        for lane in road.findall(".//lane"):
            if lane.get("id") == "0":
                continue
            lp, ls = lane.find("link/predecessor"), lane.find("link/successor")
            if any(x is None for x in [pred, succ, lp, ls]):
                records.append(dict(road_id=rid, status="source lane links incomplete"))
                continue
            a = pred.get("elementId") + "_" + lp.get("id")
            b = succ.get("elementId") + "_" + ls.get("id")
            if int(lane.get("id")) > 0:
                a, b = b, a
            records.append(dict(road_id=rid, junction_id=road.get("junction"),
                                length_m=float(road.get("length")), lane_type=lane.get("type"),
                                from_original_lane=a, to_original_lane=b,
                                same_lane_pair_present=(a, b) in pairs,
                                status="connection pair retained under another original ID" if (a, b) in pairs
                                else "not represented in imported network; direction/topology needs review"))
    base_ids = {r.get("id") for r in roads.values() if r.get("junction") == "-1"}
    return dict(source_nonjunction_roads=len(base_ids),
                intentionally_pruned_source_road_ids=build.get('intentionally_pruned_source_road_ids', []),
                intentionally_excluded_source_roads=build.get('intentionally_excluded_source_roads', {}),
                missing_nonjunction_roads=sorted(base_ids - set(build["represented_source_road_ids"])
                                                 - set(build.get('intentionally_excluded_source_roads', {}))),
                missing_original_id_count=len(records),
                equivalent_connection_count=sum(r.get("same_lane_pair_present", False) for r in records),
                unresolved=records)


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from PIL import Image

    out = MAP
    source = out / "source"
    build = json.loads((out / "reports" / "build.json").read_text())
    net = sumolib.net.readNet(str(out / "kcity.net.xml"), withInternal=True)
    projection = net.getGeoProj().srs
    geo_to_sumo = pyproj.Transformer.from_crs("EPSG:4326", projection, always_xy=True)
    info = json.loads((source / "mgeo_global_info.json").read_text())
    mgeo_to_sumo = pyproj.Transformer.from_crs(info["global_coordinate_system"], projection, always_xy=True)
    mgeo_lines = []
    mgeo_samples = []
    for link in json.loads((source / "mgeo_link_set.json").read_text()):
        points = np.asarray(link["points"])
        x, y = mgeo_to_sumo.transform(points[:, 0] + info["local_origin_in_global"][0],
                                      points[:, 1] + info["local_origin_in_global"][1])
        line = np.column_stack([x, y])
        mgeo_lines.append(line)
        mgeo_samples.extend(line[::4])
    regular_lines = [lane.getShape() for edge in net.getEdges(withInternal=False) for lane in edge.getLanes()]
    internal_lines = [lane.getShape() for edge in net.getEdges(withInternal=True)
                      if edge.getFunction() == "internal" for lane in edge.getLanes()]
    samples = np.asarray([point for line in regular_lines + internal_lines for point in sample_polyline(line)])
    distances = cKDTree(samples).query(np.asarray(mgeo_samples))[0]
    audit = connector_audit(out / "kcity.net.xml", source / "kcity.xodr", build)
    audit["mgeo_comparison"] = dict(
        method="MGeo link points sampled every fourth point; nearest SUMO polyline sample spaced <=0.5 m; no fitted alignment",
        samples=len(distances), median_distance_m=float(np.median(distances)),
        p90_distance_m=float(np.percentile(distances, 90)), p95_distance_m=float(np.percentile(distances, 95)),
        fraction_within_5m=float((distances <= 5).mean()),
        conclusion="different source extent/geometry or georeferencing; do not merge without alignment and edition evidence")
    image_meta = json.loads((source / "jj_kcity.json").read_text())
    extent = image_meta["extent"]
    left, bottom = geo_to_sumo.transform(extent["xmin"], extent["ymin"])
    right, top = geo_to_sumo.transform(extent["xmax"], extent["ymax"])
    gui = ET.Element('viewsettings')
    ET.SubElement(gui, 'scheme', name='real world')
    ET.SubElement(gui, 'delay', value='40')
    ET.SubElement(gui, "decal", filename="source/jj_kcity.jpg", centerX=str((left + right) / 2),
                  centerY=str((bottom + top) / 2), width=str(right - left), height=str(top - bottom),
                  altitude="0", rotation="0", tilt="0", roll="0", layer="-100")
    write_xml(out / "kcity.aerial.gui.xml", gui)
    trace_record = json.loads((source / "manifest.json").read_text())["excluded_jj_traces"]
    gnss = next(r for r in trace_record if "003556_gnss.csv" in r["path"])
    lat, lon = map(float, gnss["first_row"])
    tx, ty = geo_to_sumo.transform(lon, lat)
    audit["jj_gnss_exclusion"] = dict(first_latitude=lat, first_longitude=lon,
                                      first_projected_xy=[tx, ty], distance_from_map_origin_m=float(np.hypot(tx, ty)),
                                      reason="recorded outside K-City; metadata origin is not the recording location")
    audit["image_attribution"] = image_meta["attribution"]
    write_json(out / "reports" / "source_audit.json", audit)

    fig, axes = plt.subplots(1, 2, figsize=(12, 13), constrained_layout=True)
    for ax in axes:
        ax.set_aspect("equal")
        ax.set_xlabel("OpenDRIVE local east (m)")
        ax.set_ylabel("OpenDRIVE local north (m)")
    axes[0].set_facecolor("#eef3f7")
    axes[0].add_collection(LineCollection(regular_lines, colors="#24435b", linewidths=1.5))
    axes[0].add_collection(LineCollection(internal_lines, colors="#84a8be", linewidths=0.7))
    qlines = [net.getEdge(e).getShape() for e in build["qualifier"]["edges"]]
    axes[0].add_collection(LineCollection(qlines, colors="#d64c3c", linewidths=2.5, label="Qualifier edge route"))
    for signal in build["signals"]:
        node = net.getNode(signal["junction_id"])
        x, y = node.getCoord()
        axes[0].scatter([x], [y], c="#e9a50b", s=65, zorder=8)
        axes[0].annotate("Synthetic TLS " + node.getID(), (x, y), xytext=(10, 10),
                         textcoords="offset points", fontsize=8)
    for rb in net.getRoundabouts():
        coords = np.asarray([net.getNode(n).getCoord() for n in rb.getNodes()])
        axes[0].annotate("Roundabout", coords.mean(axis=0), xytext=(-70, 30),
                         textcoords="offset points", arrowprops=dict(arrowstyle="->"), fontsize=10)
    axes[0].set_xlim(-220, 230)
    axes[0].set_ylim(-570, 570)
    axes[0].set_title(f"SUMO K-City\n{build['regular_edges']} edges / {build['regular_lanes']} regular lanes")
    axes[0].legend(loc="lower left")
    axes[1].imshow(Image.open(source / "jj_kcity.jpg"), extent=(left, right, bottom, top), alpha=0.8)
    axes[1].add_collection(LineCollection(mgeo_lines, colors="#faaf40", linewidths=0.7, alpha=0.8, label="MGeo reference"))
    axes[1].add_collection(LineCollection(regular_lines, colors="#00b9ff", linewidths=1.0, label="SUMO / OpenDRIVE"))
    axes[1].set_xlim(-420, 270)
    axes[1].set_ylim(-800, 650)
    axes[1].set_title("JJ aerial image + source comparison\nMGeo topology is NOT stitched into this network")
    axes[1].legend(loc="lower left")
    fig.suptitle("K-CITY | imported road network and reference audit", fontsize=17, fontweight="bold")
    fig.supxlabel(image_meta["attribution"] + "\nGeographic corner placement; not a surveyed raster registration", fontsize=7)
    fig.savefig(out / "reports" / "overview.png", dpi=160)
    plt.close(fig)
    print(json.dumps(dict(mgeo=audit["mgeo_comparison"],
                          missing_source_roads=audit["missing_original_id_count"],
                          equivalent_connections=audit["equivalent_connection_count"]), indent=2))


if __name__ == "__main__":
    main()
