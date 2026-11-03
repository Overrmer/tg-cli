import asyncio
import os
from pathlib import Path
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from telethon import TelegramClient, events
from telethon.tl.types import User, Message

from .client import get_peer_title
from .formatters import print_message_line


async def run_interactive_chat(client: TelegramClient, peer: str, console: Console):
    """
    Interactive full-duplex chat session with real-time incoming messages
    and prompt_toolkit command input.
    """
    from .client import resolve_peer

    try:
        entity = await resolve_peer(client, peer)
    except Exception as e:
        console.print(f"[bold red]Failed to find peer '{peer}':[/bold red] {e}")
        return

    chat_title = get_peer_title(entity)
    console.print(f"\n[bold green]=== Interactive Chat with {chat_title} ===[/bold green]")
    console.print("[dim]Type your message and press Enter. Commands: /file <path>, /history [n], /clear, /exit[/dim]\n")

    # Load and display recent messages
    messages = await client.get_messages(entity, limit=15)
    for msg in reversed(messages):
        print_message_line(msg, console, show_chat=False)

    console.print("[dim]------------------------------------------------[/dim]")

    # Event handler for incoming messages in this chat
    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        if not event.out:  # Avoid duplicating messages sent by this client session
            print_message_line(event.message, console, show_chat=False)

    session = PromptSession()

    try:
        with patch_stdout():
            while True:
                try:
                    user_input = await session.prompt_async(f"[{chat_title}] > ")
                except (KeyboardInterrupt, EOFError):
                    break

                line = user_input.strip()
                if not line:
                    continue

                if line.lower() in ("/exit", "/quit", "/q"):
                    break
                elif line.lower() == "/clear":
                    os.system("cls" if os.name == "nt" else "clear")
                    continue
                elif line.lower().startswith("/help"):
                    console.print("\n[bold cyan]Interactive Chat Commands:[/bold cyan]")
                    console.print("  /file <path> [caption] - Send a file, photo or document")
                    console.print("  /history [N]           - Show last N messages (default 15)")
                    console.print("  /clear                 - Clear the terminal screen")
                    console.print("  /exit, /quit, /q       - Leave interactive chat\n")
                    continue
                elif line.lower().startswith("/history"):
                    parts = line.split(maxsplit=1)
                    limit = 15
                    if len(parts) > 1 and parts[1].isdigit():
                        limit = int(parts[1])
                    msgs = await client.get_messages(entity, limit=limit)
                    console.print(f"\n[dim]--- Last {len(msgs)} messages ---[/dim]")
                    for m in reversed(msgs):
                        print_message_line(m, console, show_chat=False)
                    console.print("[dim]-----------------------------[/dim]\n")
                    continue
                elif line.lower().startswith("/file "):
                    parts = line.split(maxsplit=2)
                    file_path = parts[1].strip('"\'')
                    caption = parts[2] if len(parts) > 2 else ""
                    if not Path(file_path).exists():
                        console.print(f"[bold red]File not found:[/bold red] {file_path}")
                        continue
                    try:
                        console.print(f"[dim]Uploading {file_path}...[/dim]")
                        await client.send_file(entity, file_path, caption=caption)
                        console.print(f"[bold green]✓ Sent file {file_path}[/bold green]")
                    except Exception as e:
                        console.print(f"[bold red]Failed to send file:[/bold red] {e}")
                    continue

                # Standard message send
                try:
                    sent_msg = await client.send_message(entity, line)
                    # Display our outgoing message
                    print_message_line(sent_msg, console, show_chat=False)
                except Exception as e:
                    console.print(f"[bold red]Failed to send message:[/bold red] {e}")

    finally:
        client.remove_event_handler(handler)
        console.print(f"\n[bold yellow]Left chat with {chat_title}.[/bold yellow]")
