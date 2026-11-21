"""Read-only localhost dashboard for the K-CITY experiment."""
import argparse
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNS = ROOT / "runs"
EXPERIMENT = ROOT / "configs/kcity/experiment.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def optional(folder, name):
    path = folder / name
    return read(path) if path.is_file() else {}


def rel(path):
    return path.relative_to(RUNS).as_posix()


def scan():
    data = dict(runs=[], evaluations=[], pools=[], demos=[], logs=[], warnings=[], spec=read(EXPERIMENT))
    trainers = {}
    folders = []
    for base, dirs, files in os.walk(RUNS):
        dirs[:] = sorted(d for d in dirs if d not in {
            "dataset", "shards", "checkpoints", "source_snapshot", "transitions", "__pycache__"
        } and not d.startswith("update-"))
        folder = Path(base)
        folders.append((folder, set(files)))
        data["logs"].extend(rel(folder / f) for f in sorted(files) if f.endswith(".log"))
    for folder, files in folders:
        try:
            if "CONFIG.json" in files:
                cfg = read(folder / "CONFIG.json")
                if cfg.get("kind", "").endswith(("_bc", "_rl")) or "curve.jsonl" in files:
                    complete = optional(folder, "COMPLETE.json")
                    curve = {}
                    for line in (folder / "curve.jsonl").read_text().splitlines() if "curve.jsonl" in files else []:
                        try:
                            row = json.loads(line)
                            curve[row.get("transitions", row.get("updates"))] = row
                        except ValueError:
                            data["warnings"].append(rel(folder) + " · 미완성 로그 행 제외")
                    run = dict(id=rel(folder), method=cfg.get("method") or "B1", seed=cfg.get("seed"),
                               config=cfg, complete=complete, status=optional(folder,"STATUS.json"),
                               best=optional(folder,"BEST.json"), curve=[curve[x] for x in sorted(curve)])
                    efficiency = optional(folder, "SAMPLE_EFFICIENCY.json")
                    run["efficiency"] = {k:v for k,v in efficiency.items() if k != "curve"}
                    trainers[folder] = run
                    data["runs"].append(run)
            if "POOL.json" in files:
                data["pools"].append(dict(id=rel(folder), **read(folder / "POOL.json")))
            if "STATUS.json" in files and "demo" in folder.relative_to(RUNS).parts:
                data["demos"].append(dict(id=rel(folder), **read(folder / "STATUS.json")))
        except (ValueError, OSError, TypeError) as exc:
            data["warnings"].append(f"{rel(folder)} · {exc}")
    for folder, files in folders:
        if not {"SUMMARY.json", "EPISODES.json"} <= files:
            continue
        try:
            summary = read(folder / "SUMMARY.json")
            episodes = read(folder / "EPISODES.json")
            ids = [ep.get("requested_case_uid") for ep in episodes]
            # Only skip demand exports that duplicate the parent's entire case set.
            if folder.name.startswith("demand_") and (folder.parent / "EPISODES.json").is_file():
                if episodes == read(folder.parent / "EPISODES.json"):
                    continue
            cfg = optional(folder, "CONFIG.json")
            policy = summary.get("policy", cfg.get("policy", {}))
            bundle = policy if isinstance(policy,str) else policy.get("bundle","")
            trainer = next((t for path,t in trainers.items() if path in folder.parents
                            or path in Path(bundle).resolve().parents), {})
            meta = policy if isinstance(policy,dict) else cfg.get("policy_metadata",{})
            method = trainer.get("method") or meta.get("config",{}).get("method")
            if meta.get("kind") == "expert" or policy == "expert":
                method = "B0"
            panel = summary.get("panel", episodes[0].get("namespace") if episodes else "unknown")
            step = summary.get("actual_transitions")
            cohort = hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest() if ids and all(ids) else rel(folder)
            detail = []
            for ep in episodes:
                lane = (ep.get("situations") or {}).get("lane_drop") or {}
                detail.append({**{k:ep.get(k) for k in ("case_index","scenario_id","demand_multiplier",
                    "attempt_valid","primary_end_reason","compliant_completion","ever_AV_collision","elapsed_s")},
                    "position":lane.get("position_m"),"wait":lane.get("wait_s")})
            data["evaluations"].append(dict(id=rel(folder), method=method or "기타", panel=panel,
                seed=summary.get("seed",trainer.get("seed",meta.get("config",{}).get("seed"))),
                run=trainer.get("id"), step=step, cohort=cohort, aggregate=summary["aggregate"],
                representative=step is None or step == trainer.get("complete",{}).get("transitions"),
                cases=detail, scenarios=dict(Counter(e["scenario_id"] for e in detail))))
        except (OSError,ValueError,TypeError,KeyError) as exc:
            data["warnings"].append(f"{rel(folder)} · {exc}")
    return data


@lru_cache(maxsize=1)
def map_svg():
    panel = read(ROOT / read(EXPERIMENT)["case_panels"]["dev"]["path"])
    routes = {c["scenario_id"]:c["scenario"]["route_edges"] for c in panel["cases"]}
    net = ET.parse(ROOT / "maps/kcity/kcity.net.xml")
    lines = {}
    for edge in net.findall("edge"):
        lane = edge.find("lane")
        if lane is not None and edge.get("function") != "internal":
            lines[edge.get("id")] = [tuple(map(float,p.split(","))) for p in lane.get("shape").split()]
    points = [p for line in lines.values() for p in line]
    x,y = zip(*points)
    view = f"{min(x)-20} {-max(y)-20} {max(x)-min(x)+40} {max(y)-min(y)+40}"
    def segment(key):
        return '<polyline points="' + ' '.join(f'{a:.1f},{-b:.1f}' for a,b in lines[key]) + '"/>'
    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" fill="none" stroke-linejoin="round"><g stroke="#648097" stroke-width="3">']
    chunks.extend(segment(k) for k in lines)
    chunks.append("</g>")
    for code,color in zip("ABC",["#80cded","#ffd07b","#d0b8ff"]):
        chunks.append(f'<g stroke="{color}" stroke-width="9">')
        chunks.extend(segment(k) for k in routes.get(code,[]) if k in lines)
        chunks.append("</g>")
    return ''.join(chunks)+'</svg>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path == "/api/results":
                body, mime = json.dumps(scan(), allow_nan=False).encode(), "application/json"
            elif url.path == "/map.svg":
                body, mime = map_svg().encode(), "image/svg+xml"
            elif url.path == "/api/log":
                name = parse_qs(url.query).get("file",[""])[0]
                path = (RUNS / name).resolve()
                if not path.is_relative_to(RUNS) or path.suffix != ".log" or not path.is_file():
                    return self.send_error(404)
                with path.open("rb") as f:
                    f.seek(max(0, path.stat().st_size-32768))
                    if f.tell():
                        f.readline()
                    body = f.read()
                mime = "text/plain; charset=utf-8"
            elif url.path in ("/","/style.css","/app.js"):
                name = url.path[1:] or "index.html"
                body = (HERE / "dist" / name).read_bytes()
                mime = {"index.html":"text/html; charset=utf-8","app.js":"text/javascript","style.css":"text/css"}[name]
            else:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError, KeyError) as exc:
            self.send_error(500,str(exc))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1",args.port), Handler) as server:
        print(f"http://localhost:{server.server_port}",flush=True)
        server.serve_forever()
