import asyncio
import re
import html
from dataclasses import dataclass, field

import aiohttp
import feedparser

from config import FEED_USER_AGENT

# --- Регэкспы для извлечения деталей из title/description ---

RESOLUTION_RE = re.compile(r"\b(2160p|1080p|720p|480p|4K|UHD)\b", re.IGNORECASE)
SOURCE_RE = re.compile(
    r"\b(BDRip|BDRemux|BD-Remux|BluRay|WEB-?DL|WEBRip|HDTV|DVDRip|DVDScr|HDRip|Telesync|TS|CAMRip)\b",
    re.IGNORECASE,
)
AUDIO_RE = re.compile(
    r"\b(DTS|AC3|AAC|TrueHD|Dolby|Atmos|5\.1|7\.1|2\.0)\b", re.IGNORECASE
)

SIZE_RE = re.compile(
    r"(Размер|Size)\s*[:\-]?\s*([\d.,]+\s?(?:GB|MB|ГБ|МБ|Gb|Mb))", re.IGNORECASE
)
SEEDERS_RE = re.compile(r"(Сид(?:ов|ы|еров)?|Seed(?:ers|s)?)\s*[:\-]?\s*(\d+)", re.IGNORECASE)
LEECHERS_RE = re.compile(r"(Лич(?:ей|и)?|Leech(?:ers|s)?|Пиров?|Peers?)\s*[:\-]?\s*(\d+)", re.IGNORECASE)

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"[ \t]+")


def strip_html(raw: str) -> str:
    """Убирает HTML-теги и лишние пробелы, декодирует сущности."""
    if not raw:
        return ""
    text = html.unescape(raw)
    text = TAG_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text)
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


@dataclass
class FeedEntry:
    guid: str
    title: str
    link: str
    description: str = ""
    category: str = ""
    pub_date: str = ""
    resolution: str = ""
    source: str = ""
    audio: str = ""
    size: str = ""
    seeders: str = ""
    leechers: str = ""

    def quality_str(self) -> str:
        parts = [p for p in (self.resolution, self.source, self.audio) if p]
        return " / ".join(parts)


@dataclass
class FeedFetchResult:
    ok: bool
    entries: list[FeedEntry] = field(default_factory=list)
    error: str | None = None
    feed_title: str = ""


def _extract_details(entry: FeedEntry, search_text: str):
    m = RESOLUTION_RE.search(search_text)
    if m:
        entry.resolution = m.group(1).upper()
    m = SOURCE_RE.search(search_text)
    if m:
        entry.source = m.group(1)
    m = AUDIO_RE.search(search_text)
    if m:
        entry.audio = m.group(1)
    m = SIZE_RE.search(search_text)
    if m:
        entry.size = m.group(2).strip()
    m = SEEDERS_RE.search(search_text)
    if m:
        entry.seeders = m.group(2)
    m = LEECHERS_RE.search(search_text)
    if m:
        entry.leechers = m.group(2)


def _parse_feed_bytes(raw: bytes) -> FeedFetchResult:
    parsed = feedparser.parse(raw)

    if parsed.bozo and not parsed.entries:
        reason = str(parsed.get("bozo_exception", "не удалось разобрать RSS"))
        return FeedFetchResult(ok=False, error=reason)

    feed_title = ""
    if hasattr(parsed, "feed"):
        feed_title = parsed.feed.get("title", "") or ""

    entries = []
    for raw_entry in parsed.entries:
        title = raw_entry.get("title", "").strip()
        link = raw_entry.get("link", "").strip()
        guid = raw_entry.get("id") or raw_entry.get("guid") or link or title
        raw_description = raw_entry.get("summary", "") or raw_entry.get("description", "")
        description_clean = strip_html(raw_description)

        category = ""
        if "tags" in raw_entry and raw_entry.tags:
            category = ", ".join(
                t.get("term", "") for t in raw_entry.tags if t.get("term")
            )

        pub_date = raw_entry.get("published", "") or raw_entry.get("updated", "")

        entry = FeedEntry(
            guid=guid,
            title=title,
            link=link,
            description=description_clean,
            category=category,
            pub_date=pub_date,
        )
        search_text = f"{title}\n{raw_description}"
        _extract_details(entry, search_text)
        entries.append(entry)

    return FeedFetchResult(ok=True, entries=entries, feed_title=feed_title)


async def fetch_feed(url: str, timeout_seconds: int = 20) -> FeedFetchResult:
    headers = {"User-Agent": FEED_USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return FeedFetchResult(
                        ok=False, error=f"HTTP {resp.status} при запросе фида"
                    )
                raw = await resp.read()
    except asyncio.TimeoutError:
        return FeedFetchResult(ok=False, error="Таймаут при запросе фида")
    except aiohttp.ClientError as e:
        return FeedFetchResult(ok=False, error=f"Ошибка сети: {e}")

    return await asyncio.to_thread(_parse_feed_bytes, raw)
