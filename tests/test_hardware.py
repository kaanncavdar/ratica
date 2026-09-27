from ratica.hardware import choose_backend, parse_list_devices, parse_nvidia_smi


def test_parse_nvidia_smi():
    gpus = parse_nvidia_smi("NVIDIA GeForce RTX 4060, 8188, 7400\n")
    assert gpus == [{"name": "NVIDIA GeForce RTX 4060", "total_mib": 8188, "free_mib": 7400}]


def test_parse_nvidia_smi_without_gpu():
    assert parse_nvidia_smi("") == []


def test_parse_list_devices():
    out = ("0.00.001.608 I srv  llama_server: initializing ...\nAvailable devices:\n"
           "  Vulkan0: AMD Radeon RX 7600 (8176 MiB, 7900 MiB free)\n")
    assert parse_list_devices(out) == [{"name": "AMD Radeon RX 7600", "total_mib": 8176, "free_mib": 7900}]


def test_apple_silicon_uses_metal():
    assert choose_backend(system="Darwin", machine="arm64", nvidia=[]) == "metal"


def test_nvidia_uses_cuda_on_windows_and_linux():
    gpu = [{"name": "RTX 4060", "total_mib": 8188, "free_mib": 7000}]
    assert choose_backend(system="Windows", machine="AMD64", nvidia=gpu) == "cuda"
    assert choose_backend(system="Linux", machine="x86_64", nvidia=gpu) == "cuda"


def test_everything_else_uses_vulkan():
    assert choose_backend(system="Windows", machine="AMD64", nvidia=[]) == "vulkan"
    assert choose_backend(system="Linux", machine="x86_64", nvidia=[]) == "vulkan"


def test_intel_mac_falls_back_to_cpu():
    assert choose_backend(system="Darwin", machine="x86_64", nvidia=[]) == "cpu"
