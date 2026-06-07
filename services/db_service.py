import os
import contextlib
import aiosqlite
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/users.db")

# Папка под БД должна существовать (data/ шарится между контейнерами bot и admin)
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


@contextlib.asynccontextmanager
async def _db():
    """Соединение с включённым busy_timeout — снижает 'database is locked'
    при одновременном доступе из бота и веб-админки."""
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA busy_timeout=5000")
        yield conn


async def init_db():
    async with _db() as db:
        # WAL — параллельные чтения не блокируются записью (data/ общая для обоих контейнеров)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                joined_at   TEXT,
                last_seen   TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS texts (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()


# ─── Пользователи ─────────────────────────────────────────────

async def add_user(user_id: int, username: str, first_name: str):
    now = datetime.now().isoformat()
    async with _db() as db:
        await db.execute("""
            INSERT INTO users (id, username, first_name, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username   = excluded.username,
                first_name = excluded.first_name,
                last_seen  = excluded.last_seen
        """, (user_id, username or "", first_name or "", now, now))
        await db.commit()


async def get_all_users() -> list[int]:
    async with _db() as db:
        cursor = await db.execute("SELECT id FROM users")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def get_stats() -> dict:
    async with _db() as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        today = (await (await db.execute(
            "SELECT COUNT(*) FROM users WHERE date(last_seen) = date('now')"
        )).fetchone())[0]
        week = (await (await db.execute(
            "SELECT COUNT(*) FROM users WHERE last_seen >= datetime('now', '-7 days')"
        )).fetchone())[0]
    return {"total": total, "today": today, "week": week}


# ─── Тексты (редактируются через веб-админку) ─────────────────

async def get_text_overrides() -> dict:
    async with _db() as db:
        cursor = await db.execute("SELECT key, value FROM texts")
        rows = await cursor.fetchall()
        return {k: v for k, v in rows}


async def set_text(key: str, value: str):
    async with _db() as db:
        await db.execute("""
            INSERT INTO texts (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        await db.commit()


async def delete_text(key: str):
    async with _db() as db:
        await db.execute("DELETE FROM texts WHERE key = ?", (key,))
        await db.commit()
