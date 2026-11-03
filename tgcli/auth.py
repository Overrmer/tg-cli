import io
import os
import asyncio
from typing import Optional
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)
import qrcode

from .config import get_session_path, SESSIONS_DIR, load_config, save_config


async def do_qr_login(client: TelegramClient, console: Console) -> bool:
    """Performs QR code login displaying ASCII QR code in terminal."""
    console.print("\n[bold cyan]Initiating QR Code Login...[/bold cyan]")
    
    try:
        qr_login = await client.qr_login()
    except Exception as e:
        console.print(f"[bold red]Failed to request QR code login:[/bold red] {e}")
        return False

    def print_qr(url: str):
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        console.print(buf.getvalue())
        console.print("[bold yellow]1. Open Telegram on your phone[/bold yellow]")
        console.print("[bold yellow]2. Go to Settings -> Devices -> Link Desktop Device[/bold yellow]")
        console.print("[bold yellow]3. Scan the QR code above.[/bold yellow]\n")

    print_qr(qr_login.url)

    try:
        with console.status("[bold green]Waiting for scan in Telegram app...[/bold green]"):
            user = await qr_login.wait()
            console.print(f"[bold green]✓ Successfully authorized as {user.first_name} (@{user.username})![/bold green]")
            return True
    except SessionPasswordNeededError:
        console.print("\n[bold yellow]Two-Step Verification is enabled on your account.[/bold yellow]")
        password = Prompt.ask("Enter your Telegram 2FA cloud password", password=True)
        try:
            user = await client.sign_in(password=password)
            console.print(f"[bold green]✓ Successfully authorized as {user.first_name}![/bold green]")
            return True
        except PasswordHashInvalidError:
            console.print("[bold red]Error: Incorrect 2FA password.[/bold red]")
            return False
    except asyncio.TimeoutError:
        console.print("[bold red]QR Code login timed out. Please try again.[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]QR Login error:[/bold red] {e}")
        return False


async def do_phone_login(client: TelegramClient, console: Console, phone: Optional[str] = None) -> bool:
    """Performs phone number + SMS/Telegram code login."""
    if not phone:
        phone = Prompt.ask("[bold cyan]Enter phone number (international format e.g. +79991234567)[/bold cyan]")
    
    phone = phone.strip().replace(" ", "").replace("-", "")

    try:
        sent = await client.send_code_request(phone)
    except PhoneNumberInvalidError:
        console.print("[bold red]Error: Invalid phone number format.[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]Failed to send authorization code:[/bold red] {e}")
        return False

    console.print(f"[green]Auth code sent to phone number {phone} (check your Telegram apps or SMS).[/green]")
    code = Prompt.ask("[bold cyan]Enter the code you received[/bold cyan]")
    code = code.strip().replace(" ", "").replace("-", "")

    try:
        user = await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        console.print(f"[bold green]✓ Successfully authorized as {user.first_name} (@{user.username})![/bold green]")
        return True
    except SessionPasswordNeededError:
        console.print("\n[bold yellow]Two-Step Verification (2FA) is required.[/bold yellow]")
        password = Prompt.ask("Enter your Telegram 2FA cloud password", password=True)
        try:
            user = await client.sign_in(password=password)
            console.print(f"[bold green]✓ Successfully authorized as {user.first_name}![/bold green]")
            return True
        except PasswordHashInvalidError:
            console.print("[bold red]Error: Incorrect 2FA password.[/bold red]")
            return False
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        console.print(f"[bold red]Error with auth code:[/bold red] {e}")
        return False
    except Exception as e:
        console.print(f"[bold red]Login error:[/bold red] {e}")
        return False


async def do_bot_login(client: TelegramClient, console: Console, bot_token: str) -> bool:
    """Performs Bot Token login."""
    try:
        await client.start(bot_token=bot_token.strip())
        me = await client.get_me()
        console.print(f"[bold green]✓ Successfully authorized as Bot @{me.username} ({me.first_name})![/bold green]")
        return True
    except Exception as e:
        console.print(f"[bold red]Bot login failed:[/bold red] {e}")
        return False


async def do_logout(client: TelegramClient, console: Console, session_name: Optional[str] = None) -> bool:
    """Logs out of the active Telegram session and removes session files."""
    cfg = load_config()
    session_name = session_name or cfg.get("active_session", "default")
    
    if client.is_connected():
        try:
            await client.log_out()
        except Exception:
            pass

    # Remove session files
    removed = 0
    for file in SESSIONS_DIR.glob(f"{session_name}.*"):
        try:
            file.unlink()
            removed += 1
        except Exception:
            pass

    console.print(f"[bold green]✓ Successfully logged out from session '{session_name}'.[/bold green]")
    return True
