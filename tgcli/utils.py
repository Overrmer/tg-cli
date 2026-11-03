import sys
import os
from pathlib import Path
from typing import Optional, Callable
from rich.console import Console
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn, TextColumn
from telethon import TelegramClient
from telethon.tl.types import Message

from .config import load_config, DOWNLOADS_DIR


def get_progress_bar(description: str = "Transferring") -> Progress:
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    )


async def download_message_media(
    client: TelegramClient,
    message: Message,
    output_path: Optional[str] = None,
    console: Optional[Console] = None,
) -> Path:
    """
    Downloads media attached to a message with a progress bar.
    """
    if not message.media:
        raise ValueError(f"Message #{message.id} does not contain any media attachment.")

    cfg = load_config()
    default_dir = Path(cfg.get("downloads_dir", DOWNLOADS_DIR))
    default_dir.mkdir(parents=True, exist_ok=True)

    target: Optional[Path] = None
    if output_path:
        target = Path(output_path)
        if target.is_dir():
            target = target  # Telethon will choose filename inside target directory
    else:
        target = default_dir

    with get_progress_bar("Downloading") as progress:
        task = progress.add_task("Download", total=None)

        def progress_callback(current: int, total: int):
            if progress.tasks[task].total is None and total:
                progress.update(task, total=total)
            progress.update(task, completed=current)

        saved_path = await client.download_media(
            message,
            file=str(target),
            progress_callback=progress_callback,
        )

    if not saved_path:
        raise RuntimeError("Media download failed or resulted in empty file.")

    return Path(saved_path)


async def upload_file_with_progress(
    client: TelegramClient,
    entity: any,
    file_path: str,
    caption: str = "",
    as_document: bool = False,
    console: Optional[Console] = None,
) -> Message:
    """
    Uploads a file or media to Telegram with an active progress bar.
    """
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    file_size = path.stat().st_size

    with get_progress_bar(f"Uploading {path.name}") as progress:
        task = progress.add_task("Upload", total=file_size)

        def progress_callback(current: int, total: int):
            progress.update(task, completed=current)

        msg = await client.send_file(
            entity,
            str(path),
            caption=caption,
            force_document=as_document,
            progress_callback=progress_callback,
        )

    return msg


def read_stdin_if_available() -> Optional[str]:
    """Reads all input from standard input if piped or redirected."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return None
