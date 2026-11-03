import json
from datetime import datetime
from typing import List, Any, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from telethon.tl.types import (
    User,
    Chat,
    Channel,
    Message,
    MessageMediaPhoto,
    MessageMediaDocument,
    DocumentAttributeFilename,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    DocumentAttributeSticker,
)

from .client import get_peer_title


def format_timestamp(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    local_dt = dt.astimezone()
    today = datetime.now().astimezone().date()
    if local_dt.date() == today:
        return local_dt.strftime("%H:%M:%S")
    return local_dt.strftime("%Y-%m-%d %H:%M")


def get_entity_type(entity: Any) -> str:
    if isinstance(entity, User):
        if getattr(entity, "bot", False):
            return "🤖 Bot"
        if getattr(entity, "is_self", False):
            return "💾 Saved"
        return "👤 User"
    elif isinstance(entity, Chat):
        return "👥 Group"
    elif isinstance(entity, Channel):
        if getattr(entity, "broadcast", False):
            return "📢 Channel"
        return "👥 Supergroup"
    return "💬 Chat"


def get_media_info(message: Message) -> str:
    if not message.media:
        return ""
    
    media = message.media
    if isinstance(media, MessageMediaPhoto):
        return "[📷 Photo]"
    
    if isinstance(media, MessageMediaDocument) and hasattr(media, "document") and media.document:
        doc = media.document
        size_mb = doc.size / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{doc.size / 1024:.1f} KB"
        
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeSticker):
                emoji = getattr(attr, "alt", "")
                return f"[🍕 Sticker {emoji}]".strip()
            elif isinstance(attr, DocumentAttributeAudio):
                if getattr(attr, "voice", False):
                    dur = getattr(attr, "duration", 0)
                    return f"[🎤 Voice {dur}s, {size_str}]"
                title = getattr(attr, "title", "Audio")
                return f"[🎵 {title}, {size_str}]"
            elif isinstance(attr, DocumentAttributeVideo):
                dur = getattr(attr, "duration", 0)
                return f"[🎬 Video {dur}s, {size_str}]"
            elif isinstance(attr, DocumentAttributeFilename):
                return f"[📎 Document: {attr.file_name} ({size_str})]"
        return f"[📎 Document: {size_str}]"

    return "[📎 Media]"


def print_dialogs_table(dialogs: List[Any], console: Console):
    table = Table(title="💬 Telegram Chats & Dialogs", show_lines=True, header_style="bold magenta")
    table.add_column("ID", style="dim", width=14)
    table.add_column("Type", width=12)
    table.add_column("Title / Name", style="bold cyan")
    table.add_column("Username", style="yellow")
    table.add_column("Unread", justify="right", width=8)
    table.add_column("Last Message", style="white")
    table.add_column("Date", style="dim", width=14)

    for d in dialogs:
        entity = d.entity
        entity_id = str(d.id)
        entity_type = get_entity_type(entity)
        title = get_peer_title(entity)
        username = f"@{entity.username}" if getattr(entity, "username", None) else ""
        
        unread_str = ""
        if d.unread_count > 0:
            unread_str = f"[bold red]{d.unread_count}[/bold red]"

        last_msg = ""
        last_date = ""
        if d.message:
            last_date = format_timestamp(d.message.date)
            media_tag = get_media_info(d.message)
            text = (d.message.message or "").replace("\n", " ").strip()
            if len(text) > 40:
                text = text[:37] + "..."
            last_msg = f"{media_tag} {text}".strip()

        table.add_row(
            entity_id,
            entity_type,
            title,
            username,
            unread_str,
            last_msg,
            last_date,
        )

    console.print(table)


def print_message_line(msg: Message, console: Console, show_chat: bool = False, chat_title: str = ""):
    ts = format_timestamp(msg.date)
    sender = ""
    if msg.sender:
        sender = get_peer_title(msg.sender)
    elif msg.post_author:
        sender = msg.post_author
    elif msg.out:
        sender = "You"
    else:
        sender = "Unknown"

    color = "green" if msg.out else "cyan"
    media_tag = get_media_info(msg)
    body = msg.message or ""
    
    reply_tag = ""
    if msg.reply_to_msg_id:
        reply_tag = f" [dim](reply to #{msg.reply_to_msg_id})[/dim]"

    chat_prefix = f"[bold yellow][{chat_title}][/bold yellow] " if (show_chat and chat_title) else ""
    
    header = f"{chat_prefix}[dim]#{msg.id} [{ts}][/dim] [bold {color}]{sender}[/bold {color}]{reply_tag}:"
    content = f"{media_tag} {body}".strip()
    
    console.print(f"{header} {content}")


def serialize_entity(entity: Any) -> dict:
    return {
        "id": getattr(entity, "id", None),
        "type": get_entity_type(entity),
        "title": get_peer_title(entity),
        "username": getattr(entity, "username", None),
        "first_name": getattr(entity, "first_name", None),
        "last_name": getattr(entity, "last_name", None),
        "phone": getattr(entity, "phone", None),
        "bot": getattr(entity, "bot", False),
        "verified": getattr(entity, "verified", False),
        "premium": getattr(entity, "premium", False),
    }


def serialize_message(msg: Message, chat_title: str = "") -> dict:
    return {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "out": msg.out,
        "chat_id": msg.chat_id,
        "chat_title": chat_title,
        "sender_id": msg.sender_id,
        "sender_name": get_peer_title(msg.sender) if msg.sender else None,
        "reply_to_msg_id": msg.reply_to_msg_id,
        "text": msg.message or "",
        "media": get_media_info(msg) if msg.media else None,
    }


def print_user_profile(user: User, console: Console):
    title = f"👤 User Profile: {user.first_name} {user.last_name or ''}".strip()
    info_lines = [
        f"[bold]Name:[/bold] {user.first_name} {user.last_name or ''}",
        f"[bold]ID:[/bold] [yellow]{user.id}[/yellow]",
        f"[bold]Username:[/bold] @{user.username or 'none'}",
        f"[bold]Phone:[/bold] {user.phone or 'hidden'}",
        f"[bold]Premium:[/bold] {'⭐ Yes' if getattr(user, 'premium', False) else 'No'}",
        f"[bold]Bot:[/bold] {'🤖 Yes' if getattr(user, 'bot', False) else 'No'}",
        f"[bold]Verified:[/bold] {'✓ Yes' if getattr(user, 'verified', False) else 'No'}",
    ]
    console.print(Panel("\n".join(info_lines), title=title, border_style="bold green"))
