from html import escape as esc

from rss_parser import FeedEntry

MAX_DESCRIPTION_LEN = 500


def format_entry_message(entry: FeedEntry, feed_name: str) -> str:
    lines = [f"🆕 <b>{esc(entry.title)}</b>", ""]

    if entry.category:
        lines.append(f"📁 Категория: {esc(entry.category)}")
    quality = entry.quality_str()
    if quality:
        lines.append(f"🎬 Качество: {esc(quality)}")
    if entry.size:
        lines.append(f"💾 Размер: {esc(entry.size)}")
    if entry.seeders or entry.leechers:
        s = entry.seeders or "?"
        l = entry.leechers or "?"
        lines.append(f"🌱 Сиды/Пиры: {esc(s)}/{esc(l)}")
    if entry.pub_date:
        lines.append(f"📅 Дата: {esc(entry.pub_date)}")

    if entry.description:
        desc = entry.description
        if len(desc) > MAX_DESCRIPTION_LEN:
            desc = desc[:MAX_DESCRIPTION_LEN].rsplit(" ", 1)[0] + "…"
        lines.append("")
        lines.append(f"📝 {esc(desc)}")

    lines.append("")
    if entry.link:
        lines.append(f'🔗 <a href="{esc(entry.link)}">Открыть раздачу</a>')
    lines.append(f"📡 Источник: {esc(feed_name)}")

    return "\n".join(lines)
