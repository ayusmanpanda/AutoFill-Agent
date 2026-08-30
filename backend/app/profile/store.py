"""Multi-profile SQLite store.

Each person gets their own row in `profiles` (own name + JSON document); exactly
one profile is "active" at a time (tracked in `app_state`). Every existing
consumer keeps calling `get_profile()` / `save_profile()` with no arguments and
transparently reads/writes the ACTIVE profile — so multi-profile support drops in
without touching the fill / pdf / learn / generate code paths.

The whole profile is still stored as one JSON document; Pydantic validates the
shape on the way in and out. The DB file lives at backend/data/profile.db.

A one-time migration lifts the old single-row `profile` table (id = 1) into
`profiles` as a profile named "Default", so existing users lose nothing.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .schema import Profile

# .../app/profile/store.py -> parents[2] == backend/
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "profile.db"

_CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

_CREATE_STATE = """
CREATE TABLE IF NOT EXISTS app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_CREATE_PROFILES)
    conn.execute(_CREATE_STATE)
    return conn


def _get_state(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
        (key, value),
    )


def _migrate_and_seed(conn: sqlite3.Connection) -> None:
    """Bring the DB up to the multi-profile shape, non-destructively."""
    # 1. Lift the legacy single-row `profile` table into `profiles` as "Default".
    has_legacy = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='profile'"
    ).fetchone()
    n_profiles = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    if has_legacy and n_profiles == 0:
        row = conn.execute("SELECT data, updated_at FROM profile WHERE id = 1").fetchone()
        if row:
            conn.execute(
                "INSERT INTO profiles (name, data, updated_at) VALUES (?, ?, ?)",
                ("Default", row[0], row[1] or _now()),
            )
            n_profiles = 1

    # 2. Guarantee at least one profile exists.
    if n_profiles == 0:
        conn.execute(
            "INSERT INTO profiles (name, data, updated_at) VALUES (?, ?, ?)",
            ("Default", Profile().model_dump_json(), _now()),
        )

    # 3. Guarantee a valid active profile is selected.
    active = _get_state(conn, "active_profile_id")
    valid = active is not None and conn.execute(
        "SELECT 1 FROM profiles WHERE id = ?", (active,)
    ).fetchone()
    if not valid:
        first = conn.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
        _set_state(conn, "active_profile_id", str(first[0]))


def init_db() -> None:
    conn = _connect()
    try:
        _migrate_and_seed(conn)
        conn.commit()
    finally:
        conn.close()


# ----------------------------- active-profile helpers -----------------------

def get_active_id() -> int:
    conn = _connect()
    try:
        _migrate_and_seed(conn)
        conn.commit()
        return int(_get_state(conn, "active_profile_id"))
    finally:
        conn.close()


def set_active(profile_id: int) -> int:
    """Make `profile_id` the active profile. Raises KeyError if it doesn't exist."""
    conn = _connect()
    try:
        exists = conn.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not exists:
            raise KeyError(profile_id)
        _set_state(conn, "active_profile_id", str(profile_id))
        conn.commit()
        return profile_id
    finally:
        conn.close()


# ----------------------------- profile CRUD ---------------------------------

def list_profiles() -> List[dict]:
    """All profiles as {id, name, updated_at}, plus which one is active."""
    conn = _connect()
    try:
        _migrate_and_seed(conn)
        conn.commit()
        rows = conn.execute(
            "SELECT id, name, updated_at FROM profiles ORDER BY id"
        ).fetchall()
        active = int(_get_state(conn, "active_profile_id"))
    finally:
        conn.close()
    return [
        {"id": r[0], "name": r[1], "updated_at": r[2], "active": r[0] == active}
        for r in rows
    ]


def create_profile(name: str, profile: Optional[Profile] = None,
                   activate: bool = True) -> dict:
    """Create a new named profile. Returns {id, name}. Raises ValueError on
    a blank or duplicate name."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name is required.")
    data = (profile or Profile()).model_dump_json()
    conn = _connect()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO profiles (name, data, updated_at) VALUES (?, ?, ?)",
                (name, data, _now()),
            )
        except sqlite3.IntegrityError:
            raise ValueError("A profile named %r already exists." % name)
        new_id = int(cur.lastrowid)
        if activate:
            _set_state(conn, "active_profile_id", str(new_id))
        conn.commit()
    finally:
        conn.close()
    return {"id": new_id, "name": name}


def rename_profile(profile_id: int, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name is required.")
    conn = _connect()
    try:
        exists = conn.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not exists:
            raise KeyError(profile_id)
        try:
            conn.execute(
                "UPDATE profiles SET name = ?, updated_at = ? WHERE id = ?",
                (name, _now(), profile_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError("A profile named %r already exists." % name)
        conn.commit()
    finally:
        conn.close()
    return {"id": profile_id, "name": name}


def delete_profile(profile_id: int) -> int:
    """Delete a profile. Refuses to delete the last remaining one. If the active
    profile is deleted, the lowest-id survivor becomes active. Returns the
    active id afterward."""
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        if total <= 1:
            raise ValueError("Can't delete the only profile.")
        exists = conn.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not exists:
            raise KeyError(profile_id)
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        active = _get_state(conn, "active_profile_id")
        if active is None or int(active) == profile_id:
            first = conn.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
            _set_state(conn, "active_profile_id", str(first[0]))
        conn.commit()
        return int(_get_state(conn, "active_profile_id"))
    finally:
        conn.close()


# ------------------------- read / write a profile ---------------------------

def get_profile(profile_id: Optional[int] = None) -> Profile:
    """Read a profile (the ACTIVE one when `profile_id` is None)."""
    conn = _connect()
    try:
        _migrate_and_seed(conn)
        conn.commit()
        pid = profile_id if profile_id is not None else int(_get_state(conn, "active_profile_id"))
        row = conn.execute("SELECT data FROM profiles WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return Profile()
    return Profile.model_validate_json(row[0])


def save_profile(profile: Profile, profile_id: Optional[int] = None) -> Profile:
    """Save into a profile (the ACTIVE one when `profile_id` is None)."""
    conn = _connect()
    try:
        _migrate_and_seed(conn)
        pid = profile_id if profile_id is not None else int(_get_state(conn, "active_profile_id"))
        conn.execute(
            "UPDATE profiles SET data = ?, updated_at = ? WHERE id = ?",
            (profile.model_dump_json(), _now(), pid),
        )
        conn.commit()
    finally:
        conn.close()
    return profile


# Ensure the tables exist (and legacy data is migrated) on import.
init_db()
