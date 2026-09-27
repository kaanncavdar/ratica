"""Find out which GPU the machine has and which llama.cpp build fits it.

NVIDIA → CUDA, Apple Silicon → Metal, anything else → Vulkan (which falls back to the CPU
by itself when no GPU is usable). Intel Macs get the plain CPU build.
"""
import platform
import re
import subprocess
import sys


def parse_nvidia_smi(output: str) -> list[dict]:
    gpus = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit():
            gpus.append({"name": parts[0], "total_mib": int(parts[1]), "free_mib": int(parts[2])})
    return gpus


DEVICE = re.compile(r"^\s*\w+\d+: (.+?) \((\d+) MiB, (\d+) MiB free\)", re.M)


def parse_list_devices(output: str) -> list[dict]:
    """Parse ``llama-server --list-devices``."""
    return [{"name": m[0], "total_mib": int(m[1]), "free_mib": int(m[2])} for m in DEVICE.findall(output)]


def nvidia_gpus() -> list[dict]:
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15,
                             creationflags=flags)
        return parse_nvidia_smi(out.stdout) if out.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        return []


def choose_backend(system: str, machine: str, nvidia: list[dict]) -> str:
    if system == "Darwin":
        return "metal" if machine.lower() in ("arm64", "aarch64") else "cpu"
    if nvidia:
        return "cuda"
    return "vulkan"


def probe() -> dict:
    """Describe this machine: OS, CPU architecture, NVIDIA GPUs and the backend to use."""
    system, machine = platform.system(), platform.machine()
    nvidia = nvidia_gpus()
    return {"system": system, "machine": machine, "nvidia": nvidia,
            "backend": choose_backend(system, machine, nvidia)}
