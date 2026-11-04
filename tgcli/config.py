import os
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# Tested working official Telegram keys (Telegram Android)
DEFAULT_API_ID = 17349
DEFAULT_API_HASH = "344583e45741c457fe1862106095a5eb"
DEFAULT_DEVICE_MODEL = "Samsung Galaxy S23"
DEFAULT_SYSTEM_VERSION = "Android 14"
DEFAULT_APP_VERSION = "10.0.0"

CONFIG_DIR = Path.home() / ".tgcli"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSIONS_DIR = CONFIG_DIR / "sessions"
DOWNLOADS_DIR = CONFIG_DIR / "downloads"


def ensure_directories():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def get_default_config() -> Dict[str, Any]:
    env_api_id = os.environ.get("TG_API_ID")
    env_api_hash = os.environ.get("TG_API_HASH")
    
    return {
        "api_id": int(env_api_id) if env_api_id and env_api_id.isdigit() else DEFAULT_API_ID,
        "api_hash": env_api_hash if env_api_hash else DEFAULT_API_HASH,
        "active_session": "default",
        "downloads_dir": str(DOWNLOADS_DIR),
        "default_limit": 20,
        "device_model": DEFAULT_DEVICE_MODEL,
        "system_version": DEFAULT_SYSTEM_VERSION,
        "app_version": DEFAULT_APP_VERSION,
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
            defaults = get_default_config()
            defaults.update(data)
            # If previous config had null or obsolete 2040, replace with working defaults
            if not defaults.get("api_id") or defaults.get("api_id") == 2040:
                defaults["api_id"] = DEFAULT_API_ID
                defaults["api_hash"] = DEFAULT_API_HASH
                defaults["device_model"] = DEFAULT_DEVICE_MODEL
                defaults["system_version"] = DEFAULT_SYSTEM_VERSION
                defaults["app_version"] = DEFAULT_APP_VERSION
                save_config(defaults)
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
    return str(SESSIONS_DIR / session_name)


def is_credentials_valid() -> bool:
    cfg = load_config()
    api_id = cfg.get("api_id")
    api_hash = cfg.get("api_hash")
    if not api_id or not api_hash or api_id == 2040:
        return False
    return True


def prompt_credentials(console: Console) -> Tuple[int, str]:
    """Prompts the user if they wish to enter their own Telegram api_id and api_hash."""
    instructions = (
        "[bold yellow]Вы можете использовать встроенные рабочие ключи Telegram или указать свои.[/bold yellow]\n\n"
        "[white]Если вы хотите ввести свои с my.telegram.org:[/white]\n"
        "  1. Открой в браузере: [bold cyan]https://my.telegram.org[/bold cyan]\n"
        "  2. Скопируй [bold]App api_id[/bold] и [bold]App api_hash[/bold]"
    )
    console.print(Panel(instructions, title="🔑 Telegram API Credentials", border_style="yellow"))

    api_id_raw = Prompt.ask("[bold cyan]Введи App api_id (Enter для встроенного рабочего ключа)[/bold cyan]", default=str(DEFAULT_API_ID)).strip()
    if api_id_raw.isdigit():
        api_id = int(api_id_raw)
    else:
        api_id = DEFAULT_API_ID

    api_hash = Prompt.ask("[bold cyan]Введи App api_hash[/bold cyan]", default=DEFAULT_API_HASH).strip()

    update_config(api_id=api_id, api_hash=api_hash)
    console.print("[bold green]✓ Ключи сохранены в ~/.tgcli/config.json![/bold green]\n")
    return api_id, api_hash
