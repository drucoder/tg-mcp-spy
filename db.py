import sqlite3
from typing import Optional

DB_PATH = "telegram_cache.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channelname TEXT UNIQUE NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            tg_post_id INTEGER NOT NULL,
            text TEXT,
            date TEXT NOT NULL,
            url TEXT NOT NULL,
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            UNIQUE(channel_id, tg_post_id)
        );
    """)
    conn.commit()
    conn.close()


def add_channel(channelname: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO channels (channelname) VALUES (?)", (channelname,))
        conn.commit()
        row = conn.execute(
            "SELECT id, channelname, added_at FROM channels WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT id, channelname, added_at FROM channels WHERE channelname = ?",
            (channelname,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def remove_channel(channelname: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM channels WHERE channelname = ?", (channelname,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    channel_id = row["id"]
    conn.execute("DELETE FROM posts WHERE channel_id = ?", (channel_id,))
    conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()
    return True


def list_channels() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, channelname, added_at FROM channels ORDER BY channelname"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_channel(channelname: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, channelname, added_at FROM channels WHERE channelname = ?",
        (channelname,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_posts(channel_id: int, posts: list[dict]):
    conn = get_conn()
    for post in posts:
        conn.execute(
            """INSERT OR IGNORE INTO posts (channel_id, tg_post_id, text, date, url)
               VALUES (?, ?, ?, ?, ?)""",
            (channel_id, post["tg_post_id"], post["text"], post["date"], post["url"]),
        )
    conn.commit()
    conn.close()


def get_latest_post_id(channel_id: int) -> Optional[int]:
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(tg_post_id) as max_id FROM posts WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()
    conn.close()
    return row["max_id"] if row and row["max_id"] is not None else None


def get_oldest_post_date(channel_id: int) -> Optional[str]:
    conn = get_conn()
    row = conn.execute(
        "SELECT MIN(date) as min_date FROM posts WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()
    conn.close()
    return row["min_date"] if row and row["min_date"] is not None else None


def get_posts(channel_ids: list[int], since_date: str) -> list[dict]:
    conn = get_conn()
    placeholders = ",".join("?" * len(channel_ids))
    rows = conn.execute(
        f"""SELECT p.id, c.channelname, p.tg_post_id, p.text, p.date, p.url
            FROM posts p
            JOIN channels c ON c.id = p.channel_id
            WHERE p.channel_id IN ({placeholders})
              AND p.date >= ?
            ORDER BY p.date DESC, p.tg_post_id DESC""",
        (*channel_ids, since_date),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
