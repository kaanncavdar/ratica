import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ratica.install import ChecksumError, download, engine_assets

DATA = bytes(range(256)) * 400  # 100 KiB
SHA = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def file_server():
    """Serves DATA at /file, honouring Range requests; counts bytes sent."""
    sent = {"bytes": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            start = 0
            if "Range" in self.headers:
                start = int(self.headers["Range"].split("=")[1].split("-")[0])
                self.send_response(206)
            else:
                self.send_response(200)
            body = DATA[start:]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            sent["bytes"] += len(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/file", sent
    srv.shutdown()


def test_download_verifies_and_reports_progress(file_server, tmp_path):
    url, _ = file_server
    seen = []
    path = download(url, tmp_path / "f.bin", SHA, on_progress=lambda done, total: seen.append((done, total)))
    assert path.read_bytes() == DATA
    assert seen[-1] == (len(DATA), len(DATA))


def test_download_resumes_a_partial_file(file_server, tmp_path):
    url, sent = file_server
    (tmp_path / "f.bin.part").write_bytes(DATA[:60000])
    download(url, tmp_path / "f.bin", SHA)
    assert sent["bytes"] == len(DATA) - 60000
    assert (tmp_path / "f.bin").read_bytes() == DATA


def test_download_rejects_a_wrong_checksum(file_server, tmp_path):
    url, _ = file_server
    with pytest.raises(ChecksumError):
        download(url, tmp_path / "f.bin", "0" * 64)
    assert not (tmp_path / "f.bin").exists()
    assert not (tmp_path / "f.bin.part").exists()


def test_existing_verified_file_is_not_downloaded_again(file_server, tmp_path):
    url, sent = file_server
    download(url, tmp_path / "f.bin", SHA)
    download(url, tmp_path / "f.bin", SHA)
    assert sent["bytes"] == len(DATA)


def test_windows_cuda_needs_the_engine_and_the_cuda_runtime():
    names = [a.name for a in engine_assets("Windows", "cuda")]
    assert names == ["llama-b11211-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]


def test_cpu_fallback_uses_a_build_without_gpu_libraries():
    assert [a.name for a in engine_assets("Windows", "cpu")] == ["llama-b11211-bin-win-cpu-x64.zip"]
    assert [a.name for a in engine_assets("Linux", "cpu")] == ["llama-b11211-bin-ubuntu-x64.tar.gz"]


def test_every_supported_platform_has_pinned_assets():
    for system, backend in [("Windows", "vulkan"), ("Windows", "cpu"), ("Linux", "vulkan"), ("Linux", "cuda"),
                            ("Linux", "cpu"), ("Darwin", "metal")]:
        assets = engine_assets(system, backend)
        assert assets and all(len(a.sha256) == 64 for a in assets)
