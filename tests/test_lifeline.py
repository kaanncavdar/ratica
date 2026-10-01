"""The engine must never outlive Ratica: a stray llama-server keeps holding GPU memory."""
import subprocess
import sys
import time

import psutil

from ratica import lifeline

SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


def _gone(pid: int, seconds: float = 15) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.2)
    return False


def test_the_engine_dies_when_ratica_is_killed():
    parent_code = (
        "import subprocess, sys, time\n"
        "from ratica import lifeline\n"
        f"child = subprocess.Popen({SLEEPER!r})\n"
        "lifeline.bind(child)\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(120)\n")
    parent = subprocess.Popen([sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline())
    try:
        assert psutil.pid_exists(child_pid)
        parent.kill()  # a crash: no cleanup code runs in the parent
        parent.wait()
        assert _gone(child_pid)
    finally:
        try:
            psutil.Process(child_pid).kill()
        except psutil.NoSuchProcess:
            pass


def test_running_engines_are_stopped_on_exit():
    child = subprocess.Popen(SLEEPER)
    lifeline.register(child)
    lifeline.stop_all()
    assert child.wait(timeout=10) is not None


class FakeProc:
    def __init__(self, pid, exe, ppid, created, parent_created=None):
        self.pid, self._exe, self._ppid, self._created = pid, exe, ppid, created
        self.info = {"pid": pid, "exe": exe}
        self.parent_created = parent_created
        self.killed = False

    def ppid(self):
        return self._ppid

    def create_time(self):
        return self._created

    def kill(self):
        self.killed = True


def test_only_ownerless_engines_from_ratica_are_cleaned_up(tmp_path, monkeypatch):
    engines = tmp_path / "engines"
    server = str(engines / "b1" / "llama-server")
    orphan = FakeProc(10, server, 1, 100.0)  # re-parented to init/launchd: its Ratica is gone
    dead_parent = FakeProc(11, server, 999, 100.0)  # parent pid no longer exists
    reused_pid = FakeProc(12, server, 50, 100.0)  # parent pid now belongs to a newer process
    owned = FakeProc(13, server, 60, 100.0)  # a running Ratica still owns it
    other = FakeProc(14, str(tmp_path / "elsewhere" / "llama-server"), 1, 100.0)  # not ours
    procs = [orphan, dead_parent, reused_pid, owned, other]
    parents = {50: 200.0, 60: 50.0}  # parent pid -> its start time

    monkeypatch.setattr(lifeline.psutil, "process_iter", lambda attrs=None: iter(procs))
    monkeypatch.setattr(lifeline, "_start_time", lambda pid: parents.get(pid))
    assert lifeline.kill_orphans(engines) == 3
    assert [p.killed for p in procs] == [True, True, True, False, False]
