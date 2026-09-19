import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Railway volume mount is optional. Local development falls back to tracker.db.
_VOLUME_DIR = Path("/app/data")
DB_FILE = str(_VOLUME_DIR / "tracker.db") if _VOLUME_DIR.is_dir() else "tracker.db"


def init_db():
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                username TEXT PRIMARY KEY,
                current_followers INTEGER DEFAULT 0,
                previous_followers INTEGER DEFAULT 0,
                net_change INTEGER DEFAULT 0,
                last_checked TEXT,
                status TEXT DEFAULT 'OK'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()


def set_setting(key: str, value: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default


def delete_setting(key: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        conn.commit()


def add_accounts(usernames: list[str]):
    with sqlite3.connect(DB_FILE) as conn:
        for username in usernames:
            clean = username.strip().lstrip("@").lower()
            if clean:
                conn.execute("INSERT OR IGNORE INTO accounts (username) VALUES (?)", (clean,))
        conn.commit()


def remove_accounts(usernames: list[str]) -> int:
    removed = 0
    with sqlite3.connect(DB_FILE) as conn:
        for username in usernames:
            clean = username.strip().lstrip("@").lower()
            removed += conn.execute("DELETE FROM accounts WHERE username = ?", (clean,)).rowcount
        conn.commit()
    return removed


def get_all_accounts():
    with sqlite3.connect(DB_FILE) as conn:
        return [row[0] for row in conn.execute("SELECT username FROM accounts ORDER BY username").fetchall()]


def count_accounts() -> int:
    with sqlite3.connect(DB_FILE) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])


def update_account_stats(username: str, followers: int, status: str = "OK"):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT current_followers FROM accounts WHERE username = ?", (username,)).fetchone()
        old_current = int(row[0]) if row else 0
        previous = old_current if old_current > 0 else followers
        net = followers - old_current if old_current > 0 else 0
        conn.execute("""
            UPDATE accounts
            SET previous_followers = ?, current_followers = ?, net_change = ?, last_checked = ?, status = ?
            WHERE username = ?
        """, (previous, followers, net, datetime.now(timezone.utc).isoformat(), status, username))
        conn.commit()


def mark_account_failed(username: str, error_msg: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE accounts SET status = ?, last_checked = ? WHERE username = ?",
                     (error_msg[:80], datetime.now(timezone.utc).isoformat(), username))
        conn.commit()


def get_leaderboard_data():
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute("""
            SELECT username, current_followers, net_change, status
            FROM accounts
            ORDER BY net_change DESC, current_followers DESC
        """).fetchall()
