import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import database as db
from config import (
    BOT_TOKEN,
    MIN_INTERVAL_MINUTES,
    MAX_FEEDS_PER_USER,
    DEFAULT_INTERVAL_MINUTES,
)
from rss_parser import fetch_feed
from poller import poll_loop

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("bot")

router = Router()

HELP_TEXT = (
    "🤖 <b>Бот мониторинга торрент-раздач по RSS</b>\n\n"
    "Команды:\n"
    "/add <code>ссылка</code> [название] — добавить RSS-ленту\n"
    "/list — список ваших фидов\n"
    "/remove <code>id</code> — удалить фид\n"
    "/interval <code>минуты</code> — как часто проверять фиды (мин. "
    f"{MIN_INTERVAL_MINUTES})\n"
    "/check — проверить все фиды прямо сейчас\n"
    "/status — статус бота и ваших фидов\n"
    "/help — это сообщение\n\n"
    "Просто пришлите RSS-ссылку с трекера (rutracker, kinozal и т.п.), "
    "и бот будет присылать уведомления о новых раздачах."
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await db.ensure_user(message.chat.id)
    await message.answer(
        "Привет! Я слежу за RSS-лентами торрент-трекеров и присылаю уведомления "
        "о новых раздачах.\n\n" + HELP_TEXT
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(Command("add"))
async def cmd_add(message: Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 2 or not args[1].startswith(("http://", "https://")):
        await message.answer(
            "Использование: <code>/add ссылка [название]</code>\n"
            "Например: <code>/add https://rutracker.org/forum/rss.php?filter=... Сериалы</code>"
        )
        return

    url = args[1]
    name = args[2] if len(args) > 2 else None

    count = await db.count_feeds(message.chat.id)
    if count >= MAX_FEEDS_PER_USER:
        await message.answer(
            f"Достигнут лимит в {MAX_FEEDS_PER_USER} фидов. Удалите ненужные через /remove."
        )
        return

    status_msg = await message.answer("🔍 Проверяю ссылку...")

    result = await fetch_feed(url)
    if not result.ok:
        await status_msg.edit_text(
            f"❌ Не удалось прочитать RSS по этой ссылке.\nОшибка: {result.error}\n\n"
            "Проверьте, что это прямая ссылка на RSS-фид (обычно на странице поиска "
            "трекера есть иконка RSS или пункт «RSS»)."
        )
        return

    display_name = name or result.feed_title or url
    feed_id = await db.add_feed(message.chat.id, url, display_name)
    if feed_id is None:
        await status_msg.edit_text("⚠️ Такой фид у вас уже добавлен.")
        return

    await status_msg.edit_text(
        f"✅ Фид «{display_name}» добавлен (id {feed_id}).\n"
        f"Найдено {len(result.entries)} текущих раздач — они не будут присланы как "
        f"уведомления, бот сообщит только о новых поступлениях.\n"
        f"Интервал проверки: {await db.get_interval(message.chat.id)} мин. "
        f"(изменить: /interval)"
    )


@router.message(Command("list"))
async def cmd_list(message: Message):
    feeds = await db.list_feeds(message.chat.id)
    if not feeds:
        await message.answer("У вас пока нет добавленных фидов. Добавьте через /add.")
        return

    lines = ["📋 <b>Ваши фиды:</b>\n"]
    for f in feeds:
        status = "✅" if not f["last_error"] else f"⚠️ ({f['last_error'][:40]})"
        lines.append(
            f"<b>#{f['id']}</b> {f['name'] or f['url']} {status}\n"
            f"   <code>{f['url']}</code>"
        )
    await message.answer("\n".join(lines))


@router.message(Command("remove"))
async def cmd_remove(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer("Использование: <code>/remove id</code> (id смотрите в /list)")
        return

    feed_id = int(args[1].strip())
    ok = await db.remove_feed(message.chat.id, feed_id)
    if ok:
        await message.answer(f"🗑 Фид #{feed_id} удалён.")
    else:
        await message.answer("Фид с таким id не найден среди ваших.")


@router.message(Command("interval"))
async def cmd_interval(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        current = await db.get_interval(message.chat.id)
        await message.answer(
            f"Текущий интервал проверки: {current} мин.\n"
            f"Использование: <code>/interval минуты</code> (минимум {MIN_INTERVAL_MINUTES})"
        )
        return

    minutes = int(args[1].strip())
    if minutes < MIN_INTERVAL_MINUTES:
        await message.answer(f"Минимальный интервал — {MIN_INTERVAL_MINUTES} мин.")
        return

    await db.set_interval(message.chat.id, minutes)
    await message.answer(f"⏱ Интервал проверки установлен: {minutes} мин.")


@router.message(Command("check"))
async def cmd_check(message: Message):
    from poller import _process_feed  # локальный импорт во избежание циклов

    feeds = await db.list_feeds(message.chat.id)
    if not feeds:
        await message.answer("У вас нет фидов. Добавьте через /add.")
        return

    await message.answer(f"🔄 Проверяю {len(feeds)} фид(ов)...")
    for f in feeds:
        await _process_feed(message.bot, f)
    await message.answer("✅ Проверка завершена.")


@router.message(Command("status"))
async def cmd_status(message: Message):
    feeds = await db.list_feeds(message.chat.id)
    interval = await db.get_interval(message.chat.id)
    errors = sum(1 for f in feeds if f["last_error"])
    await message.answer(
        f"📊 <b>Статус</b>\n"
        f"Фидов: {len(feeds)}\n"
        f"Интервал проверки: {interval} мин.\n"
        f"Фидов с ошибками: {errors}"
    )


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await db.init_db()

    poller_task = asyncio.create_task(poll_loop(bot))

    try:
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
