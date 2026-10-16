#!/usr/bin/env python3
"""One writer at a time for a file: a lock file beside it, made with O_EXCL. Stdlib only.

    with locked(path):        # path.lock exists while the block runs
        ...

A lock left by a writer that died is stale after STALE_S and is taken over. Used by keys.py (the key file)
and project_store.py (project.json).

    python3 fslock.py demo    self-check
"""
import contextlib
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

STALE_S = 10


@contextlib.contextmanager
def locked(path, wait=10):
    lock = Path(path).with_name(Path(path).name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(int(wait / 0.025)):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            break
        except (FileExistsError, PermissionError):   # Windows: a lock being deleted refuses a new open
            try:
                if time.time() - lock.stat().st_mtime > STALE_S:
                    lock.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.025)
    else:
        raise TimeoutError(f"{lock} is held; delete it if nothing is writing {Path(path).name}")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def demo():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "n.txt"
        f.write_text("0", encoding="utf-8")

        def bump():
            for _ in range(25):
                with locked(f):
                    f.write_text(str(int(f.read_text(encoding="utf-8")) + 1), encoding="utf-8")
        ts = [threading.Thread(target=bump) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert f.read_text(encoding="utf-8") == "100", f.read_text(encoding="utf-8")
        assert not (Path(d) / "n.txt.lock").exists()
        stale = Path(d) / "n.txt.lock"
        stale.write_text("", encoding="utf-8")
        os.utime(stale, (time.time() - 60, time.time() - 60))
        with locked(f, wait=1):   # a dead writer's lock is taken over
            pass
    print("demo ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        print(__doc__)
        sys.exit(2)
