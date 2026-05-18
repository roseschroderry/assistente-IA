import os
import shutil
import sys


APP_NAME = "AssistenteElite"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> str:
    if is_frozen():
        return os.path.abspath(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def exe_dir() -> str:
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return bundle_dir()


def data_dir() -> str:
    base = os.getenv("ELITE_DATA_DIR")
    if not base:
        base = os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return os.path.abspath(base)


def logs_dir() -> str:
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def observations_dir() -> str:
    path = os.path.join(data_dir(), "observations")
    os.makedirs(path, exist_ok=True)
    return path


def core_dir() -> str:
    path = os.path.join(data_dir(), "core")
    os.makedirs(path, exist_ok=True)
    return path


def user_files_dir() -> str:
    path = os.path.join(data_dir(), "files")
    os.makedirs(path, exist_ok=True)
    return path


def db_path() -> str:
    path = os.path.join(data_dir(), "memory.db")
    legacy = os.path.join(bundle_dir(), "memory.db")
    if not os.path.exists(path) and os.path.exists(legacy):
        try:
            shutil.copy2(legacy, path)
        except Exception:
            pass
    return path


def log_path(name: str) -> str:
    safe_name = os.path.basename(name)
    return os.path.join(logs_dir(), safe_name)


def runtime_summary() -> dict:
    return {
        "frozen": is_frozen(),
        "bundle_dir": bundle_dir(),
        "exe_dir": exe_dir(),
        "data_dir": data_dir(),
        "logs_dir": logs_dir(),
        "db_path": db_path(),
    }
