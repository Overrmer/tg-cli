import sys
import asyncio
import json
from pathlib import Path
from typing import Optional, List
import typer
from rich.console import Console
from rich.prompt import Prompt

from telethon import events
from telethon.tl.types import User, Chat, Channel

from . import __version__, __app_name__
from .config import load_config, update_config, get_session_path, SESSIONS_DIR
from .client import get_client, resolve_peer, get_peer_title
from .auth import do_qr_login, do_phone_login, do_bot_login, do_logout
from .formatters import (
    print_dialogs_table,
    print_message_line,
    print_user_profile,
    serialize_entity,
    serialize_message,
)
from .utils import download_message_media, upload_file_with_progress, read_stdin_if_available
from .interactive import run_interactive_chat

app = typer.Typer(
    name="tg",
    help="⚡ Modern, blazing-fast Telegram CLI client for terminals, scripting and automation.",
    add_completion=True,
    no_args_is_help=True,
)
console = Console()


def run_async(coro):
    """Utility to run an async coroutine synchronously."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/yellow]")
        sys.exit(0)


async def check_auth_or_exit(client) -> User:
    await client.connect()
    if not await client.is_user_authorized():
        console.print("[bold red]Not logged in![/bold red] Please run [bold cyan]tg login[/bold cyan] first.")
        await client.disconnect()
        sys.exit(1)
    return await client.get_me()


@app.command(name="login")
def login(
    qr: bool = typer.Option(False, "--qr", help="Log in by scanning a QR code with your Telegram mobile app."),
    phone: Optional[str] = typer.Option(None, "--phone", "-p", help="Phone number with country code (e.g. +79991234567)."),
    bot_token: Optional[str] = typer.Option(None, "--bot-token", "-b", help="Log in as a Telegram Bot using its Bot Token."),
    api_id: Optional[int] = typer.Option(None, "--api-id", help="Custom Telegram API ID from my.telegram.org"),
    api_hash: Optional[str] = typer.Option(None, "--api-hash", help="Custom Telegram API Hash from my.telegram.org"),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name (default: 'default')"),
):
    """
    Authenticate your Telegram account or bot.
    Supports QR code login (default recommended), SMS/Telegram code, or Bot Token.
    """
    if api_id or api_hash:
        update_config(api_id=api_id, api_hash=api_hash)
    if session:
        update_config(active_session=session)

    async def _login():
        client = get_client(session_name=session, api_id=api_id, api_hash=api_hash)
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            console.print(f"[bold green]Already logged in as {me.first_name} (@{me.username})[/bold green]")
            await client.disconnect()
            return

        success = False
        if bot_token:
            success = await do_bot_login(client, console, bot_token)
        elif phone:
            success = await do_phone_login(client, console, phone=phone)
        elif qr:
            success = await do_qr_login(client, console)
        else:
            # Interactive choice
            console.print("[bold cyan]Choose Telegram login method:[/bold cyan]")
            console.print("  [1] QR Code (Fastest & easiest, scan with phone)")
            console.print("  [2] Phone number (Receive code in Telegram or SMS)")
            console.print("  [3] Bot Token (Run as a Telegram bot)")
            choice = Prompt.ask("Select option", choices=["1", "2", "3"], default="1")
            
            if choice == "1":
                success = await do_qr_login(client, console)
            elif choice == "2":
                success = await do_phone_login(client, console)
            elif choice == "3":
                token = Prompt.ask("Enter Bot Token")
                success = await do_bot_login(client, console, token)

        await client.disconnect()
        if success:
            console.print("\n[bold green]✨ Authentication complete! Run [cyan]tg me[/cyan] or [cyan]tg chats[/cyan] to get started.[/bold green]")

    run_async(_login())


@app.command(name="logout")
def logout(
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name to log out."),
):
    """Log out and remove stored session files."""
    async def _logout():
        client = get_client(session_name=session)
        await client.connect()
        await do_logout(client, console, session_name=session)
        await client.disconnect()

    run_async(_logout())


@app.command(name="me")
def me(
    json_output: bool = typer.Option(False, "--json", help="Output information as JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """Display information about the currently authenticated user/bot."""
    async def _me():
        client = get_client(session_name=session)
        user = await check_auth_or_exit(client)
        if json_output:
            console.print(json.dumps(serialize_entity(user), indent=2, ensure_ascii=False))
        else:
            print_user_profile(user, console)
        await client.disconnect()

    run_async(_me())


@app.command(name="chats")
def chats(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of chats to display."),
    unread_only: bool = typer.Option(False, "--unread", "-u", help="Only show chats with unread messages."),
    filter_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Filter by type: user, group, channel, bot."
    ),
    search_query: Optional[str] = typer.Option(None, "--search", "-q", help="Filter chats by title/username query."),
    json_output: bool = typer.Option(False, "--json", help="Output dialogs as JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """List recent chats, groups, channels and bots with unread counts."""
    async def _chats():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        dialogs = []
        async for d in client.iter_dialogs(limit=200):
            if unread_only and d.unread_count == 0:
                continue

            entity = d.entity
            if filter_type:
                ft = filter_type.lower()
                if ft == "user" and (not isinstance(entity, User) or getattr(entity, "bot", False)):
                    continue
                elif ft == "bot" and (not isinstance(entity, User) or not getattr(entity, "bot", False)):
                    continue
                elif ft == "group" and not isinstance(entity, Chat) and not (isinstance(entity, Channel) and not getattr(entity, "broadcast", False)):
                    continue
                elif ft == "channel" and not (isinstance(entity, Channel) and getattr(entity, "broadcast", False)):
                    continue

            if search_query:
                sq = search_query.lower()
                title = (get_peer_title(entity) or "").lower()
                username = (getattr(entity, "username", "") or "").lower()
                if sq not in title and sq not in username:
                    continue

            dialogs.append(d)
            if len(dialogs) >= limit:
                break

        if json_output:
            out = []
            for d in dialogs:
                item = serialize_entity(d.entity)
                item["unread_count"] = d.unread_count
                if d.message:
                    item["last_message"] = serialize_message(d.message)
                out.append(item)
            console.print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            print_dialogs_table(dialogs, console)

        await client.disconnect()

    run_async(_chats())


@app.command(name="read")
def read(
    peer: str = typer.Argument(..., help="Peer identifier: username (@user), phone (+...), ID, or 'me'."),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of messages to retrieve."),
    reverse: bool = typer.Option(True, "--reverse/--no-reverse", help="Show oldest messages first (chronological order)."),
    json_output: bool = typer.Option(False, "--json", help="Output messages as JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """Read message history from a chat, group, channel, or Saved Messages."""
    async def _read():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Error resolving peer '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        chat_title = get_peer_title(entity)
        messages = await client.get_messages(entity, limit=limit)

        if reverse:
            messages = list(reversed(messages))

        if json_output:
            out = [serialize_message(m, chat_title=chat_title) for m in messages]
            console.print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            console.print(f"[bold magenta]📖 History for {chat_title} ({len(messages)} messages):[/bold magenta]\n")
            for m in messages:
                print_message_line(m, console, show_chat=False)

        await client.disconnect()

    run_async(_read())


@app.command(name="send")
def send(
    peer: str = typer.Argument(..., help="Recipient: username (@user), phone (+...), chat ID, or 'me'."),
    message: Optional[str] = typer.Argument(None, help="Text message to send. If '-' or omitted, reads from stdin."),
    reply_to: Optional[int] = typer.Option(None, "--reply-to", "-r", help="Message ID to reply to."),
    silent: bool = typer.Option(False, "--silent", help="Send silently without notifying recipient."),
    json_output: bool = typer.Option(False, "--json", help="Output sent message details as JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """
    Send a text message to a user, group, channel or Saved Messages.
    Supports stdin piping: `echo "Hello" | tg send me`
    """
    # Check if text comes from stdin
    if not message or message == "-":
        stdin_text = read_stdin_if_available()
        if stdin_text:
            message = stdin_text
        elif not message:
            console.print("[bold red]Error: No message provided and standard input is empty.[/bold red]")
            sys.exit(1)

    async def _send():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Error resolving peer '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        chat_title = get_peer_title(entity)
        msg = await client.send_message(entity, message, reply_to=reply_to, silent=silent)

        if json_output:
            console.print(json.dumps(serialize_message(msg, chat_title=chat_title), indent=2, ensure_ascii=False))
        else:
            console.print(f"[bold green]✓ Message sent to {chat_title} (ID: #{msg.id})[/bold green]")

        await client.disconnect()

    run_async(_send())


@app.command(name="send-file")
def send_file(
    peer: str = typer.Argument(..., help="Recipient: username, ID, or 'me'."),
    file_path: str = typer.Argument(..., help="Path to the file, image, video or document."),
    caption: str = typer.Option("", "--caption", "-c", help="Optional text caption for the file."),
    as_document: bool = typer.Option(False, "--doc", help="Force sending as document without compression."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """Upload and send a file, image, audio, or document to Telegram."""
    async def _send_file():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Error resolving peer '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        chat_title = get_peer_title(entity)
        try:
            msg = await upload_file_with_progress(
                client, entity, file_path, caption=caption, as_document=as_document, console=console
            )
            console.print(f"[bold green]✓ Successfully uploaded {file_path} to {chat_title} (ID: #{msg.id})[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Upload failed:[/bold red] {e}")

        await client.disconnect()

    run_async(_send_file())


@app.command(name="download")
def download(
    peer: str = typer.Argument(..., help="Peer containing the message."),
    message_id: int = typer.Argument(..., help="Message ID containing media/file."),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Output file path or directory."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """Download photos, documents, audio or video attachments from a message."""
    async def _download():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Error resolving peer '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        msg = await client.get_messages(entity, ids=message_id)
        if not msg:
            console.print(f"[bold red]Message #{message_id} not found.[/bold red]")
            await client.disconnect()
            sys.exit(1)

        try:
            saved_path = await download_message_media(client, msg, output_path=out, console=console)
            console.print(f"[bold green]✓ Downloaded to: {saved_path}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Download failed:[/bold red] {e}")

        await client.disconnect()

    run_async(_download())


@app.command(name="stream")
def stream(
    peer: Optional[str] = typer.Option(None, "--peer", "-p", help="Optional specific peer to watch."),
    json_output: bool = typer.Option(False, "--json", help="Output live events as raw JSON lines."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """
    Live stream/tail incoming messages in real-time (like `tail -f`).
    Watches all chats or a specific chat.
    """
    async def _stream():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        filter_chat = None
        filter_title = "All Chats"
        if peer:
            try:
                filter_chat = await resolve_peer(client, peer)
                filter_title = get_peer_title(filter_chat)
            except Exception as e:
                console.print(f"[bold red]Error resolving peer '{peer}':[/bold red] {e}")
                await client.disconnect()
                sys.exit(1)

        if not json_output:
            console.print(f"[bold cyan]⚡ Live streaming incoming messages from [yellow]{filter_title}[/yellow] (Ctrl+C to stop)...[/bold cyan]\n")

        chat_cache = {}

        @client.on(events.NewMessage(chats=filter_chat))
        async def on_new_message(event):
            msg = event.message
            chat_id = msg.chat_id
            if chat_id not in chat_cache:
                chat = await event.get_chat()
                chat_cache[chat_id] = get_peer_title(chat) if chat else str(chat_id)
            title = chat_cache[chat_id]

            if json_output:
                print(json.dumps(serialize_message(msg, chat_title=title), ensure_ascii=False), flush=True)
            else:
                print_message_line(msg, console, show_chat=True, chat_title=title)

        try:
            await client.run_until_disconnected()
        except KeyboardInterrupt:
            console.print("\n[yellow]Stream stopped.[/yellow]")
        finally:
            await client.disconnect()

    run_async(_stream())


@app.command(name="chat")
def chat(
    peer: str = typer.Argument(..., help="Peer identifier to open chat session with: username, phone, ID, or 'me'."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """Launch full-duplex interactive terminal chat session with a user or group."""
    async def _chat():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)
        await run_interactive_chat(client, peer, console)
        await client.disconnect()

    run_async(_chat())


@app.command(name="search")
def search(
    query: str = typer.Argument(..., help="Search query string."),
    peer: Optional[str] = typer.Option(None, "--peer", "-p", help="Search only within this peer/chat."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results to return."),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Session name."),
):
    """Search messages by keyword globally or inside a specific chat."""
    async def _search():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        entity = None
        if peer:
            try:
                entity = await resolve_peer(client, peer)
            except Exception as e:
                console.print(f"[bold red]Error resolving peer '{peer}':[/bold red] {e}")
                await client.disconnect()
                sys.exit(1)

        results = []
        async for msg in client.iter_messages(entity, search=query, limit=limit):
            results.append(msg)

        if json_output:
            out = [serialize_message(m) for m in results]
            console.print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            console.print(f"[bold cyan]🔍 Found {len(results)} messages matching '{query}':[/bold cyan]\n")
            for m in results:
                print_message_line(m, console, show_chat=True)

        await client.disconnect()

    run_async(_search())


@app.command(name="config")
def config_cmd(
    api_id: Optional[int] = typer.Option(None, "--api-id", help="Set Telegram API ID."),
    api_hash: Optional[str] = typer.Option(None, "--api-hash", help="Set Telegram API Hash."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Set active session name."),
    downloads_dir: Optional[str] = typer.Option(None, "--downloads-dir", help="Set default downloads folder."),
):
    """View or update configuration settings."""
    if any([api_id, api_hash, session, downloads_dir]):
        cfg = update_config(
            api_id=api_id,
            api_hash=api_hash,
            active_session=session,
            downloads_dir=downloads_dir,
        )
        console.print("[bold green]✓ Configuration updated successfully![/bold green]")
    else:
        cfg = load_config()

    # Display configuration
    console.print("\n[bold cyan]Current TG-CLI Configuration:[/bold cyan]")
    masked_hash = cfg.get("api_hash", "")
    if len(masked_hash) > 8:
        masked_hash = masked_hash[:4] + "..." + masked_hash[-4:]
    console.print(f"  [bold]API ID:[/bold] {cfg.get('api_id')}")
    console.print(f"  [bold]API Hash:[/bold] {masked_hash}")
    console.print(f"  [bold]Active Session:[/bold] {cfg.get('active_session')}")
    console.print(f"  [bold]Downloads Dir:[/bold] {cfg.get('downloads_dir')}")
    console.print(f"  [bold]Sessions Folder:[/bold] {SESSIONS_DIR}\n")


@app.command(name="version")
def version():
    """Show version information."""
    console.print(f"[bold cyan]{__app_name__}[/bold cyan] version [bold green]{__version__}[/bold green]")


def main():
    app()


if __name__ == "__main__":
    main()
