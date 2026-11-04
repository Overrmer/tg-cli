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
from telethon.errors import ApiIdInvalidError

from . import __version__, __app_name__
from .config import (
    load_config,
    update_config,
    get_session_path,
    SESSIONS_DIR,
    is_credentials_valid,
    prompt_credentials,
)
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
from .tui import TelegramTUI

app = typer.Typer(
    name="tg",
    help="⚡ Modern, blazing-fast Telegram CLI & TUI client for terminals, scripting and automation.",
    add_completion=True,
    no_args_is_help=True,
)
console = Console()


def run_async(coro):
    """Utility to run an async coroutine synchronously with clean error handling."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]Операция прервана пользователем.[/yellow]")
        sys.exit(0)
    except ApiIdInvalidError:
        console.print("\n[bold red]❌ Ошибка: Telegram отклонил api_id и api_hash (API_ID_INVALID).[/bold red]")
        console.print("[yellow]Telegram строго запрещает использование устаревших или публичных ключей.[/yellow]")
        console.print("Получите бесплатный личный API ID и Hash на [bold cyan]https://my.telegram.org[/bold cyan] и задайте их:")
        console.print("  [cyan]tg config --api-id <ID> --api-hash <HASH>[/cyan]\n")
        sys.exit(1)
    except (ConnectionError, OSError) as e:
        console.print(f"\n[bold red]❌ Ошибка соединения с Telegram:[/bold red] {e}")
        console.print("[dim](Обычно возникает при сбросе сессии или недействительных API credentials)[/dim]\n")
        sys.exit(1)


async def check_auth_or_exit(client) -> User:
    try:
        await client.connect()
    except ApiIdInvalidError:
        console.print("\n[bold red]❌ Ошибка: Неверный api_id / api_hash.[/bold red]")
        console.print("Обновите ключи: [cyan]tg config --api-id <ID> --api-hash <HASH>[/cyan]\n")
        sys.exit(1)

    if not await client.is_user_authorized():
        console.print("[bold red]Вы не авторизованы![/bold red] Сначала выполните [bold cyan]tg login[/bold cyan].")
        await client.disconnect()
        sys.exit(1)
    return await client.get_me()


@app.command(name="login")
def login(
    qr: bool = typer.Option(False, "--qr", help="Войти через сканирование QR-кода камерой телефона."),
    phone: Optional[str] = typer.Option(None, "--phone", "-p", help="Номер телефона с кодом страны (напр. +79991234567)."),
    bot_token: Optional[str] = typer.Option(None, "--bot-token", "-b", help="Войти как Telegram Bot по Bot Token."),
    api_id: Optional[int] = typer.Option(None, "--api-id", help="Собственный Telegram API ID с my.telegram.org"),
    api_hash: Optional[str] = typer.Option(None, "--api-hash", help="Собственный Telegram API Hash с my.telegram.org"),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии (по умолчанию 'default')"),
):
    """
    Авторизация в Telegram (по QR-коду, телефону с 2FA или Bot Token).
    """
    if api_id or api_hash:
        update_config(api_id=api_id, api_hash=api_hash)
    if session:
        update_config(active_session=session)

    # If credentials are not valid/configured, guide the user
    if not is_credentials_valid():
        api_id, api_hash = prompt_credentials(console)

    async def _login():
        client = get_client(session_name=session, api_id=api_id, api_hash=api_hash)
        try:
            await client.connect()
        except ApiIdInvalidError:
            console.print("\n[bold red]❌ Ошибка: Введенные api_id / api_hash отклонены сервером Telegram.[/bold red]")
            console.print("Проверьте правильность на https://my.telegram.org и обновите: [cyan]tg config --api-id <ID> --api-hash <HASH>[/cyan]\n")
            return

        if await client.is_user_authorized():
            me = await client.get_me()
            console.print(f"[bold green]Вы уже авторизованы как {me.first_name} (@{me.username})[/bold green]")
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
            console.print("[bold cyan]Выберите способ входа в Telegram:[/bold cyan]")
            console.print("  [1] QR-код (Быстрее всего — отсканировать камерой в приложении)")
            console.print("  [2] По номеру телефона (Код придет в Telegram или SMS)")
            console.print("  [3] Bot Token (Войти как бот)")
            choice = Prompt.ask("Выбор", choices=["1", "2", "3"], default="1")
            
            if choice == "1":
                success = await do_qr_login(client, console)
            elif choice == "2":
                success = await do_phone_login(client, console)
            elif choice == "3":
                token = Prompt.ask("Введи Bot Token")
                success = await do_bot_login(client, console, token)

        await client.disconnect()
        if success:
            console.print("\n[bold green]✨ Авторизация успешна! Запустите [cyan]tg tui[/cyan] для полноэкранного интерфейса или [cyan]tg chats[/cyan].[/bold green]")

    run_async(_login())


@app.command(name="tui")
def tui_cmd(
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """
    🖥️ Запустить полноэкранный графический терминальный интерфейс (TUI) с сайдбаром чатов и лентой сообщений.
    """
    if not is_credentials_valid():
        console.print("[bold red]Ключи API не настроены.[/bold red] Сначала запустите [cyan]tg login[/cyan].")
        sys.exit(1)

    async def _tui():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)
        app_tui = TelegramTUI(client)
        await app_tui.run_async()
        await client.disconnect()

    run_async(_tui())


@app.command(name="logout")
def logout(
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии для выхода."),
):
    """Выйти из аккаунта и удалить сохраненные файлы сессии."""
    async def _logout():
        client = get_client(session_name=session)
        await client.connect()
        await do_logout(client, console, session_name=session)
        await client.disconnect()

    run_async(_logout())


@app.command(name="me")
def me(
    json_output: bool = typer.Option(False, "--json", help="Вывод в формате JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Информация о текущем авторизованном пользователе или боте."""
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
    limit: int = typer.Option(20, "--limit", "-n", help="Количество чатов для отображения."),
    unread_only: bool = typer.Option(False, "--unread", "-u", help="Показывать только чаты с непрочитанными."),
    filter_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Фильтр по типу: user, group, channel, bot."
    ),
    search_query: Optional[str] = typer.Option(None, "--search", "-q", help="Поиск по названию или @username."),
    json_output: bool = typer.Option(False, "--json", help="Вывод в формате JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Список последних чатов, групп и каналов с бейджами непрочитанных."""
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
    peer: str = typer.Argument(..., help="Кому/Откуда: юзернейм (@user), телефон (+...), ID или 'me'."),
    limit: int = typer.Option(20, "--limit", "-n", help="Количество сообщений."),
    reverse: bool = typer.Option(True, "--reverse/--no-reverse", help="Хронологический порядок (старые сверху)."),
    json_output: bool = typer.Option(False, "--json", help="Вывод в формате JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Прочитать историю сообщений из чата, канала или Избранного."""
    async def _read():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Ошибка поиска '{peer}':[/bold red] {e}")
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
            console.print(f"[bold magenta]📖 История диалога {chat_title} ({len(messages)} сообщений):[/bold magenta]\n")
            for m in messages:
                print_message_line(m, console, show_chat=False)

        await client.disconnect()

    run_async(_read())


@app.command(name="send")
def send(
    peer: str = typer.Argument(..., help="Получатель: юзернейм (@user), телефон, ID или 'me'."),
    message: Optional[str] = typer.Argument(None, help="Текст сообщения (или передать через конвейер pipe)."),
    reply_to: Optional[int] = typer.Option(None, "--reply-to", "-r", help="ID сообщения для ответа."),
    silent: bool = typer.Option(False, "--silent", help="Отправить без звукового уведомления."),
    json_output: bool = typer.Option(False, "--json", help="Вывод информации в JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """
    Отправить текстовое сообщение (поддерживает pipe: `echo "Готово" | tg send me`).
    """
    if not message or message == "-":
        stdin_text = read_stdin_if_available()
        if stdin_text:
            message = stdin_text
        elif not message:
            console.print("[bold red]Ошибка: Текст сообщения не указан и stdin пуст.[/bold red]")
            sys.exit(1)

    async def _send():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Ошибка поиска получателя '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        chat_title = get_peer_title(entity)
        msg = await client.send_message(entity, message, reply_to=reply_to, silent=silent)

        if json_output:
            console.print(json.dumps(serialize_message(msg, chat_title=chat_title), indent=2, ensure_ascii=False))
        else:
            console.print(f"[bold green]✓ Отправлено в {chat_title} (ID сообщения: #{msg.id})[/bold green]")

        await client.disconnect()

    run_async(_send())


@app.command(name="send-file")
def send_file(
    peer: str = typer.Argument(..., help="Получатель: юзернейм, ID или 'me'."),
    file_path: str = typer.Argument(..., help="Путь к файлу, картинке, видео или документу."),
    caption: str = typer.Option("", "--caption", "-c", help="Текстовая подпись к файлу."),
    as_document: bool = typer.Option(False, "--doc", help="Отправить как документ без сжатия."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Загрузить и отправить файл с индикатором прогресса."""
    async def _send_file():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Ошибка поиска получателя '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        chat_title = get_peer_title(entity)
        try:
            msg = await upload_file_with_progress(
                client, entity, file_path, caption=caption, as_document=as_document, console=console
            )
            console.print(f"[bold green]✓ Файл {file_path} успешно отправлен в {chat_title} (ID: #{msg.id})[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Ошибка отправки файла:[/bold red] {e}")

        await client.disconnect()

    run_async(_send_file())


@app.command(name="download")
def download(
    peer: str = typer.Argument(..., help="Чат/канал с сообщением."),
    message_id: int = typer.Argument(..., help="ID сообщения с файлом/медиа."),
    out: Optional[str] = typer.Option(None, "--out", "-o", help="Путь для сохранения (папка или имя файла)."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Скачать фото, документ, аудио или видео из сообщения."""
    async def _download():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        try:
            entity = await resolve_peer(client, peer)
        except Exception as e:
            console.print(f"[bold red]Ошибка поиска '{peer}':[/bold red] {e}")
            await client.disconnect()
            sys.exit(1)

        msg = await client.get_messages(entity, ids=message_id)
        if not msg:
            console.print(f"[bold red]Сообщение #{message_id} не найдено.[/bold red]")
            await client.disconnect()
            sys.exit(1)

        try:
            saved_path = await download_message_media(client, msg, output_path=out, console=console)
            console.print(f"[bold green]✓ Файл сохранен в: {saved_path}[/bold green]")
        except Exception as e:
            console.print(f"[bold red]Ошибка скачивания:[/bold red] {e}")

        await client.disconnect()

    run_async(_download())


@app.command(name="stream")
def stream(
    peer: Optional[str] = typer.Option(None, "--peer", "-p", help="Фильтр по конкретному чату."),
    json_output: bool = typer.Option(False, "--json", help="Выводить поток сырым JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """
    Живой стриминг входящих сообщений в реальном времени (как `tail -f`).
    """
    async def _stream():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        filter_chat = None
        filter_title = "Все чаты"
        if peer:
            try:
                filter_chat = await resolve_peer(client, peer)
                filter_title = get_peer_title(filter_chat)
            except Exception as e:
                console.print(f"[bold red]Ошибка поиска '{peer}':[/bold red] {e}")
                await client.disconnect()
                sys.exit(1)

        if not json_output:
            console.print(f"[bold cyan]⚡ Стриминг входящих сообщений из [yellow]{filter_title}[/yellow] (Ctrl+C для выхода)...[/bold cyan]\n")

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
            console.print("\n[yellow]Стриминг остановлен.[/yellow]")
        finally:
            await client.disconnect()

    run_async(_stream())


@app.command(name="chat")
def chat(
    peer: str = typer.Argument(..., help="Собеседник: юзернейм, телефон, ID или 'me'."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Быстрый консольный интерактивный чат с одним пользователем или группой."""
    async def _chat():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)
        await run_interactive_chat(client, peer, console)
        await client.disconnect()

    run_async(_chat())


@app.command(name="search")
def search(
    query: str = typer.Argument(..., help="Текст для поиска."),
    peer: Optional[str] = typer.Option(None, "--peer", "-p", help="Искать только внутри этого чата."),
    limit: int = typer.Option(20, "--limit", "-n", help="Максимум результатов."),
    json_output: bool = typer.Option(False, "--json", help="Вывод в формате JSON."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Имя сессии."),
):
    """Поиск сообщений по ключевому слову глобально или внутри чата."""
    async def _search():
        client = get_client(session_name=session)
        await check_auth_or_exit(client)

        entity = None
        if peer:
            try:
                entity = await resolve_peer(client, peer)
            except Exception as e:
                console.print(f"[bold red]Ошибка поиска '{peer}':[/bold red] {e}")
                await client.disconnect()
                sys.exit(1)

        results = []
        async for msg in client.iter_messages(entity, search=query, limit=limit):
            results.append(msg)

        if json_output:
            out = [serialize_message(m) for m in results]
            console.print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            console.print(f"[bold cyan]🔍 Найдено {len(results)} сообщений по запросу '{query}':[/bold cyan]\n")
            for m in results:
                print_message_line(m, console, show_chat=True)

        await client.disconnect()

    run_async(_search())


@app.command(name="config")
def config_cmd(
    api_id: Optional[int] = typer.Option(None, "--api-id", help="Задать Telegram API ID (с my.telegram.org)."),
    api_hash: Optional[str] = typer.Option(None, "--api-hash", help="Задать Telegram API Hash (с my.telegram.org)."),
    session: Optional[str] = typer.Option(None, "--session", "-s", help="Активная сессия."),
    downloads_dir: Optional[str] = typer.Option(None, "--downloads-dir", help="Папка для скачиваний."),
):
    """Просмотр или изменение настроек (API ID, API Hash, папки)."""
    if any([api_id, api_hash, session, downloads_dir]):
        cfg = update_config(
            api_id=api_id,
            api_hash=api_hash,
            active_session=session,
            downloads_dir=downloads_dir,
        )
        console.print("[bold green]✓ Настройки успешно сохранены![/bold green]")
    else:
        cfg = load_config()

    console.print("\n[bold cyan]Текущая конфигурация TG-CLI:[/bold cyan]")
    masked_hash = cfg.get("api_hash", "") or ""
    if len(masked_hash) > 8:
        masked_hash = masked_hash[:4] + "..." + masked_hash[-4:]
    console.print(f"  [bold]API ID:[/bold] {cfg.get('api_id') or '[red]Не задан (требуется с my.telegram.org)[/red]'}")
    console.print(f"  [bold]API Hash:[/bold] {masked_hash or '[red]Не задан[/red]'}")
    console.print(f"  [bold]Активная сессия:[/bold] {cfg.get('active_session')}")
    console.print(f"  [bold]Папка скачиваний:[/bold] {cfg.get('downloads_dir')}")
    console.print(f"  [bold]Хранилище сессий:[/bold] {SESSIONS_DIR}\n")


@app.command(name="version")
def version():
    """Показать версию."""
    console.print(f"[bold cyan]{__app_name__}[/bold cyan] version [bold green]{__version__}[/bold green]")


def main():
    app()


if __name__ == "__main__":
    main()
