"""Keep the translation engine from outliving Ratica.

A llama-server left running holds gigabytes of GPU memory, and every later start then fails for lack of
memory. Three guards:

- ``bind`` ties the engine to this process. Windows: a job object that closes the engine when Ratica's last
  handle goes away, however Ratica ends. macOS/Linux: a tiny watchdog process that stops the engine once
  Ratica is gone.
- ``register`` / ``stop_all`` stop engines on a normal exit (atexit, closing the window).
- ``kill_orphans`` stops engines from Ratica's own engines folder whose Ratica is no longer running
  (for example after a crash of an older version).
"""
import atexit
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

_running: set = set()
_lock = threading.Lock()
_jobs = []  # Windows job handles; closing them (at process end) closes the engines


def register(proc: subprocess.Popen):
    with _lock:
        _running.add(proc)


def unregister(proc: subprocess.Popen):
    with _lock:
        _running.discard(proc)


def stop(proc: subprocess.Popen, timeout: float = 10):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)
    unregister(proc)


def stop_all():
    with _lock:
        procs = list(_running)
    for proc in procs:
        try:
            stop(proc)
        except OSError:
            pass


atexit.register(stop_all)


# --- tie the engine to this process ------------------------------------------------------------------------------

def bind(proc: subprocess.Popen):
    """Make sure ``proc`` ends when this process ends, even if this process is killed."""
    register(proc)
    if sys.platform == "win32":
        _bind_windows(proc)
    else:
        _start_watchdog(proc.pid)


def _bind_windows(proc: subprocess.Popen):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # ExtendedLimitInformation
    if ok and kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
        _jobs.append(job)  # kept open for the life of this process on purpose


def _watchdog_command(parent: int, child: int) -> list[str]:
    if getattr(sys, "frozen", False):  # the packaged app: packaging/launch.py runs it
        return [sys.executable, "_watchdog", str(parent), str(child)]
    return [sys.executable, "-m", "ratica.lifeline", str(parent), str(child)]


def _start_watchdog(child: int):
    subprocess.Popen(_watchdog_command(os.getpid(), child), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def watchdog(parent: int, child: int, poll: float = 1.0):
    """Wait until ``parent`` ends, then stop ``child`` (unless it ended first)."""
    while psutil.pid_exists(child):
        try:
            alive = psutil.Process(parent).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            alive = False
        if not alive:
            try:
                p = psutil.Process(child)
                p.terminate()
                try:
                    p.wait(timeout=10)
                except psutil.TimeoutExpired:
                    p.kill()
            except psutil.NoSuchProcess:
                pass
            return
        time.sleep(poll)


# --- clean up after an earlier crash -----------------------------------------------------------------------------

def _start_time(pid: int):
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _is_ours(exe: str | None, engines_dir: Path) -> bool:
    if not exe:
        return False
    try:
        return Path(exe).resolve().is_relative_to(engines_dir.resolve())
    except (OSError, ValueError):
        return False


def kill_orphans(engines_dir: Path) -> int:
    """Stop engines started from ``engines_dir`` whose parent process is gone. Returns how many."""
    killed = 0
    for proc in psutil.process_iter(["pid", "exe"]):
        try:
            if not _is_ours(proc.info.get("exe"), Path(engines_dir)):
                continue
            ppid = proc.ppid()
            parent_started = None if ppid in (0, 1) else _start_time(ppid)
            # No parent, or the parent pid was reused by a process that started after the engine.
            if parent_started is None or parent_started > proc.create_time():
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed


if __name__ == "__main__":  # python -m ratica.lifeline <parent pid> <child pid>
    watchdog(int(sys.argv[1]), int(sys.argv[2]))
