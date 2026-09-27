# PyInstaller spec: one-folder app (plus a .app bundle on macOS).
#   uv run --group build pyinstaller packaging/ratica.spec --noconfirm
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

HERE = Path(SPECPATH)
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
from ratica import __version__  # noqa: E402

datas = collect_data_files("pymupdf_fonts") + collect_data_files("ratica")
icon = str(HERE / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))

a = Analysis([str(HERE / "launch.py")], pathex=[str(ROOT / "src")], datas=datas,
             excludes=["tkinter", "pytest", "sacrebleu", "gguf"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Ratica", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="Ratica")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="Ratica.app", icon=icon, bundle_identifier="io.github.kaanncavdar.ratica",
                 version=__version__,
                 info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "12.0",
                             "CFBundleDocumentTypes": [{"CFBundleTypeName": "PDF document",
                                                        "LSItemContentTypes": ["com.adobe.pdf"],
                                                        "CFBundleTypeRole": "Viewer"}]})
