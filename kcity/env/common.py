"""SUMO tool discovery, map paths and JSON/XML helpers shared by the environment and map tools."""
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "maps" / "kcity"


def sumo_tools():
    candidates = [Path(os.environ["SUMO_HOME"])] if os.environ.get("SUMO_HOME") else []
    candidates += [Path("/usr/share/sumo"), Path("/usr/local/share/sumo"),
                   Path("/opt/homebrew/opt/sumo/share/sumo")]
    for home in candidates:
        if (home / "tools" / "sumolib").is_dir():
            os.environ.setdefault("SUMO_HOME", str(home))
            sys.path.insert(0, str(home / "tools"))
            break
    import sumolib
    return sumolib


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def write_xml(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()
