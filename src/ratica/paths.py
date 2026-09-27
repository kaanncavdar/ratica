"""Where Ratica keeps its engine, model, settings and logs on each operating system."""
import os
import platform
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("RATICA_HOME")
    if override:
        base = Path(override)
    elif platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Ratica"
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Ratica"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ratica"
    base.mkdir(parents=True, exist_ok=True)
    return base


def engines_dir() -> Path:
    return data_dir() / "engines"


def models_dir() -> Path:
    return data_dir() / "models"


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"
