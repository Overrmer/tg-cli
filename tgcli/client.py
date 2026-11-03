import asyncio
import logging
import sys
from typing import Optional, Union, Any
from telethon import TelegramClient
from telethon.tl.types import User, Chat, Channel
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PasswordHashInvalidError,
    FloodWaitError,
)

from .config import load_config, get_session_path

# Suppress telethon debug logs unless verbose
logging.getLogger("telethon").setLevel(logging.WARNING)


def get_client(
    session_name: Optional[str] = None,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
) -> TelegramClient:
    cfg = load_config()
    final_api_id = int(api_id or cfg.get("api_id"))
    final_api_hash = str(api_hash or cfg.get("api_hash"))
    session_path = get_session_path(session_name or cfg.get("active_session", "default"))

    client = TelegramClient(
        session_path,
        api_id=final_api_id,
        api_hash=final_api_hash,
        device_model=cfg.get("device_model", "PC 64bit"),
        system_version=cfg.get("system_version", "Windows 11"),
        app_version=cfg.get("app_version", "1.0.0"),
    )
    return client


async def resolve_peer(client: TelegramClient, peer: Union[str, int]) -> Any:
    """
    Intelligently resolves a peer identifier into a Telegram entity.
    Supports:
    - 'me', 'saved' -> Saved Messages
    - Username (@username or username)
    - Phone number (+123456789)
    - Numeric ID (123456, -100123456)
    - Chat/User display name (case-insensitive search in active dialogs)
    """
    if isinstance(peer, int):
        return await client.get_entity(peer)

    peer_str = str(peer).strip()
    if peer_str.lower() in ("me", "self", "saved", "saved messages"):
        return await client.get_me()

    # Try integer parsing (positive or negative)
    try:
        int_id = int(peer_str)
        return await client.get_entity(int_id)
    except (ValueError, TypeError):
        pass

    # Try direct resolution (for @username, t.me link, or phone number)
    try:
        return await client.get_entity(peer_str)
    except Exception:
        pass

    # If starts without @, try with @
    if not peer_str.startswith("@") and not peer_str.startswith("+"):
        try:
            return await client.get_entity(f"@{peer_str}")
        except Exception:
            pass

    # Fallback: search in cached/active dialogs by name/title
    lower_peer = peer_str.lower()
    async for dialog in client.iter_dialogs(limit=200):
        # Exact match first
        if dialog.name and dialog.name.lower() == lower_peer:
            return dialog.entity
        entity = dialog.entity
        if isinstance(entity, User):
            if entity.username and entity.username.lower() == lower_peer:
                return entity
            full_name = f"{entity.first_name or ''} {entity.last_name or ''}".strip().lower()
            if full_name == lower_peer:
                return entity

    # Substring match if exact match wasn't found
    async for dialog in client.iter_dialogs(limit=200):
        if dialog.name and lower_peer in dialog.name.lower():
            return dialog.entity

    raise ValueError(f"Chat or user '{peer_str}' not found in your Telegram dialogs or contacts.")


def get_peer_title(entity: Any) -> str:
    """Returns a readable name for a user, chat, or channel."""
    if isinstance(entity, User):
        if entity.is_self:
            return "Saved Messages"
        parts = [entity.first_name or "", entity.last_name or ""]
        name = " ".join(p for p in parts if p).strip()
        if not name:
            name = entity.username or f"User {entity.id}"
        return name
    elif isinstance(entity, (Chat, Channel)):
        return entity.title or f"Chat {entity.id}"
    elif hasattr(entity, "title"):
        return entity.title
    elif hasattr(entity, "name"):
        return entity.name
    return str(getattr(entity, "id", "Unknown"))
