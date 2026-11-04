import asyncio
from datetime import datetime
from typing import Optional, List, Any, Dict
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, ListView, ListItem, Label, Input, Static
from textual.binding import Binding

from telethon import TelegramClient, events
from telethon.tl.types import User, Chat, Channel, Message as TelethonMsg

from .client import get_peer_title, resolve_peer
from .formatters import get_entity_type, get_media_info, format_timestamp


class ChatListItem(ListItem):
    """List item representing a Telegram chat / dialog."""

    def __init__(self, dialog: Any):
        super().__init__()
        self.dialog = dialog
        self.entity = dialog.entity
        self.chat_id = dialog.id
        self.title = get_peer_title(self.entity)
        self.entity_type = get_entity_type(self.entity)

    def compose(self) -> ComposeResult:
        unread = self.dialog.unread_count
        unread_str = f" [b red]({unread})[/]" if unread > 0 else ""
        
        last_text = ""
        last_date = ""
        if self.dialog.message:
            media = get_media_info(self.dialog.message)
            text = (self.dialog.message.message or "").replace("\n", " ").strip()
            if len(text) > 30:
                text = text[:28] + "..."
            last_text = f"{media} {text}".strip()
            if self.dialog.message.date:
                last_date = format_timestamp(self.dialog.message.date)

        first_line = f"{self.entity_type.split()[0]} [bold]{self.title}[/bold]{unread_str}"
        second_line = f"[dim]{last_date} {last_text}[/dim]" if last_text else f"[dim]{last_date}[/dim]"

        yield Label(first_line, classes="chat-item-header")
        yield Label(second_line, classes="chat-item-preview")


class MessageBubble(Static):
    """Widget representing a single message in the chat timeline."""

    def __init__(self, msg: TelethonMsg):
        super().__init__()
        self.msg = msg

    def compose(self) -> ComposeResult:
        is_out = self.msg.out
        time_str = format_timestamp(self.msg.date)
        sender_name = "You" if is_out else get_peer_title(self.msg.sender) if self.msg.sender else "Author"
        sender_color = "green" if is_out else "cyan"

        media_info = get_media_info(self.msg)
        body = self.msg.message or ""
        content = f"{media_info} {body}".strip() if media_info else body

        header = f"[bold {sender_color}]{sender_name}[/bold {sender_color}] [dim]• {time_str} • #{self.msg.id}[/dim]"
        text_markup = f"{header}\n{content}"

        classes = "message-bubble bubble-out" if is_out else "message-bubble bubble-in"
        yield Label(text_markup, classes=classes)


class TelegramTUI(App):
    """Full-screen interactive Terminal User Interface for Telegram."""

    CSS = """
    Screen {
        layout: horizontal;
    }

    #sidebar {
        width: 38;
        height: 100%;
        border-right: heavy cyan;
        background: #181825;
    }

    #sidebar-title {
        text-align: center;
        background: cyan;
        color: black;
        text-style: bold;
        padding: 1;
    }

    #chat-search {
        margin: 1 1 0 1;
        border: tall cyan;
    }

    #chat-list {
        height: 1fr;
        margin-top: 1;
    }

    ChatListItem {
        padding: 1;
        border-bottom: solid #313244;
    }

    ChatListItem:hover {
        background: #313244;
    }

    ChatListItem.-selected {
        background: cyan;
        color: black;
    }

    .chat-item-header {
        text-style: bold;
    }

    .chat-item-preview {
        color: #a6adc8;
    }

    #chat-pane {
        width: 1fr;
        height: 100%;
        background: #11111b;
    }

    #chat-header {
        height: 3;
        background: #181825;
        color: cyan;
        text-style: bold;
        padding: 1 2;
        border-bottom: solid cyan;
    }

    #messages-container {
        height: 1fr;
        padding: 1 2;
    }

    .message-bubble {
        margin-bottom: 1;
        padding: 0 1;
        max-width: 85%;
    }

    .bubble-out {
        background: #1b3820;
        border: round green;
        margin-left: 6;
    }

    .bubble-in {
        background: #181825;
        border: round cyan;
        margin-right: 6;
    }

    #input-container {
        height: 4;
        background: #181825;
        padding: 0 1;
        border-top: solid cyan;
    }

    #message-input {
        width: 100%;
        border: tall cyan;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh_chats", "Refresh", show=True),
        Binding("slash", "focus_search", "Search", show=True),
        Binding("tab", "switch_focus", "Switch Focus", show=True),
        Binding("escape", "blur_input", "Back to Chats", show=True),
    ]

    def __init__(self, client: TelegramClient):
        super().__init__()
        self.client = client
        self.current_dialog = None
        self.all_dialogs: List[Any] = []
        self.active_listener = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("💬 TELEGRAM CHATS", id="sidebar-title")
                yield Input(placeholder="🔍 Search chats...", id="chat-search")
                yield ListView(id="chat-list")
            with Vertical(id="chat-pane"):
                yield Label("Select a chat from the sidebar to start reading & chatting", id="chat-header")
                yield VerticalScroll(id="messages-container")
                with Horizontal(id="input-container"):
                    yield Input(placeholder="Write a message... (Press Enter to send)", id="message-input")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the TUI is first launched."""
        self.title = "TG-CLI Terminal"
        self.sub_title = "Modern Telegram TUI"

        # Load dialogs
        await self.load_dialogs()

        # Global event listener for incoming messages
        @self.client.on(events.NewMessage)
        async def on_incoming_message(event):
            await self.handle_incoming_message(event)

        self.active_listener = on_incoming_message

    async def load_dialogs(self, query: Optional[str] = None) -> None:
        chat_list = self.query_one("#chat-list", ListView)
        await chat_list.clear()

        if not self.all_dialogs or not query:
            try:
                self.all_dialogs = await self.client.get_dialogs(limit=100)
            except Exception as e:
                self.notify(f"Error loading chats: {e}", severity="error")
                return

        filtered = self.all_dialogs
        if query:
            q = query.lower()
            filtered = [
                d for d in self.all_dialogs
                if q in (get_peer_title(d.entity) or "").lower() or q in (getattr(d.entity, "username", "") or "").lower()
            ]

        for d in filtered:
            await chat_list.append(ChatListItem(d))

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Filters the chat list as the user types in the search box."""
        if event.input.id == "chat-search":
            await self.load_dialogs(query=event.value.strip())

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Triggered when a user clicks or presses Enter on a chat item."""
        if isinstance(event.item, ChatListItem):
            await self.open_chat(event.item.dialog)

    async def open_chat(self, dialog: Any) -> None:
        self.current_dialog = dialog
        chat_title = get_peer_title(dialog.entity)
        username = f" (@{dialog.entity.username})" if getattr(dialog.entity, "username", None) else ""
        
        header = self.query_one("#chat-header", Label)
        header.update(f"💬 {chat_title}{username}")

        messages_container = self.query_one("#messages-container", VerticalScroll)
        await messages_container.remove_children()

        try:
            # Fetch recent 35 messages
            messages = await self.client.get_messages(dialog.entity, limit=35)
            for msg in reversed(messages):
                await messages_container.mount(MessageBubble(msg))
            
            # Scroll to end
            messages_container.scroll_end(animate=False)
        except Exception as e:
            self.notify(f"Failed to load messages: {e}", severity="error")

        # Focus message input
        self.query_one("#message-input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Sends a message when Enter is pressed in #message-input."""
        if event.input.id == "message-input":
            text = event.value.strip()
            if not text:
                return

            if not self.current_dialog:
                self.notify("No chat selected! Pick a chat first.", severity="warning")
                return

            event.input.value = ""

            try:
                sent_msg = await self.client.send_message(self.current_dialog.entity, text)
                messages_container = self.query_one("#messages-container", VerticalScroll)
                await messages_container.mount(MessageBubble(sent_msg))
                messages_container.scroll_end(animate=False)
            except Exception as e:
                self.notify(f"Send failed: {e}", severity="error")

    async def handle_incoming_message(self, event: Any) -> None:
        msg = event.message
        # If currently open chat received message, display it
        if self.current_dialog and msg.chat_id == self.current_dialog.id:
            messages_container = self.query_one("#messages-container", VerticalScroll)
            await messages_container.mount(MessageBubble(msg))
            messages_container.scroll_end(animate=False)
        else:
            # Update unread / preview in sidebar
            self.notify(f"New message from {get_peer_title(await event.get_chat())}", title="Telegram")

    async def action_quit(self) -> None:
        if self.active_listener:
            self.client.remove_event_handler(self.active_listener)
        self.exit()

    async def action_refresh_chats(self) -> None:
        self.notify("Refreshing dialogs...", severity="information")
        self.all_dialogs = []
        await self.load_dialogs()

    def action_focus_search(self) -> None:
        self.query_one("#chat-search", Input).focus()

    def action_switch_focus(self) -> None:
        chat_list = self.query_one("#chat-list", ListView)
        msg_input = self.query_one("#message-input", Input)
        if chat_list.has_focus:
            msg_input.focus()
        else:
            chat_list.focus()

    def action_blur_input(self) -> None:
        self.query_one("#chat-list", ListView).focus()
