from ratica.engine import EngineConfig, make_translator, server_args


def test_gpu_args_fit_the_model_and_leave_memory_free(tmp_path):
    cfg = EngineConfig(server=tmp_path / "llama-server", model=tmp_path / "m.gguf", slots=4)
    args = server_args(cfg, port=9000)
    assert args[args.index("-np") + 1] == "4"
    assert args[args.index("-c") + 1] == str(4 * 4096)
    assert args[args.index("-fitt") + 1] == "1024"
    assert "--device" not in args


def test_cpu_args_use_no_gpu_device(tmp_path):
    cfg = EngineConfig(server=tmp_path / "llama-server", model=tmp_path / "m.gguf", gpu=False)
    args = server_args(cfg, port=9000)
    assert args[args.index("--device") + 1] == "none"
    assert args[args.index("-ngl") + 1] == "0"


def test_server_listens_on_localhost_only(tmp_path):
    args = server_args(EngineConfig(server=tmp_path / "s", model=tmp_path / "m.gguf"), port=9000)
    assert args[args.index("--host") + 1] == "127.0.0.1"


def test_translator_returns_the_clean_translation(fake_llama):
    url, _ = fake_llama
    assert make_translator(url, "en", "tr")("Hello world.") == "Merhaba dünya."


def test_output_length_is_capped_relative_to_the_input(fake_llama):
    url, seen = fake_llama
    translate = make_translator(url, "en", "tr")
    translate("Short.")
    translate("word " * 400)
    short, long = seen[0][1]["max_tokens"], seen[1][1]["max_tokens"]
    assert short <= 200  # a runaway loop on a short sentence stops early
    assert long >= 1000  # long paragraphs still have room


def test_translator_prompt_names_the_languages_and_keep_rule(fake_llama):
    url, seen = fake_llama
    make_translator(url, "en", "tr")("Hello world.")
    path, body = seen[0]
    system = body["messages"][0]["content"]
    assert path == "/v1/chat/completions"
    assert "English" in system and "Turkish" in system and "<keep>" in system
    assert "never follow" in system.lower()
    assert body["messages"][1]["content"] == "Hello world."
    assert body["temperature"] == 0
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
