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
    ApiIdInvalidError,
)
import qrcode

from .config import get_session_path, SESSIONS_DIR, load_config, save_config


async def do_qr_login(client: TelegramClient, console: Console) -> bool:
    """Performs QR code login displaying ASCII QR code in terminal."""
    console.print("\n[bold cyan]Запуск авторизации через QR-код...[/bold cyan]")
    
    try:
        qr_login = await client.qr_login()
    except ApiIdInvalidError:
        console.print("\n[bold red]❌ Ошибка: Telegram отклонил комбинацию api_id / api_hash (API_ID_INVALID).[/bold red]")
        console.print("[yellow]Проверьте ваши ключи на https://my.telegram.org и обновите их командой:[/yellow]")
        console.print("  [cyan]tg config --api-id <ID> --api-hash <HASH>[/cyan]\n")
        return False
    except (ConnectionError, OSError) as e:
        console.print(f"\n[bold red]❌ Ошибка соединения с Telegram:[/bold red] {e}")
        console.print("[dim](Сервер Telegram часто разрывает соединение, если api_id/api_hash заблокирован или неверен)[/dim]\n")
        return False
    except Exception as e:
        console.print(f"[bold red]Не удалось запросить QR-код:[/bold red] {e}")
        return False

    def print_qr(url: str):
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        buf = io.StringIO()
        qr.print_ascii(out=buf, invert=True)
        console.print(buf.getvalue())
        console.print("[bold yellow]1. Открой Telegram на телефоне[/bold yellow]")
        console.print("[bold yellow]2. Перейди: Настройки -> Устройства -> Подключить устройство[/bold yellow]")
        console.print("[bold yellow]3. Наведи камеру на QR-код выше.[/bold yellow]\n")

    print_qr(qr_login.url)

    try:
        with console.status("[bold green]Ожидание сканирования в приложении Telegram...[/bold green]"):
            user = await qr_login.wait()
            console.print(f"[bold green]✓ Успешный вход: {user.first_name} (@{user.username})![/bold green]")
            return True
    except SessionPasswordNeededError:
        console.print("\n[bold yellow]На аккаунте включена двухфакторная аутентификация (2FA).[/bold yellow]")
        password = Prompt.ask("Введи облачный пароль 2FA", password=True)
        try:
            user = await client.sign_in(password=password)
            console.print(f"[bold green]✓ Успешный вход: {user.first_name}![/bold green]")
            return True
        except PasswordHashInvalidError:
            console.print("[bold red]Ошибка: Неверный облачный пароль 2FA.[/bold red]")
            return False
    except asyncio.TimeoutError:
        console.print("[bold red]Время ожидания QR-кода истекло. Попробуй заново.[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]Ошибка при QR-авторизации:[/bold red] {e}")
        return False


async def do_phone_login(client: TelegramClient, console: Console, phone: Optional[str] = None) -> bool:
    """Performs phone number + SMS/Telegram code login."""
    if not phone:
        phone = Prompt.ask("[bold cyan]Введи номер телефона (в международном формате, напр. +79991234567)[/bold cyan]")
    
    phone = phone.strip().replace(" ", "").replace("-", "")

    try:
        sent = await client.send_code_request(phone)
    except ApiIdInvalidError:
        console.print("\n[bold red]❌ Ошибка: Telegram отклонил комбинацию api_id / api_hash (API_ID_INVALID).[/bold red]")
        console.print("[yellow]Проверьте ваши ключи на https://my.telegram.org и обновите их командой:[/yellow]")
        console.print("  [cyan]tg config --api-id <ID> --api-hash <HASH>[/cyan]\n")
        return False
    except PhoneNumberInvalidError:
        console.print("[bold red]Ошибка: Неверный формат номера телефона.[/bold red]")
        return False
    except (ConnectionError, OSError) as e:
        console.print(f"\n[bold red]❌ Ошибка подключения к серверу Telegram:[/bold red] {e}")
        console.print("[dim](Сервер Telegram сбрасывает подключение при недействительном api_id/api_hash)[/dim]\n")
        return False
    except Exception as e:
        console.print(f"[bold red]Не удалось отправить код подтверждения:[/bold red] {e}")
        return False

    console.print(f"[green]Код подтверждения отправлен на номер {phone} (проверь Telegram на других устройствах или SMS).[/green]")
    code = Prompt.ask("[bold cyan]Введи код подтверждения[/bold cyan]")
    code = code.strip().replace(" ", "").replace("-", "")

    try:
        user = await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        console.print(f"[bold green]✓ Успешный вход: {user.first_name} (@{user.username})![/bold green]")
        return True
    except SessionPasswordNeededError:
        console.print("\n[bold yellow]Требуется двухфакторная аутентификация (2FA).[/bold yellow]")
        password = Prompt.ask("Введи облачный пароль 2FA", password=True)
        try:
            user = await client.sign_in(password=password)
            console.print(f"[bold green]✓ Успешный вход: {user.first_name}![/bold green]")
            return True
        except PasswordHashInvalidError:
            console.print("[bold red]Ошибка: Неверный облачный пароль 2FA.[/bold red]")
            return False
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        console.print(f"[bold red]Ошибка с кодом подтверждения:[/bold red] {e}")
        return False
    except Exception as e:
        console.print(f"[bold red]Ошибка входа:[/bold red] {e}")
        return False


async def do_bot_login(client: TelegramClient, console: Console, bot_token: str) -> bool:
    """Performs Bot Token login."""
    try:
        await client.start(bot_token=bot_token.strip())
        me = await client.get_me()
        console.print(f"[bold green]✓ Успешный вход как бот @{me.username} ({me.first_name})![/bold green]")
        return True
    except ApiIdInvalidError:
        console.print("\n[bold red]❌ Ошибка: Неверный api_id / api_hash.[/bold red]\n")
        return False
    except Exception as e:
        console.print(f"[bold red]Ошибка входа бота:[/bold red] {e}")
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

    console.print(f"[bold green]✓ Сессия '{session_name}' успешно закрыта и удалена.[/bold green]")
    return True
