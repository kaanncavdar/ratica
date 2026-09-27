"""Download and verify the llama.cpp engine and the default model.

Every file is pinned by SHA-256 to exactly what was benchmarked (see bench/RESULTS.md).
Downloads resume after an interruption and are only moved into place once verified.
"""
import hashlib
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from . import paths

LLAMA_BUILD = "b11211"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/"


@dataclass(frozen=True)
class Asset:
    name: str
    sha256: str
    size: int

    @property
    def url(self) -> str:
        return LLAMA_URL + self.name


_A = {
    "win-cuda": Asset("llama-b11211-bin-win-cuda-12.4-x64.zip",
                      "33c8475c137bdaf7d0c108b0e77cb02eddc26f53d193c3acf69f1e4237668081", 263078592),
    "win-cudart": Asset("cudart-llama-bin-win-cuda-12.4-x64.zip",
                        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6", 391443627),
    "win-vulkan": Asset("llama-b11211-bin-win-vulkan-x64.zip",
                        "84205d373657d81e2ae272c2fefe72148e655d72684745aa8c137578d8e3a855", 33062372),
    "linux-cuda": Asset("llama-b11211-bin-ubuntu-cuda-12.8-x64.tar.gz",
                        "4c2e16a4e018bce19857280de03dcb1b6e1b112d8b933b8d21c21e5503be475c", 170927056),
    "linux-cudart": Asset("cudart-llama-b11211-bin-ubuntu-cuda-12.8-x64.tar.gz",
                          "7dc8fa4a580c66fd828dc97976f2ea4c473fcd183537d1ad408421e0ec487510", 594377924),
    "linux-vulkan": Asset("llama-b11211-bin-ubuntu-vulkan-x64.tar.gz",
                          "39d0c77061e045b7138f441f399b6ecb47b7b019c1cf94d5eed6e7ef0973032d", 31345681),
    "win-cpu": Asset("llama-b11211-bin-win-cpu-x64.zip",
                     "4523850c6d869ebe0642cf5ad9a26578a3ddc60f544f085562ee9bce3084ed99", 19155103),
    "linux-cpu": Asset("llama-b11211-bin-ubuntu-x64.tar.gz",
                       "6c1d18f86570db9cdb70fa2ef4cc5e8dbbdcb55294e43a8927beea08f4aba3af", 17402818),
    "mac-arm64": Asset("llama-b11211-bin-macos-arm64.tar.gz",
                       "2262cbe82440dfaa0b4ddeabded277a9fa0a91ef44ac56e3ab5ff6d820f5d4bc", 11755588),
    "mac-x64": Asset("llama-b11211-bin-macos-x64.tar.gz",
                     "e3525142255447f9bb0658b1a400ff2d58270817a6f9c07e877ce019389d80f3", 11309085),
}

# (system, backend) -> assets to unpack into one folder. The CPU builds need no GPU drivers at all.
_ENGINES = {
    ("Windows", "cuda"): ["win-cuda", "win-cudart"],
    ("Windows", "vulkan"): ["win-vulkan"],
    ("Windows", "cpu"): ["win-cpu"],
    ("Linux", "cuda"): ["linux-cuda", "linux-cudart"],
    ("Linux", "vulkan"): ["linux-vulkan"],
    ("Linux", "cpu"): ["linux-cpu"],
    ("Darwin", "metal"): ["mac-arm64"],
    ("Darwin", "cpu"): ["mac-x64"],
}

MODEL = Asset("gemma-4-E4B-it-Q4_K_M.gguf", "85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87",
              4977171584)
MODEL_URL = ("https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/"
             "bfc15c382204943c3a8fff0c750b94ae2364d7a3/" + MODEL.name)


class ChecksumError(Exception):
    pass


def engine_assets(system: str, backend: str) -> list[Asset]:
    return [_A[k] for k in _ENGINES[(system, backend)]]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest, sha256: str, on_progress=None, should_stop=None) -> Path:
    """Download ``url`` to ``dest`` (resuming a ``.part`` file) and verify its SHA-256."""
    dest = Path(dest)
    if dest.exists() and _sha256(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with requests.get(url, headers=headers, stream=True, timeout=60) as r:
        r.raise_for_status()
        if r.status_code == 200:  # server ignored the range: start over
            done = 0
        total = done + int(r.headers.get("Content-Length", 0))
        with open(part, "ab" if done else "wb") as f:
            for chunk in r.iter_content(1 << 20):
                if should_stop and should_stop():
                    raise InterruptedError("download stopped")
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    if _sha256(part) != sha256:
        part.unlink()
        raise ChecksumError(f"{dest.name}: checksum mismatch, the download was corrupted")
    part.replace(dest)
    return dest


def _unpack(archive: Path, into: Path):
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into, filter="data")


def find_server(folder: Path) -> Path | None:
    for name in ("llama-server.exe", "llama-server"):
        hits = sorted(folder.rglob(name))
        if hits:
            return hits[0]
    return None


def install_engine(system: str, backend: str, on_progress=None, should_stop=None) -> Path:
    """Download and unpack the llama.cpp build for this machine; return the llama-server path."""
    folder = paths.engines_dir() / f"{LLAMA_BUILD}-{backend}"
    server = find_server(folder) if folder.exists() else None
    if server:
        return server
    downloads = paths.data_dir() / "downloads"
    tmp = folder.with_name(folder.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    for asset in engine_assets(system, backend):
        archive = download(asset.url, downloads / asset.name, asset.sha256, on_progress, should_stop)
        _unpack(archive, tmp)
    server = find_server(tmp)
    if not server:
        raise RuntimeError("llama-server was not found in the downloaded engine")
    if system != "Windows":
        server.chmod(0o755)
    tmp.replace(folder)
    shutil.rmtree(downloads, ignore_errors=True)
    return find_server(folder)


def install_model(on_progress=None, should_stop=None) -> Path:
    return download(MODEL_URL, paths.models_dir() / MODEL.name, MODEL.sha256, on_progress, should_stop)
