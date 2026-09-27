"""Blind side-by-side rating of Turkish translations.

    uv run python bench/rate.py        -> serves http://127.0.0.1:8765

For every rated item the rater sees the English source and each model's output in a
shuffled order with no model names; identical outputs are merged into one card.
Choices are saved to bench/results/ratings.json after every click, so the session can
be stopped and resumed.
"""
import html
import json
import random
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BENCH = Path(__file__).parent
RESULTS = BENCH / "results"
RATINGS = RESULTS / "ratings.json"
PORT = 8765


def load_tasks():
    testset = json.loads((BENCH / "data" / "testset.json").read_text(encoding="utf-8"))
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS.glob("*-gpu.json"))
            if not p.name.startswith("parallel-")]
    tasks = []
    for item in (i for i in testset if i["rated"]):
        variant = "keep" if item["kind"] == "synthetic" else "plain"
        cands = {}
        for run in runs:
            row = next(x for x in run["rows"] if x["id"] == item["id"] and x["variant"] == variant)
            text = re.sub(r"</?keep>", "", row["out"]).strip()
            cands.setdefault(text, []).append(run["model"])
        options = [{"text": t, "models": m} for t, m in cands.items()]
        random.Random(item["id"]).shuffle(options)  # stable per item, unrelated to model order
        src = re.sub(r"\[\[(.+?)\]\]", r"\1", item.get("src") or item["src_marked"])
        tasks.append({"id": item["id"], "src": src, "options": options})
    return tasks


TASKS = load_tasks()


def load_ratings():
    return json.loads(RATINGS.read_text(encoding="utf-8")) if RATINGS.exists() else {}


# CSS contains "%" signs, so the body is inserted with str.replace, not %-formatting.
PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Çeviri karşılaştırma</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#1b2230;--muted:#5d6675;--line:#dde2e8;--accent:#1c6a86}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a2029;--ink:#e5e9ef;--muted:#9aa4b3;--line:#2b3440;--accent:#6cc0dc}}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 system-ui,"Segoe UI",sans-serif;padding:24px 16px 64px}
main{max-width:760px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
.top{display:flex;justify-content:space-between;color:var(--muted);font-size:14px}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent)}
.src{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.src small,.hint{color:var(--muted);font-size:13px}
form{display:flex;flex-direction:column;gap:10px;margin:0}
button.opt{all:unset;box-sizing:border-box;background:var(--card);border:2px solid var(--line);border-radius:10px;padding:14px 16px;cursor:pointer;white-space:pre-wrap}
button.opt:hover,button.opt:focus-visible{border-color:var(--accent)}
button.opt b{color:var(--accent);margin-right:8px}
.row{display:flex;gap:10px;flex-wrap:wrap}
.row button{font:inherit;font-size:15px;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
a{color:var(--accent)}
</style></head><body><main>__BODY__</main>
<script>document.addEventListener('keydown',e=>{const b=document.querySelector('[data-key="'+e.key+'"]');if(b)b.click();});</script>
</body></html>"""


def page(body):
    return PAGE.replace("__BODY__", body)


def render(idx):
    ratings = load_ratings()
    done = sum(1 for t in TASKS if t["id"] in ratings)
    if idx >= len(TASKS):
        return page(f"<h1>Bitti, teşekkürler.</h1><p>{done}/{len(TASKS)} cümle puanlandı. Pencereyi kapatabilirsin.</p>")
    t = TASKS[idx]
    letters = "ABCDEFGH"
    opts = "".join(
        f'<button class="opt" name="pick" value="{n}" data-key="{n + 1}"><b>{letters[n]}</b>{html.escape(o["text"])}</button>'
        for n, o in enumerate(t["options"]))
    prev = f'<a href="/?i={idx - 1}">← geri</a>' if idx else ""
    return page(f"""
<div class="top"><span>{idx + 1} / {len(TASKS)}</span><span>{prev}</span></div>
<div class="bar"><i style="width:{100 * done / len(TASKS):.0f}%"></i></div>
<div class="src"><small>İngilizce</small><div>{html.escape(t["src"])}</div></div>
<p class="hint">En iyi Türkçe çeviriyi seç (klavye: 1–{len(t["options"])}). Model adları gizli, sıra karışık.</p>
<form method="post" action="/rate?i={idx}">{opts}
<div class="row"><button name="pick" value="tie" data-key="0">Hepsi aynı kalitede (0)</button></div></form>""")


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200, headers=None):
        self.send_response(code)
        for k, v in (headers or {"Content-Type": "text/html; charset=utf-8"}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        if "i" in q:
            idx = int(q["i"][0])
        else:  # resume at the first unrated item
            ratings = load_ratings()
            idx = next((n for n, t in enumerate(TASKS) if t["id"] not in ratings), len(TASKS))
        self._send(render(max(0, idx)))

    def do_POST(self):
        idx = int(parse_qs(urlparse(self.path).query)["i"][0])
        pick = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())["pick"][0]
        t = TASKS[idx]
        ratings = load_ratings()
        ratings[t["id"]] = {"winners": "tie" if pick == "tie" else t["options"][int(pick)]["models"],
                            "options": t["options"]}
        RATINGS.write_text(json.dumps(ratings, ensure_ascii=False, indent=1), encoding="utf-8")
        self._send("", 303, {"Location": f"/?i={idx + 1}"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"{len(TASKS)} items -> http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
