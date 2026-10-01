"""Desktop window: pick a PDF, pick a language, translate. Everything else happens by itself."""
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QLocale, QObject, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from . import __version__, lifeline, paths
from .detect import detect_language
from .engine import LANGUAGES
from .extract import extract
from .queue import JobStore
from .service import (book_estimate, downloads_size, load_settings, prepare, remove_downloads,
                      translate_pdf, work_dir)

ISSUES_URL = "https://github.com/kaanncavdar/ratica/issues"

STYLE = """
QWidget { font-size: 10.5pt; }
QFrame#card { background: palette(base); border: 1px solid palette(mid); border-radius: 10px; }
QLabel#title { font-size: 20pt; font-weight: 600; }
QLabel#muted { color: palette(placeholder-text); }
QPushButton#primary { background: #1c6a86; color: white; border: none; border-radius: 6px; padding: 8px 18px;
                      font-weight: 600; }
QPushButton#primary:disabled { background: #9fb6c0; }
QPushButton#primary:hover:enabled { background: #175a72; }
QProgressBar { border: none; background: palette(midlight); border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #1c6a86; border-radius: 4px; }
"""


def _fmt_minutes(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 1:
        return "less than a minute"
    if minutes < 90:
        return f"about {round(minutes)} min"
    return f"about {minutes / 60:.1f} hours"


class Bridge(QObject):
    """Signals emitted from worker threads; Qt delivers them on the GUI thread."""
    progress = Signal(int, int)
    stage = Signal(str, float, float)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)


def _card():
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    return f, lay


def _muted(text=""):
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


class MainWindow(QMainWindow):
    job_done = Signal(object)

    def __init__(self, server_url: str | None = None):
        super().__init__()
        self.server_url = server_url  # tests and advanced users: use an already running llama-server
        self.settings = load_settings()
        self.pdf: Path | None = None
        self.book = None
        self.result = None
        self.busy = False
        self.pause_requested = False
        self.bridge = Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.stage.connect(self._on_stage)
        self.bridge.log.connect(lambda m: self.status.setText(m))
        self.bridge.done.connect(self._on_done)
        self.bridge.failed.connect(self._on_failed)

        self.setWindowTitle("Ratica")
        self.setMinimumSize(560, 640)
        self.setAcceptDrops(True)
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)
        title = QLabel("Ratica")
        title.setObjectName("title")
        outer.addWidget(title)
        outer.addWidget(_muted("Translate PDF books on your own computer. Nothing is uploaded."))

        # --- first-run setup
        self.setup_box, lay = _card()
        lay.addWidget(QLabel("<b>Get ready</b>"))
        lay.addWidget(_muted("Ratica downloads its translation engine and AI model once (about 5–6 GB) and measures "
                             "your computer's speed. This takes a few minutes and only happens the first time."))
        self.setup_button = QPushButton("Download and set up")
        self.setup_button.setObjectName("primary")
        self.setup_button.clicked.connect(self.run_setup)
        self.setup_progress = QProgressBar()
        self.setup_progress.setVisible(False)
        self.setup_status = _muted()
        lay.addWidget(self.setup_button, alignment=Qt.AlignLeft)
        lay.addWidget(self.setup_progress)
        lay.addWidget(self.setup_status)
        outer.addWidget(self.setup_box)

        # --- book
        book_box, lay = _card()
        row = QHBoxLayout()
        self.book_name = QLabel("<b>No book chosen</b>")
        choose = QPushButton("Choose PDF…")
        choose.clicked.connect(self.choose_pdf)
        row.addWidget(self.book_name, 1)
        row.addWidget(choose)
        lay.addLayout(row)
        self.book_info = _muted("Drop a PDF on this window or choose one.")
        lay.addWidget(self.book_info)

        grid = QGridLayout()
        self.source_language, self.language = QComboBox(), QComboBox()
        for n, (label, combo) in enumerate((("Translate from", self.source_language), ("Translate to", self.language))):
            for code, name in sorted(LANGUAGES.items(), key=lambda kv: kv[1]):
                combo.addItem(name, code)
            combo.currentIndexChanged.connect(lambda _: self._refresh())
            grid.addWidget(QLabel(label), n, 0)
            grid.addWidget(combo, n, 1)
        self.keep = QLineEdit()
        self.keep.setPlaceholderText("names, separated by commas (optional)")
        grid.addWidget(QLabel("Do not translate"), 2, 0)
        grid.addWidget(self.keep, 2, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        outer.addWidget(book_box)

        # --- run
        run_box, lay = _card()
        self.estimate = QLabel("")
        lay.addWidget(self.estimate)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        lay.addWidget(self.progress)
        self.status = _muted()
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.start_button = QPushButton("Translate")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._on_start_clicked)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setVisible(False)
        self.pause_button.clicked.connect(self._on_pause_clicked)
        row.addWidget(self.start_button)
        row.addWidget(self.pause_button)
        row.addStretch(1)
        self.open_pdf_button = QPushButton("Open PDF")
        self.open_epub_button = QPushButton("Open EPUB")
        self.open_folder_button = QPushButton("Show folder")
        for b, attr in ((self.open_pdf_button, "pdf"), (self.open_epub_button, "epub")):
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, a=attr: self._open(self.result and self.result[a]))
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(lambda: self._open(self.pdf and self.pdf.parent))
        for b in (self.open_pdf_button, self.open_epub_button, self.open_folder_button):
            row.addWidget(b)
        lay.addLayout(row)
        outer.addWidget(run_box)

        foot = _muted(f'Ratica {__version__} · runs entirely on this computer · '
                      f'<a href="{ISSUES_URL}">report a problem</a>')
        foot.setOpenExternalLinks(True)
        outer.addWidget(foot)
        self.storage = _muted()
        self.storage.linkActivated.connect(lambda _: self.remove_downloads())
        outer.addWidget(self.storage)
        outer.addStretch(1)
        self.setCentralWidget(root)

        prefs = QSettings("Ratica", "Ratica")
        default = prefs.value("target", QLocale.system().name().split("_")[0])
        self.set_source("en")
        self.set_target(default if default in LANGUAGES and default != "en" else "es")
        self._refresh()

    # --- state -------------------------------------------------------------------------------------------------
    def ready(self) -> bool:
        return bool(self.server_url) or bool(self.settings and self.settings.is_current())

    def target(self) -> str:
        return self.language.currentData()

    def source(self) -> str:
        return self.source_language.currentData()

    def set_source(self, code: str):
        idx = self.source_language.findData(code)
        if idx >= 0:
            self.source_language.setCurrentIndex(idx)

    def set_target(self, code: str):
        idx = self.language.findData(code)
        if idx >= 0:
            self.language.setCurrentIndex(idx)

    def _done_ids(self) -> set[str]:
        if not self.pdf:
            return set()
        db = work_dir(self.pdf, self.pdf.parent, self.target()) / "job.sqlite"
        return set(JobStore(db).translations()) if db.exists() else set()

    def remove_downloads(self):
        size = downloads_size() / 1e9
        answer = QMessageBox.question(
            self, "Ratica", f"Delete the translation engine and AI model Ratica downloaded ({size:.1f} GB)?\n\n"
            "Your PDFs and translated books are not affected. Ratica downloads the files again the next time "
            "you set it up.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        remove_downloads()
        self.settings = load_settings()
        self._refresh()

    def _refresh(self):
        size = 0 if self.busy or self.server_url else downloads_size()
        self.storage.setText(f'Downloaded engine and model: {size / 1e9:.1f} GB · <a href="remove">delete</a>'
                             if size else "")
        self.setup_box.setVisible(not self.ready())
        same = self.source() == self.target()
        can_start = self.ready() and self.book is not None and not self.busy and not same
        self.start_button.setEnabled(can_start)
        if self.book is None:
            self.estimate.setText("")
            return
        if same:
            self.estimate.setText("Choose two different languages.")
            return
        done = self._done_ids()
        todo = {b.id for b in self.book.blocks if b.translatable}
        if self.busy or not done:
            self.start_button.setText("Translate")
        else:
            self.start_button.setText("Translate again" if todo <= done else "Resume")
        if self.settings and self.settings.words_per_second:
            left = book_estimate(self.book, self.settings, done)
            self.estimate.setText(f"<b>{_fmt_minutes(left).capitalize()}</b> on this computer")

    # --- actions -----------------------------------------------------------------------------------------------
    def choose_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a PDF", str(Path.home()), "PDF files (*.pdf)")
        if path:
            self.open_pdf(path)

    def open_pdf(self, path):
        self.pdf = Path(path)
        try:
            self.book = extract(self.pdf)
        except Exception as e:  # a damaged or encrypted PDF
            self.book = None
            QMessageBox.warning(self, "Ratica", f"This PDF cannot be read:\n{e}")
            return
        pages = max((b.page for b in self.book.blocks), default=0)
        words = sum(len(b.text.split()) for b in self.book.blocks if b.translatable)
        self.book_name.setText(f"<b>{self.pdf.name}</b>")
        self.book_info.setText(f"{pages} page{'s' if pages != 1 else ''} · {words:,} words to translate")
        sample = " ".join(b.text for b in self.book.blocks if b.translatable)[:20000]
        detected = detect_language(sample)
        if detected in LANGUAGES:
            self.set_source(detected)
        self.result = None
        for b in (self.open_pdf_button, self.open_epub_button):
            b.setEnabled(False)
        self._refresh()

    def run_setup(self):
        self.setup_button.setEnabled(False)
        self.setup_progress.setVisible(True)

        def work():
            try:
                s = prepare(on_progress=lambda st, d, t: self.bridge.stage.emit(st, d, t),
                            log=lambda m: self.bridge.stage.emit(m, 0, 0))
                self.bridge.done.emit(("setup", s))
            except Exception as e:
                self.bridge.failed.emit(f"Setup failed: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_start_clicked(self):
        self.pause_requested = False
        self.start()

    def _on_pause_clicked(self):
        self.pause_requested = True
        self.pause_button.setEnabled(False)
        self.status.setText("Pausing after the paragraphs in progress…")

    def start(self):
        if not self.book:
            return
        self.busy = True
        QSettings("Ratica", "Ratica").setValue("target", self.target())
        self._run_first = None
        self.progress.setVisible(True)
        self.pause_button.setVisible(True)
        self.pause_button.setEnabled(True)
        self.status.setText("Starting the translation engine…")
        self._refresh()
        keep = [t.strip() for t in self.keep.text().split(",") if t.strip()]
        pdf, lang, source, settings, url = self.pdf, self.target(), self.source(), self.settings, self.server_url

        def work():
            try:
                result = translate_pdf(pdf, lang, settings, source=source, server_url=url, keep_terms=keep,
                                       on_progress=lambda d, t: self.bridge.progress.emit(d, t),
                                       should_stop=lambda: self.pause_requested)
                self.bridge.done.emit(("translate", result))
            except Exception as e:
                (paths.logs_dir() / "last-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                self.bridge.failed.emit(f"Translation stopped: {e}")

        threading.Thread(target=work, daemon=True).start()

    # --- worker callbacks --------------------------------------------------------------------------------------
    def _on_progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        # Live estimate from the speed of this run, once enough parts are done to be meaningful.
        now = time.monotonic()
        if self._run_first is None:
            self._run_first, self._run_start = done, now
        left = ""
        finished_now = done - self._run_first
        if finished_now >= 20 and done < total:
            rate = finished_now / (now - self._run_start)
            left = f" · {_fmt_minutes((total - done) / rate)} left"
        self.status.setText(f"Translated {done:,} of {total:,} parts{left}")

    def _on_stage(self, stage, done, total):
        if total > 1:
            self.setup_progress.setMaximum(1000)
            self.setup_progress.setValue(int(1000 * done / total))
            self.setup_status.setText(f"Downloading the {stage}: {done / 2**30:.2f} of {total / 2**30:.2f} GB")
        elif stage == "speed test":
            self.setup_progress.setMaximum(0)  # busy indicator
            self.setup_status.setText("Measuring this computer's speed (about a minute)…")
        elif total == 0 and done == 0:
            self.setup_status.setText(stage)

    def _on_done(self, payload):
        kind, value = payload
        if kind == "setup":
            self.settings = value
            self.setup_progress.setVisible(False)
            self._refresh()
            self.job_done.emit(value)
            return
        self.busy = False
        self.pause_button.setVisible(False)
        self.result = value
        if value["finished"]:
            self.status.setText(f"Done in {_fmt_minutes(value['seconds'])}. Saved next to the original PDF.")
            for b in (self.open_pdf_button, self.open_epub_button, self.open_folder_button):
                b.setEnabled(True)
        else:
            self.status.setText("Paused. Your progress is saved; press Resume to continue.")
        self._refresh()
        self.job_done.emit(value)

    def _on_failed(self, message):
        self.busy = False
        self.pause_button.setVisible(False)
        self.setup_button.setEnabled(True)
        self.status.setText(message)
        self.setup_status.setText(message)
        self._refresh()
        QMessageBox.warning(self, "Ratica", f"{message}\n\nDetails are in {paths.logs_dir()}")
        self.job_done.emit(None)

    def _open(self, path):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # --- drag and drop -----------------------------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".pdf"):
                self.open_pdf(u.toLocalFile())
                break

    def closeEvent(self, e):
        if self.busy:
            self.pause_requested = True  # progress is already saved paragraph by paragraph
        lifeline.stop_all()  # never leave the engine holding GPU memory
        super().closeEvent(e)


def main():
    lifeline.kill_orphans(paths.engines_dir())  # engines left behind by an earlier crash
    app = QApplication(sys.argv)
    app.setApplicationName("Ratica")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "icon.png")))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.resize(640, 720)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
