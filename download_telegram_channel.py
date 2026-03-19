#!/usr/bin/env python3
"""
Скрипт для скачивания всех материалов из личного Telegram-канала.
Сохраняет текст сообщений в Markdown, скачивает все медиафайлы в каталог resources.

Использование:
    1. Создайте файл .env с переменными TELEGRAM_API_ID и TELEGRAM_API_HASH
       (или передайте их через аргументы командной строки)
    2. Запустите: python download_telegram_channel.py
    3. При первом запуске введите номер телефона и код подтверждения
"""

import os
import sys
import asyncio
import argparse
import re
from datetime import datetime
from pathlib import Path

try:
    from telethon import TelegramClient
    from telethon.tl.types import (
        MessageMediaPhoto,
        MessageMediaDocument,
        MessageMediaWebPage,
        MessageEntityBold,
        MessageEntityItalic,
        MessageEntityCode,
        MessageEntityPre,
        MessageEntityStrike,
        MessageEntityTextUrl,
        MessageEntityUrl,
        MessageEntityMention,
        MessageEntityHashtag,
        MessageEntityUnderline,
        MessageEntitySpoiler,
        MessageEntityBlockquote,
    )
    from telethon.utils import get_display_name
except ImportError:
    print("Ошибка: установите telethon: pip install telethon")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv необязателен, можно передать через аргументы


# ─── Конфигурация ────────────────────────────────────────────────────────────

OUTPUT_DIR = "telegram_backup"
RESOURCES_DIR = "resources"
MD_FILENAME = "channel_messages.md"
SESSION_NAME = "telegram_session"

# Расширения изображений для inline-вставки в markdown
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".svg"}


# ─── Конвертация Telegram-форматирования в Markdown ──────────────────────────

def _get_entity_type(entity) -> str:
    """Возвращает строковый тип entity."""
    if isinstance(entity, MessageEntityBold):
        return "bold"
    elif isinstance(entity, MessageEntityItalic):
        return "italic"
    elif isinstance(entity, MessageEntityStrike):
        return "strike"
    elif isinstance(entity, MessageEntityCode):
        return "code"
    elif isinstance(entity, MessageEntityPre):
        return "pre"
    elif isinstance(entity, MessageEntityUnderline):
        return "underline"
    elif isinstance(entity, MessageEntitySpoiler):
        return "spoiler"
    elif isinstance(entity, MessageEntityBlockquote):
        return "blockquote"
    elif isinstance(entity, MessageEntityTextUrl):
        return "texturl"
    elif isinstance(entity, MessageEntityUrl):
        return "url"
    elif isinstance(entity, MessageEntityMention):
        return "mention"
    elif isinstance(entity, MessageEntityHashtag):
        return "hashtag"
    else:
        return "unknown"


def _normalize_entities(entities: list) -> list[tuple]:
    """
    Конвертирует Telegram entities в список кортежей (start, end, type, extra)
    и объединяет смежные/перекрывающиеся entities одного типа.

    Возвращает список кортежей, отсортированных по start.
    """
    if not entities:
        return []

    from collections import defaultdict

    # Конвертируем в кортежи: (start, end, type_str, extra_data)
    tuples = []
    for entity in entities:
        etype = _get_entity_type(entity)
        start = entity.offset
        end = entity.offset + entity.length
        extra = {}
        if isinstance(entity, MessageEntityPre):
            extra["language"] = getattr(entity, 'language', '') or ''
        elif isinstance(entity, MessageEntityTextUrl):
            extra["url"] = entity.url
        tuples.append((start, end, etype, extra))

    # Группируем по типу для объединения смежных
    # НЕ объединяем texturl (у каждого свой URL)
    by_type = defaultdict(list)
    no_merge = []
    for t in tuples:
        if t[2] == "texturl":
            no_merge.append(t)
        else:
            by_type[t[2]].append(t)

    merged = list(no_merge)
    for etype, group in by_type.items():
        group.sort(key=lambda x: x[0])

        cur_start, cur_end, cur_type, cur_extra = group[0]
        for start, end, _, extra in group[1:]:
            if start <= cur_end:
                # Смежные или перекрывающиеся — объединяем
                cur_end = max(cur_end, end)
            else:
                merged.append((cur_start, cur_end, cur_type, cur_extra))
                cur_start, cur_end, cur_extra = start, end, extra
        merged.append((cur_start, cur_end, cur_type, cur_extra))

    merged.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    return merged


def telegram_to_markdown(text: str, entities: list | None) -> str:
    """
    Конвертирует текст с Telegram-entities в стандартный Markdown.

    **ВАЖНО**: Telegram уже возвращает текст с Markdown-разметкой
    (** для bold, ` для code, ``` для pre и т.д.). Entities указывают
    на эту разметку, ВКЛЮЧАЯ сами маркеры.

    Поэтому мы просто возвращаем текст как есть, обрабатывая только:
    - Blockquote (добавляем > перед строками)
    - TextUrl (конвертируем в [text](url))
    - Underline/Spoiler (добавляем HTML-теги, т.к. в MD их нет)
    """
    if not text:
        return ""

    # Если нет entities — возвращаем текст как есть
    if not entities:
        return text

    from collections import defaultdict

    normalized = _normalize_entities(entities)

    # Обрабатываем только специальные cases
    blockquote_ranges = []
    texturl_items = []
    underline_items = []
    spoiler_items = []

    for item in normalized:
        start, end, etype, extra = item
        if etype == "blockquote":
            blockquote_ranges.append((start, end))
        elif etype == "texturl":
            texturl_items.append((start, end, extra.get('url', '')))
        elif etype == "underline":
            underline_items.append((start, end))
        elif etype == "spoiler":
            spoiler_items.append((start, end))

    # Начинаем с исходного текста
    output = text

    # 1. TextUrl: заменяем текст на [text](url)
    # Работаем от конца к началу, чтобы не сдвигать индексы
    for start, end, url in sorted(texturl_items, key=lambda x: -x[0]):
        inner_text = output[start:end]
        output = output[:start] + f"[{inner_text}]({url})" + output[end:]

    # 2. Underline: оборачиваем в <u>...</u>
    for start, end in sorted(underline_items, key=lambda x: -x[0]):
        inner_text = output[start:end]
        output = output[:start] + f"<u>{inner_text}</u>" + output[end:]

    # 3. Spoiler: оборачиваем в <details>
    for start, end in sorted(spoiler_items, key=lambda x: -x[0]):
        inner_text = output[start:end]
        output = output[:start] + f"<details><summary>Спойлер</summary>{inner_text}</details>" + output[end:]

    # 4. Blockquote: добавляем > перед строками
    if blockquote_ranges:
        orig_lines = text.split("\n")
        line_starts = []
        pos = 0
        for line in orig_lines:
            line_starts.append(pos)
            pos += len(line) + 1

        bq_line_indices = set()
        for bq_start, bq_end in blockquote_ranges:
            for idx, ls in enumerate(line_starts):
                line_end = ls + len(orig_lines[idx])
                if ls < bq_end and line_end > bq_start:
                    bq_line_indices.add(idx)

        result_lines = output.split("\n")
        for idx in bq_line_indices:
            if idx < len(result_lines):
                result_lines[idx] = f"> {result_lines[idx]}"
        output = "\n".join(result_lines)

    # 5. Исправляем code blocks: ``` должны быть на отдельных строках
    # Telegram возвращает: text```\ncode\ncode```text
    # Нужно:              text\n```\ncode\ncode\n```\ntext
    # Паттерн 1: текст перед открывающим ```
    output = re.sub(r'([^\n])```(\w*)\n', r'\1\n```\2\n', output)
    # Паттерн 2: закрывающий ``` с текстом после
    output = re.sub(r'\n```([^\n])', r'\n```\n\1', output)
    # Паттерн 3: если ``` в начале строки, но без переноса перед
    output = re.sub(r'([^\n])```(\w*)$', r'\1\n```\2', output, flags=re.MULTILINE)

    # 6. Telegram bullet points: '• item' → '- item'
    output = re.sub(r'^•\s*', '- ', output, flags=re.MULTILINE)

    return output


# ─── Основная логика ─────────────────────────────────────────────────────────

async def resolve_channel(client: TelegramClient, channel_link: str):
    """Разрешает ссылку на канал в entity."""

    # Извлекаем username из ссылки вида https://t.me/username
    username_match = re.search(r"t\.me/([a-zA-Z0-9_]+)$", channel_link)
    if username_match:
        username = username_match.group(1)
        try:
            entity = await client.get_entity(username)
            return entity
        except Exception as e:
            print(f"Ошибка при получении канала по username @{username}: {e}")

    # Приватная ссылка вида https://t.me/+HASH или https://t.me/joinchat/HASH
    if "+" in channel_link or "joinchat" in channel_link:
        hash_match = re.search(r"(?:\+|joinchat/)([a-zA-Z0-9_-]+)", channel_link)
        if hash_match:
            invite_hash = hash_match.group(1)
            from telethon.tl.functions.messages import CheckChatInviteRequest
            try:
                result = await client(CheckChatInviteRequest(invite_hash))
                from telethon.tl.types import ChatInviteAlready, ChatInvite
                if isinstance(result, ChatInviteAlready):
                    return result.chat
                elif isinstance(result, ChatInvite):
                    print(f"Вы не являетесь участником канала. Название: {result.title}")
                    print("Сначала вступите в канал через Telegram.")
                    sys.exit(1)
            except Exception as e:
                print(f"Ошибка при проверке приглашения: {e}")

    # Пробуем получить entity напрямую (числовой ID или другой формат)
    try:
        entity = await client.get_entity(channel_link)
        return entity
    except Exception:
        pass

    # Ищем среди диалогов
    print("Ищем канал среди ваших диалогов...")
    async for dialog in client.iter_dialogs():
        if dialog.entity and hasattr(dialog.entity, 'title'):
            print(f"  Найден: {dialog.entity.title} (ID: {dialog.entity.id})")

    print("\nНе удалось автоматически найти канал.")
    print("Попробуйте указать числовой ID канала или username.")
    sys.exit(1)


async def download_channel(api_id: int, api_hash: str, channel_link: str,
                           output_dir: str, limit: int | None = None):
    """Скачивает все материалы из канала и сохраняет в Markdown."""

    output_path = Path(output_dir)
    resources_path = output_path / RESOURCES_DIR
    resources_path.mkdir(parents=True, exist_ok=True)

    session_path = str(output_path / SESSION_NAME)

    print("Подключение к Telegram...")
    client = TelegramClient(session_path, api_id, api_hash)
    await client.start()

    print("Авторизация успешна!")
    me = await client.get_me()
    print(f"Вы вошли как: {me.first_name} {me.last_name or ''} (@{me.username or 'N/A'})")

    # Получаем канал
    print(f"\nПолучение канала: {channel_link}")
    channel = await resolve_channel(client, channel_link)
    channel_title = getattr(channel, 'title', 'Unknown Channel')
    print(f"Канал найден: {channel_title}")

    # Скачиваем сообщения
    print("\nСкачивание сообщений...")
    messages = []
    count = 0
    media_count = 0
    media_skipped = 0

    async for message in client.iter_messages(channel, limit=limit, reverse=True):
        count += 1
        if count % 50 == 0:
            print(f"  Обработано сообщений: {count}...")

        # Конвертируем текст с entities в Markdown
        msg_text = telegram_to_markdown(message.text or "", message.entities)
        media_file = None
        media_filename = None

        # Скачиваем медиа
        if message.media:
            if isinstance(message.media, MessageMediaPhoto):
                # Фото
                try:
                    media_filename = f"photo_{message.id}_{message.date.strftime('%Y%m%d_%H%M%S')}.jpg"
                    filepath = str(resources_path / media_filename)
                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        media_file = filepath
                        media_skipped += 1
                    else:
                        await message.download_media(file=filepath)
                        media_file = filepath
                        media_count += 1
                        print(f"  📷 Фото: {media_filename}")
                except Exception as e:
                    print(f"  ⚠️ Ошибка скачивания фото (msg {message.id}): {e}")
                    media_filename = None

            elif isinstance(message.media, MessageMediaDocument):
                # Документ / видео / аудио / стикер / GIF
                try:
                    doc = message.media.document
                    # Определяем имя файла
                    filename = None
                    if doc and doc.attributes:
                        for attr in doc.attributes:
                            if hasattr(attr, 'file_name') and attr.file_name:
                                filename = attr.file_name
                                break

                    if not filename:
                        # Определяем расширение по MIME
                        mime = doc.mime_type if doc else "application/octet-stream"
                        ext_map = {
                            "video/mp4": ".mp4",
                            "audio/mpeg": ".mp3",
                            "audio/ogg": ".ogg",
                            "image/gif": ".gif",
                            "image/webp": ".webp",
                            "image/jpeg": ".jpg",
                            "image/png": ".png",
                            "application/pdf": ".pdf",
                            "video/quicktime": ".mov",
                        }
                        ext = ext_map.get(mime, ".bin")
                        filename = f"doc_{message.id}_{message.date.strftime('%Y%m%d_%H%M%S')}{ext}"

                    # Добавляем ID сообщения к имени для уникальности
                    media_filename = f"{message.id}_{filename}"
                    # Очищаем имя файла от проблемных символов
                    media_filename = re.sub(r'[<>:"/\\|?*]', '_', media_filename)
                    filepath = str(resources_path / media_filename)

                    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        media_file = filepath
                        media_skipped += 1
                    else:
                        await message.download_media(file=filepath)
                        media_file = filepath
                        media_count += 1

                        mime_type = doc.mime_type if doc else "unknown"
                        size_mb = (doc.size / 1024 / 1024) if doc and doc.size else 0
                        print(f"  📎 Файл: {media_filename} ({mime_type}, {size_mb:.1f} MB)")
                except Exception as e:
                    print(f"  ⚠️ Ошибка скачивания документа (msg {message.id}): {e}")
                    media_filename = None

            elif isinstance(message.media, MessageMediaWebPage):
                # Веб-страница (превью ссылки) — не скачиваем, но сохраняем URL
                if message.media.webpage and hasattr(message.media.webpage, 'url'):
                    url = message.media.webpage.url
                    title = getattr(message.media.webpage, 'title', None)
                    if msg_text:
                        # URL скорее всего уже в тексте — не дублируем
                        if url not in msg_text:
                            link_text = title or url
                            msg_text += f"\n\n[{link_text}]({url})"
                    else:
                        link_text = title or url
                        msg_text = f"[{link_text}]({url})"

        # Сохраняем сообщение
        if msg_text or media_file:
            sender_name = ""
            if message.sender:
                sender_name = get_display_name(message.sender)

            messages.append({
                "date": message.date,
                "text": msg_text,
                "media_filename": media_filename,
                "media_file": media_file,
                "sender": sender_name,
                "id": message.id,
            })

    print(f"\n{'='*50}")
    print(f"Всего сообщений: {count}")
    print(f"Медиафайлов скачано: {media_count}")
    print(f"Медиафайлов пропущено (уже есть): {media_skipped}")
    print(f"Сообщений с контентом: {len(messages)}")

    # Генерируем Markdown
    print("\nГенерация Markdown...")
    md_lines = []

    # Заголовок документа
    md_lines.append(f"# {channel_title}\n")
    md_lines.append(f"Дата экспорта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    md_lines.append(f"Всего сообщений: {len(messages)}\n")
    md_lines.append("---\n")

    for msg in messages:
        date_str = msg["date"].strftime("%Y-%m-%d %H:%M:%S")

        # Заголовок сообщения
        header = f"#### 📅 {date_str}"
        if msg["sender"]:
            header += f" — {msg['sender']}"
        md_lines.append(f"{header}\n")

        # Медиа (картинки inline, остальные файлы как ссылки)
        if msg["media_filename"]:
            rel_path = f"{RESOURCES_DIR}/{msg['media_filename']}"
            ext = Path(msg["media_filename"]).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                md_lines.append(f"![{msg['media_filename']}]({rel_path})\n")
            else:
                md_lines.append(f"📎 [{msg['media_filename']}]({rel_path})\n")

        # Текст сообщения
        if msg["text"]:
            md_lines.append(f"{msg['text']}\n")

        # Разделитель
        md_lines.append("---\n")

    md_content = "\n".join(md_lines)
    md_path = output_path / MD_FILENAME

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n✅ Markdown сохранён: {md_path}")
    print(f"✅ Ресурсы в: {resources_path}")
    print(f"\nГотово!")

    await client.disconnect()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Скачивание материалов из Telegram-канала в Markdown"
    )
    parser.add_argument(
        "--api-id",
        type=int,
        default=None,
        help="Telegram API ID (или переменная окружения TELEGRAM_API_ID)"
    )
    parser.add_argument(
        "--api-hash",
        type=str,
        default=None,
        help="Telegram API Hash (или переменная окружения TELEGRAM_API_HASH)"
    )
    parser.add_argument(
        "--channel",
        type=str,
        required=True,
        help="Ссылка на канал (например: https://t.me/username)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_DIR,
        help=f"Папка для сохранения (по умолчанию: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Максимальное количество сообщений (по умолчанию: все)"
    )

    args = parser.parse_args()

    # Получаем credentials
    api_id = args.api_id or os.environ.get("TELEGRAM_API_ID")
    api_hash = args.api_hash or os.environ.get("TELEGRAM_API_HASH")

    if not api_id:
        print("❌ Не указан API ID!")
        print("   Используйте --api-id или переменную окружения TELEGRAM_API_ID")
        print("   Или создайте файл .env с TELEGRAM_API_ID=ваш_id")
        sys.exit(1)

    if not api_hash:
        print("❌ Не указан API Hash!")
        print("   Используйте --api-hash или переменную окружения TELEGRAM_API_HASH")
        print("   Или создайте файл .env с TELEGRAM_API_HASH=ваш_hash")
        sys.exit(1)

    api_id = int(api_id)

    print("=" * 50)
    print("  Telegram Channel Downloader → Markdown")
    print("=" * 50)
    print(f"  Канал:  {args.channel}")
    print(f"  Выход:  {args.output}/")
    print(f"  Лимит:  {args.limit or 'все сообщения'}")
    print("=" * 50)

    asyncio.run(download_channel(
        api_id=api_id,
        api_hash=api_hash,
        channel_link=args.channel,
        output_dir=args.output,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
