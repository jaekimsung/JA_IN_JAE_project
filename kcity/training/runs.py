"""Run-directory ownership, status files and cooperative STOP handling."""
import json
import os
from pathlib import Path
import signal

from kcity.data.dataset import atomic_json, now, pid_alive

STOP = False


def read(path):
    return json.loads(Path(path).read_text())


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def stop_handler(*args):
    global STOP
    STOP = True


def install_signals():
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)


def stopped(root):
    return STOP or (Path(root)/'STOP').exists()


class Owner:
    def __init__(self, root, config, resume=False):
        self.root = Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.path = self.root/'OWNER.json'
        if self.path.exists():
            pid = read(self.path)['pid']
            if pid_alive(pid):
                raise RuntimeError('Another process owns this run')
            require(resume,'Stale owner requires explicit --resume')
            self.path.unlink()
        manifest = self.root/'CONFIG.json'
        if manifest.exists():
            require(resume and read(manifest)==config, 'Explicit resume with identical configuration required')
        else:
            require(not resume and not any(self.root.iterdir()), 'New run requires a new empty output')
            atomic_json(manifest,config)
        with self.path.open('x') as stream:
            json.dump(dict(pid=os.getpid(),started_at=now()),stream)

    def close(self):
        self.path.unlink(missing_ok=True)
