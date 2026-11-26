"""Local experiment dashboard and SUMO demo launcher."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNS = ROOT / "runs"
MAIN = RUNS / "dense_v2_1_main"
EXPERIMENT = ROOT / "configs/kcity/v2_1/experiment.json"
DEMO_CASE = {"A": 1000, "B": 1005, "C": 1004, "ABC": 1000, "BAC": 1005}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def has_content(path):
    return path.is_file() and path.stat().st_size > 0


def optional(folder, name):
    path = folder / name
    return read(path) if has_content(path) else {}


def rel(path):
    return path.relative_to(RUNS).as_posix()


def demo_bundle(folder, cfg, best, complete):
    if cfg.get("kind") == "main_bc":
        target = best.get("path")
        bundle = folder / target if target else None
    elif cfg.get("kind") == "main_rl":
        target = complete.get("checkpoint")
        # COMPLETE may have been created in another checkout.
        bundle = folder / "transitions/checkpoints" / Path(target).name if target else None
    else:
        return None
    if bundle and bundle.resolve().is_relative_to(folder.resolve()) and all(
        has_content(bundle / f) for f in ("training.pt", "metadata.json", "SHA256.json")
    ):
        return bundle
    return None


def legacy_demo_models():
    models = []
    for name in ("bc_main_seed11", "B2_seed11", "B3_seed11"):
        folder = RUNS / name
        cfg = optional(folder, "CONFIG.json")
        if cfg.get("seed") == 11 and demo_bundle(folder, cfg, optional(folder, "BEST.json"), optional(folder, "COMPLETE.json")):
            models.append(dict(id=name, method=cfg.get("method") or "B1", seed=11, training="v1"))
    return models


def scan():
    data = dict(runs=[], evaluations=[], pools=[], demos=[], logs=[], warnings=[], spec=read(EXPERIMENT))
    spec = data["spec"]
    experiment_hash = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=False).encode()).hexdigest()
    panel_ids = {name: {row["case_uid"] for row in read(ROOT / ref["path"])["cases"]}
                 for name, ref in spec["case_panels"].items()}
    trainers = {}
    legacy_trainers = {}
    for model in legacy_demo_models():
        folder = RUNS / model["id"]
        bundle = demo_bundle(folder, optional(folder, "CONFIG.json"),
                             optional(folder, "BEST.json"), optional(folder, "COMPLETE.json"))
        legacy_trainers[bundle.resolve()] = dict(id=model["id"], method=model["method"],
                                                 seed=model["seed"], training="v1",
                                                 complete=optional(folder, "COMPLETE.json"))
    folders = []
    empty_model_configs = []
    for base, dirs, files in os.walk(RUNS):
        if Path(base) == RUNS:
            dirs[:] = [d for d in dirs if d in (MAIN.name, "eval")]
        elif Path(base) == MAIN:
            # Publication staging and worktrees contain copies of the training runs.
            dirs[:] = [d for d in dirs if d not in ("publication_stage", "publication_worktrees")]
        dirs[:] = sorted(d for d in dirs if d not in {
            "dataset", "shards", "checkpoints", "source_snapshot", "transitions", "__pycache__"
        } and not d.startswith("update-"))
        folder = Path(base)
        present = {name for name in files if name.endswith((".json", ".log")) and has_content(folder / name)}
        if (folder.parent == MAIN and folder.name.split("_seed")[0] in spec["methods"]
                and "CONFIG.json" in files and "CONFIG.json" not in present):
            empty_model_configs.append(folder.name)
        folders.append((folder, present | ({"curve.jsonl"} if "curve.jsonl" in files else set())))
        if folder.is_relative_to(MAIN):
            data["logs"].extend(rel(folder / f) for f in sorted(present) if f.endswith(".log"))
    if empty_model_configs:
        data["warnings"].append("모델 설정 파일이 비어 있습니다 (0바이트) · " + ", ".join(empty_model_configs))
    for folder, files in folders:
        try:
            if "CONFIG.json" in files:
                cfg = read(folder / "CONFIG.json")
                if (cfg.get("kind") in ("main_bc", "main_rl") and cfg.get("seed") in spec["seeds"]
                        and cfg.get("experiment_sha256") == experiment_hash):
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
                    run["demo_available"] = demo_bundle(folder, cfg, run["best"], complete) is not None
                    trainers[folder] = run
                    data["runs"].append(run)
            if "POOL.json" in files and optional(folder, "CONFIG.json").get("experiment_sha256") == experiment_hash:
                data["pools"].append(dict(id=rel(folder), **read(folder / "POOL.json")))
            if "STATUS.json" in files and (MAIN / "demo") in folder.parents:
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
            if not trainer and bundle:
                trainer = legacy_trainers.get(Path(bundle).resolve(), {})
            meta = policy if isinstance(policy,dict) else cfg.get("policy_metadata",{})
            method = trainer.get("method") or meta.get("config",{}).get("method")
            if meta.get("kind") == "expert" or policy == "expert":
                method = "B0"
            panel = summary.get("panel", episodes[0].get("namespace") if episodes else "unknown")
            if not ids or not set(ids) <= panel_ids.get(panel, set()) or (method != "B0" and not trainer):
                continue
            step = summary.get("actual_transitions")
            if trainer.get("training") == "v1" and method in ("B2", "B3"):
                step = trainer["complete"].get("transitions")
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
                training=trainer.get("training", "v2.1"),
                representative=step is None or step == trainer.get("complete",{}).get("transitions"),
                cases=detail, scenarios=dict(Counter(e["scenario_id"] for e in detail))))
        except (OSError,ValueError,TypeError,KeyError) as exc:
            data["warnings"].append(f"{rel(folder)} · {exc}")
    data["demo_models"] = legacy_demo_models() + [
        dict(id=r["id"], method=r["method"], seed=r["seed"], training="v2.1")
        for r in data["runs"] if r["demo_available"]]
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


class DemoLauncher:
    def __init__(self, python):
        self.python = python
        self.jobs = {}
        self.lock = threading.Lock()

    def start(self, model, scenario):
        if not isinstance(scenario, str) or scenario not in DEMO_CASE or not isinstance(model, str):
            raise ValueError("모델과 시나리오를 다시 선택하세요.")
        policy = "expert"
        if model != "expert":
            run = next((r for r in scan()["demo_models"] if r["id"] == model), None)
            if run is None:
                raise ValueError("선택한 모델의 로컬 체크포인트가 없습니다.")
            folder = RUNS / model
            bundle = demo_bundle(folder, read(folder / "CONFIG.json"), optional(folder, "BEST.json"), optional(folder, "COMPLETE.json"))
            if bundle is None:
                raise ValueError("선택한 체크포인트를 찾을 수 없습니다.")
            policy = str(bundle)
        with self.lock:
            for token, (proc, _, selection, _) in list(self.jobs.items()):
                if proc.poll() is not None:
                    del self.jobs[token]
                elif selection == (model, scenario):
                    return token
            token = uuid.uuid4().hex
            folder = MAIN / "demo" / f"{Path(model).name}_{scenario}_{token}"
            folder.parent.mkdir(exist_ok=True, parents=True)
            state = {"phase": "STARTING_GUI"}
            read_fd, write_fd = os.pipe()
            pipe = os.fdopen(read_fd, encoding="utf-8")
            try:
                with folder.with_suffix(".log").open("xb") as log:
                    proc = subprocess.Popen([
                        self.python, "-u", "-B", "runner/record_video.py",
                        "--protocol", str(ROOT / read(EXPERIMENT)["base_contract"]["path"]),
                        "--namespace", "contract_check", "--policy", policy, "--scenario", scenario,
                        "--case-index", str(DEMO_CASE[scenario]),
                        *(["--observe-yield"] if scenario in ("C", "ABC", "BAC") else []),
                        "--speed", "1", "--output", str(folder), "--status-fd", str(write_fd),
                    ], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                       pass_fds=(write_fd,), start_new_session=True)
            except BaseException:
                pipe.close()
                raise
            finally:
                os.close(write_fd)
            self.jobs[token] = (proc, folder, (model, scenario), state)
            threading.Thread(target=self.watch_status, args=(pipe, state), daemon=True).start()
            return token

    def watch_status(self, pipe, state):
        with pipe:
            for line in pipe:
                update = json.loads(line)
                with self.lock:
                    state.update(update)

    def status(self, token):
        with self.lock:
            job = self.jobs.get(token)
            if job is None:
                return {"phase": "CLOSED"}
            proc, folder, _, latest = job
            state = latest.copy()
        code = proc.poll()
        phase = state.get("phase", "STARTING_GUI")
        if code is not None and (code or phase != "CLOSED"):
            with folder.with_suffix(".log").open("rb") as log:
                log.seek(max(0, log.seek(0, 2) - 2000))
                lines = log.read().decode(errors="replace").strip().splitlines()
            return {"phase": "FAILED", "message": lines[-1] if lines else f"종료 코드 {code}",
                    "log": rel(folder.with_suffix(".log"))}
        if phase == "CLOSED" and not state.get("completed") and "closed by SUMO" not in state.get("message", ""):
            return {"phase": "FAILED", "message": state.get("message", "SUMO 연결 종료")}
        return {"phase": phase}


class Handler(BaseHTTPRequestHandler):
    def reply_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/demo":
            return self.send_error(404)
        port = self.server.server_port
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        host = self.headers.get("Host")
        if host not in hosts or self.headers.get("Origin") != f"http://{host}":
            return self.reply_json(403, {"error": "로컬 대시보드에서 실행하세요."})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.headers.get_content_type() != "application/json" or not 0 < size <= 2048:
                raise ValueError("잘못된 실행 요청입니다.")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("잘못된 모델 선택입니다.")
            token = self.server.launcher.start(payload.get("model"), payload.get("scenario"))
        except ValueError as exc:
            return self.reply_json(400, {"error": str(exc)})
        except OSError as exc:
            return self.reply_json(500, {"error": f"실행 환경을 확인하세요. {exc}"})
        self.reply_json(202, {"job": token})

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path == "/api/demo":
                token = parse_qs(url.query).get("job", [""])[0]
                return self.reply_json(200, self.server.launcher.status(token))
            if url.path == "/api/results":
                body, mime = json.dumps(scan(), allow_nan=False).encode(), "application/json"
            elif url.path == "/map.svg":
                body, mime = map_svg().encode(), "image/svg+xml"
            elif url.path == "/api/log":
                name = parse_qs(url.query).get("file",[""])[0]
                path = (RUNS / name).resolve()
                if not path.is_relative_to(MAIN) or path.suffix != ".log" or not path.is_file():
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
    parser.add_argument("--port", type=int, default=4796)
    parser.add_argument("--demo-python", default=sys.executable, help="Python from the SUMO training environment")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1",args.port), Handler) as server:
        server.launcher = DemoLauncher(args.demo_python)
        print(f"http://localhost:{server.server_port}",flush=True)
        server.serve_forever()
