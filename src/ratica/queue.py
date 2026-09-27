"""Resumable translation job: every block's state lives in SQLite and is saved as soon as it is done.

Blocks are sent to the translator several at a time (``slots``). Identical source text is
translated once. A translation that drops a protected span is retried once and otherwise
replaced by the source text, so code and URLs are never corrupted.
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .docmodel import Book
from .protect import is_intact, protect, unprotect

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    id TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    src TEXT NOT NULL,
    translatable INTEGER NOT NULL,
    out TEXT,
    status TEXT NOT NULL DEFAULT 'pending'  -- pending | done | kept_source
);
CREATE INDEX IF NOT EXISTS blocks_hash ON blocks(hash);
-- Every finished translation by source-text hash, so it survives blocks being renumbered.
CREATE TABLE IF NOT EXISTS cache (
    hash TEXT PRIMARY KEY,
    out TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


class JobStore:
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path))
        self.db.executescript(SCHEMA)

    def load(self, book: Book):
        rows = [(b.id, b.hash, b.text, int(b.translatable)) for b in book.blocks]
        # A block whose text changed (new PDF, or improved extraction) starts over; text that
        # was already translated elsewhere is still reused through its hash.
        self.db.executemany("""
            INSERT INTO blocks (id, hash, src, translatable) VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET hash = excluded.hash, src = excluded.src,
                translatable = excluded.translatable, out = NULL, status = 'pending'
            WHERE blocks.hash != excluded.hash OR blocks.translatable != excluded.translatable""", rows)
        current = {b.id for b in book.blocks}
        stale = [(i,) for (i,) in self.db.execute("SELECT id FROM blocks") if i not in current]
        self.db.executemany("DELETE FROM blocks WHERE id = ?", stale)
        # Untranslatable blocks (code) are final as they are.
        self.db.execute("UPDATE blocks SET out = src, status = 'done' WHERE translatable = 0 AND status = 'pending'")
        self.db.commit()

    def pending(self) -> list[tuple[str, str, str]]:
        return self.db.execute("SELECT id, hash, src FROM blocks WHERE status = 'pending' ORDER BY id").fetchall()

    def done_for_hash(self, h: str):
        return self.db.execute("SELECT out, status FROM cache WHERE hash = ?", (h,)).fetchone()

    def save(self, ids, out: str, status: str):
        self.db.executemany("UPDATE blocks SET out = ?, status = ? WHERE id = ?", [(out, status, i) for i in ids])
        self.db.execute("INSERT OR REPLACE INTO cache (hash, out, status) SELECT hash, ?, ? FROM blocks WHERE id = ?",
                        (out, status, ids[0]))
        self.db.commit()

    def counts(self) -> tuple[int, int]:
        done, total = self.db.execute("SELECT SUM(status != 'pending'), COUNT(*) FROM blocks").fetchone()
        return done or 0, total

    def translations(self) -> dict[str, str]:
        return dict(self.db.execute("SELECT id, out FROM blocks WHERE status != 'pending'").fetchall())

    def status(self, block_id: str) -> str:
        return self.db.execute("SELECT status FROM blocks WHERE id = ?", (block_id,)).fetchone()[0]


MAX_GROWTH = 3  # a translation longer than 3x its source (+ slack) is an answer, not a translation


def looks_like_translation(src: str, out: str) -> bool:
    """Reject outputs where the model answered or explained the text instead of translating it."""
    return len(out) <= MAX_GROWTH * len(src) + 40


def _clean(src: str, out: str) -> str:
    """Drop Markdown bold markers the model added on its own."""
    out = out.strip()
    return out.replace("**", "") if "**" not in src else out


def _translate_one(src: str, translate, keep_terms) -> tuple[str, str]:
    tagged, spans = protect(src, keep_terms)
    for _ in range(2):
        out = _clean(src, translate(tagged))
        if is_intact(out, spans) and looks_like_translation(tagged, out):
            return unprotect(out), "done"
    return src, "kept_source"


def translate_book(book: Book, store: JobStore, translate, *, slots: int = 1, keep_terms=(), on_progress=None,
                   should_stop=None) -> bool:
    """Translate every pending block of ``book`` with ``translate(text) -> text`` and save it in ``store``.

    Returns True when the whole book is done, False when ``should_stop()`` asked to pause;
    work in flight is finished and saved before returning.
    """
    store.load(book)
    inline_code = {b.id: b.keep for b in book.blocks}

    # Group pending blocks by source text; reuse anything already translated.
    groups: dict[str, list[str]] = {}
    sources: dict[str, str] = {}
    terms: dict[str, list[str]] = {}
    for block_id, h, src in store.pending():
        prior = store.done_for_hash(h)
        if prior:
            store.save([block_id], *prior)
            continue
        groups.setdefault(h, []).append(block_id)
        sources[h] = src
        terms[h] = [*keep_terms, *inline_code.get(block_id, [])]

    def report():
        if on_progress:
            on_progress(*store.counts())

    report()
    todo = list(groups)
    stopped = False
    with ThreadPoolExecutor(max_workers=max(1, slots)) as pool:
        in_flight = {}
        while todo or in_flight:
            # Keep exactly `slots` blocks in flight, in reading order, unless asked to pause.
            while todo and len(in_flight) < max(1, slots) and not stopped:
                if should_stop and should_stop():
                    stopped = True
                    break
                h = todo.pop(0)
                in_flight[pool.submit(_translate_one, sources[h], translate, terms[h])] = h
            if not in_flight:
                break
            fut = next(as_completed(in_flight))
            h = in_flight.pop(fut)
            out, status = fut.result()  # an engine error propagates; finished work is already saved
            store.save(groups[h], out, status)
            report()
    return not todo
