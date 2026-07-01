import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

import database as db
from config import POLL_TICK_SECONDS, MAX_CONSECUTIVE_ERRORS_BEFORE_ALERT
from rss_parser import fetch_feed
from notifier import format_entry_message

log = logging.getLogger("poller")


async def _send_with_retry(bot: Bot, chat_id: int, text: str):
    try:
        await bot.send_message(chat_id, text, disable_web_page_preview=False)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        await bot.send_message(chat_id, text, disable_web_page_preview=False)
    except TelegramForbiddenError:
        log.warning("Пользователь %s заблокировал бота, пропускаю", chat_id)
    except TelegramBadRequest as e:
        log.warning("Не удалось отправить сообщение %s: %s", chat_id, e)


async def _process_feed(bot: Bot, feed: dict):
    result = await fetch_feed(feed["url"])
    feed_name = feed["name"] or feed["url"]

    if not result.ok:
        await db.mark_feed_checked(feed["id"], error=result.error)
        if feed["error_count"] + 1 == MAX_CONSECUTIVE_ERRORS_BEFORE_ALERT:
            await _send_with_retry(
                bot,
                feed["chat_id"],
                f"⚠️ Не удаётся опросить фид «{feed_name}» уже {MAX_CONSECUTIVE_ERRORS_BEFORE_ALERT} раз подряд.\n"
                f"Последняя ошибка: {result.error}\n"
                f"Ссылка: {feed['url']}",
            )
        return

    await db.mark_feed_checked(feed["id"], error=None)

    if not feed["initial_sync_done"]:
        # Первый опрос фида: просто запоминаем всё что есть, не спамим историей
        guids = [e.guid for e in result.entries]
        await db.mark_many_seen(feed["id"], guids)
        await db.mark_initial_sync_done(feed["id"])
        log.info(
            "Начальная синхронизация фида %s: %d записей отмечено как уже виденные",
            feed_name,
            len(guids),
        )
        return

    new_entries = []
    for entry in result.entries:
        if not await db.is_seen(feed["id"], entry.guid):
            new_entries.append(entry)

    # Новые записи в RSS обычно идут сверху вниз от новых к старым - развернём,
    # чтобы уведомления пришли в хронологическом порядке
    for entry in reversed(new_entries):
        text = format_entry_message(entry, feed_name)
        await _send_with_retry(bot, feed["chat_id"], text)
        await db.mark_seen(feed["id"], entry.guid)
        await asyncio.sleep(0.3)  # анти-флуд пауза между сообщениями


async def poll_loop(bot: Bot):
    log.info("Фоновый цикл опроса фидов запущен (тик каждые %d сек)", POLL_TICK_SECONDS)
    while True:
        try:
            feeds = await db.get_all_feeds()
            now = int(time.time())
            for feed in feeds:
                interval_minutes = await db.get_interval(feed["chat_id"])
                due = (now - feed["last_check"]) >= interval_minutes * 60
                if due:
                    try:
                        await _process_feed(bot, feed)
                    except Exception:
                        log.exception("Ошибка обработки фида %s", feed["url"])
        except Exception:
            log.exception("Ошибка в основном цикле опроса")

        await asyncio.sleep(POLL_TICK_SECONDS)
