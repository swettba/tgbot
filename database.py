import time
import aiosqlite

from config import DB_PATH, DEFAULT_INTERVAL_MINUTES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    interval_minutes INTEGER NOT NULL DEFAULT %d,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    name TEXT,
    added_at INTEGER NOT NULL,
    last_check INTEGER DEFAULT 0,
    last_error TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    initial_sync_done INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chat_id, url)
);

CREATE TABLE IF NOT EXISTS seen_items (
    feed_id INTEGER NOT NULL,
    guid TEXT NOT NULL,
    seen_at INTEGER NOT NULL,
    PRIMARY KEY (feed_id, guid)
);

CREATE INDEX IF NOT EXISTS idx_feeds_chat_id ON feeds(chat_id);
""" % DEFAULT_INTERVAL_MINUTES


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def ensure_user(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (chat_id, interval_minutes, created_at) VALUES (?, ?, ?)",
            (chat_id, DEFAULT_INTERVAL_MINUTES, int(time.time())),
        )
        await db.commit()


async def set_interval(chat_id: int, minutes: int):
    await ensure_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET interval_minutes = ? WHERE chat_id = ?",
            (minutes, chat_id),
        )
        await db.commit()


async def get_interval(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT interval_minutes FROM users WHERE chat_id = ?", (chat_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else DEFAULT_INTERVAL_MINUTES


async def add_feed(chat_id: int, url: str, name: str | None) -> int | None:
    await ensure_user(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            cur = await db.execute(
                "INSERT INTO feeds (chat_id, url, name, added_at) VALUES (?, ?, ?, ?)",
                (chat_id, url, name, int(time.time())),
            )
            await db.commit()
            return cur.lastrowid
        except aiosqlite.IntegrityError:
            return None


async def remove_feed(chat_id: int, feed_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM feeds WHERE id = ? AND chat_id = ?", (feed_id, chat_id)
        )
        await db.commit()
        return cur.rowcount > 0


async def list_feeds(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM feeds WHERE chat_id = ? ORDER BY id", (chat_id,)
        )
        return [dict(r) for r in await cur.fetchall()]


async def count_feeds(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM feeds WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
        return row[0]


async def get_all_feeds():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM feeds")
        return [dict(r) for r in await cur.fetchall()]


async def mark_feed_checked(feed_id: int, error: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if error:
            await db.execute(
                "UPDATE feeds SET last_check = ?, last_error = ?, error_count = error_count + 1 WHERE id = ?",
                (int(time.time()), error, feed_id),
            )
        else:
            await db.execute(
                "UPDATE feeds SET last_check = ?, last_error = NULL, error_count = 0 WHERE id = ?",
                (int(time.time()), feed_id),
            )
        await db.commit()


async def mark_initial_sync_done(feed_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE feeds SET initial_sync_done = 1 WHERE id = ?", (feed_id,)
        )
        await db.commit()


async def is_seen(feed_id: int, guid: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM seen_items WHERE feed_id = ? AND guid = ?", (feed_id, guid)
        )
        return (await cur.fetchone()) is not None


async def mark_seen(feed_id: int, guid: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_items (feed_id, guid, seen_at) VALUES (?, ?, ?)",
            (feed_id, guid, int(time.time())),
        )
        await db.commit()


async def mark_many_seen(feed_id: int, guids: list[str]):
    if not guids:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        now = int(time.time())
        await db.executemany(
            "INSERT OR IGNORE INTO seen_items (feed_id, guid, seen_at) VALUES (?, ?, ?)",
            [(feed_id, g, now) for g in guids],
        )
        await db.commit()
