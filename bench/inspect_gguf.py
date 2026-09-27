"""Print GGUF metadata useful for the benchmark (chat template hints, sizes)."""
import re
import sys

from gguf import GGUFReader


def field_str(reader, key):
    f = reader.fields.get(key)
    if f is None:
        return None
    val = f.parts[f.data[0]]
    try:
        return bytes(val).decode()
    except Exception:
        return val.tolist()


for path in sys.argv[1:]:
    r = GGUFReader(path)
    print("==", path)
    print("   arch:", field_str(r, "general.architecture"))
    tpl = field_str(r, "tokenizer.chat_template") or ""
    print("   template chars:", len(tpl), "| enable_thinking:", "enable_thinking" in tpl)
    for code in ["en", "tr", "zh", "zh-Hans", "zh-CN", "ru", "az", "hi"]:
        m = re.search(r'"' + re.escape(code) + r'"\s*:\s*"([^"]+)"', tpl)
        if m:
            print(f"   lang {code} -> {m.group(1)}")
