import os
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

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
        "api_id": int(env_api_id) if env_api_id and env_api_id.isdigit() else None,
        "api_hash": env_api_hash if env_api_hash else None,
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
    return str(SESSIONS_DIR / session_name)


def is_credentials_valid() -> bool:
    cfg = load_config()
    api_id = cfg.get("api_id")
    api_hash = cfg.get("api_hash")
    # 2040 was Telegram Desktop old key which is blocked for 3rd party apps
    if not api_id or not api_hash or api_id == 2040:
        return False
    return True


def prompt_credentials(console: Console) -> Tuple[int, str]:
    """Prompts the user to enter their personal Telegram api_id and api_hash."""
    instructions = (
        "[bold yellow]Telegram требует личный API ID и API Hash для работы сторонних клиентов.[/bold yellow]\n\n"
        "[white]Получить их можно бесплатно за 1 минуту:[/white]\n"
        "  1. Открой в браузере: [bold cyan]https://my.telegram.org[/bold cyan]\n"
        "  2. Авторизуйся своим номером телефона (код придет в Telegram)\n"
        "  3. Нажми [bold green]API development tools[/bold green]\n"
        "  4. Заполни любое имя приложения (например: [cyan]my-tg-cli[/cyan]) и нажми [bold green]Create application[/bold green]\n"
        "  5. Скопируй [bold]App api_id[/bold] и [bold]App api_hash[/bold]"
    )
    console.print(Panel(instructions, title="🔑 Telegram API Credentials", border_style="yellow"))

    while True:
        api_id_raw = Prompt.ask("[bold cyan]Введи App api_id (число)[/bold cyan]").strip()
        if api_id_raw.isdigit():
            api_id = int(api_id_raw)
            break
        console.print("[red]API ID должен состоять только из цифр. Попробуй ещё раз.[/red]")

    while True:
        api_hash = Prompt.ask("[bold cyan]Введи App api_hash (32-значная строка)[/bold cyan]").strip()
        if len(api_hash) >= 16:
            break
        console.print("[red]API Hash слишком короткий. Проверь строку на my.telegram.org.[/red]")

    update_config(api_id=api_id, api_hash=api_hash)
    console.print("[bold green]✓ Ключи сохранены в ~/.tgcli/config.json![/bold green]\n")
    return api_id, api_hash
