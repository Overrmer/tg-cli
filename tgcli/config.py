import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

# Default fallback credentials (Telegram Desktop public official client values)
DEFAULT_API_ID = 2040
DEFAULT_API_HASH = "b18441a2976048749e368e764d30e070"

CONFIG_DIR = Path.home() / ".tgcli"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_DIR = CONFIG_DIR / "sessions"
DOWNLOADS_DIR = CONFIG_DIR / "downloads"


def ensure_directories():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_default_config() -> Dict[str, Any]:
    return {
        "api_id": int(os.environ.get("TG_API_ID", DEFAULT_API_ID)),
        "api_hash": os.environ.get("TG_API_HASH", DEFAULT_API_HASH),
        "active_session": "default",
        "downloads_dir": str(DOWNLOADS_DIR),
        "default_limit": 20,
        "device_model": "PC 64bit",
        "system_version": "Windows 11",
        "app_version": "1.0.0",
    }


def load_config() -> Dict[str, Any]:
    ensure_directories()
    if not CONFIG_FILE.exists():
        cfg = get_default_config()
        save_config(cfg)
        return cfg

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge with defaults for any missing keys
            defaults = get_default_config()
            defaults.update(data)
            return defaults
    except Exception:
        return get_default_config()


def save_config(cfg: Dict[str, Any]) -> None:
    ensure_directories()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def update_config(**kwargs) -> Dict[str, Any]:
    cfg = load_config()
    for k, v in kwargs.items():
        if v is not None:
            if k == "api_id":
                try:
                    v = int(v)
                except ValueError:
                    pass
            cfg[k] = v
    save_config(cfg)
    return cfg


def get_session_path(session_name: Optional[str] = None) -> str:
    ensure_directories()
    if not session_name:
        cfg = load_config()
        session_name = cfg.get("active_session", "default")
    # Return absolute path without .session suffix (Telethon adds .session automatically)
    return str(SESSIONS_DIR / session_name)
