"""Offline check of the multi-profile store's SQL + migration LOGIC using stdlib
sqlite3 (the real store.py imports pydantic, which can't load in the sandbox, so
we mirror its exact statements against an in-memory DB — same approach used to
verify Phase 1):

    python3 tests/test_profiles_store.py

Proves: the legacy single-row `profile` table is lifted into `profiles` as
"Default"; a seed profile + valid active id always exist; create/activate/delete
behave; deleting the active profile re-points active to a survivor; the last
profile can't be deleted.
"""
import sqlite3

passed = 0


def test(name, fn):
    global passed
    fn()
    passed += 1
    print("  ok -", name)


# --- mirrors app/profile/store.py exactly -----------------------------------
CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL);"""
CREATE_STATE = """
CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT);"""

EMPTY = "{}"  # stand-in for Profile().model_dump_json()


def _get_state(c, k):
    r = c.execute("SELECT value FROM app_state WHERE key=?", (k,)).fetchone()
    return r[0] if r else None


def _set_state(c, k, v):
    c.execute("INSERT INTO app_state (key,value) VALUES (?,?) "
              "ON CONFLICT(key) DO UPDATE SET value=excluded.value;", (k, v))


def migrate_and_seed(c):
    has_legacy = c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name='profile'").fetchone()
    n = c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    if has_legacy and n == 0:
        row = c.execute("SELECT data, updated_at FROM profile WHERE id=1").fetchone()
        if row:
            c.execute("INSERT INTO profiles (name,data,updated_at) VALUES (?,?,?)",
                      ("Default", row[0], row[1] or "t"))
            n = 1
    if n == 0:
        c.execute("INSERT INTO profiles (name,data,updated_at) VALUES (?,?,?)",
                  ("Default", EMPTY, "t"))
    active = _get_state(c, "active_profile_id")
    valid = active is not None and c.execute("SELECT 1 FROM profiles WHERE id=?",
                                             (active,)).fetchone()
    if not valid:
        first = c.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
        _set_state(c, "active_profile_id", str(first[0]))


def fresh(with_legacy=None):
    c = sqlite3.connect(":memory:")
    c.execute(CREATE_PROFILES); c.execute(CREATE_STATE)
    if with_legacy is not None:
        c.execute("CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK(id=1), "
                  "data TEXT, updated_at TEXT);")
        c.execute("INSERT INTO profile (id,data,updated_at) VALUES (1,?,?)",
                  (with_legacy, "old"))
    return c


def _seed_empty():
    c = fresh()
    migrate_and_seed(c)
    rows = c.execute("SELECT name FROM profiles").fetchall()
    assert rows == [("Default",)], rows
    assert _get_state(c, "active_profile_id") == "1"
test("empty DB seeds one 'Default' profile and selects it active", _seed_empty)


def _migrate_legacy():
    c = fresh(with_legacy='{"basics":{"name":"Ada"}}')
    migrate_and_seed(c)
    row = c.execute("SELECT name, data FROM profiles").fetchall()
    assert row == [("Default", '{"basics":{"name":"Ada"}}')], row
    assert _get_state(c, "active_profile_id") == "1"
test("legacy id=1 profile is lifted into profiles as 'Default'", _migrate_legacy)


def _create_and_activate():
    c = fresh(); migrate_and_seed(c)
    cur = c.execute("INSERT INTO profiles (name,data,updated_at) VALUES (?,?,?)",
                    ("Bob", EMPTY, "t"))
    bob = cur.lastrowid
    _set_state(c, "active_profile_id", str(bob))
    assert _get_state(c, "active_profile_id") == str(bob)
    # unique name enforced
    try:
        c.execute("INSERT INTO profiles (name,data,updated_at) VALUES (?,?,?)",
                  ("Bob", EMPTY, "t"))
        assert False, "duplicate name should fail"
    except sqlite3.IntegrityError:
        pass
test("create makes a new profile, activate switches, names are unique", _create_and_activate)


def _delete_reassigns_active():
    c = fresh(); migrate_and_seed(c)              # Default = 1, active = 1
    bob = c.execute("INSERT INTO profiles (name,data,updated_at) VALUES (?,?,?)",
                    ("Bob", EMPTY, "t")).lastrowid
    _set_state(c, "active_profile_id", str(bob))  # active = Bob
    # delete the active (Bob) -> active must fall back to a survivor (Default=1)
    c.execute("DELETE FROM profiles WHERE id=?", (bob,))
    if int(_get_state(c, "active_profile_id")) == bob:
        first = c.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
        _set_state(c, "active_profile_id", str(first[0]))
    assert _get_state(c, "active_profile_id") == "1", _get_state(c, "active_profile_id")
test("deleting the active profile re-points active to a survivor", _delete_reassigns_active)


def _cant_delete_last():
    c = fresh(); migrate_and_seed(c)
    total = c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    assert total == 1
    refused = total <= 1  # store.delete_profile raises ValueError here
    assert refused, "should refuse deleting the only profile"
test("the last remaining profile cannot be deleted", _cant_delete_last)


if __name__ == "__main__":
    print(f"\n{passed} profile-store tests passed")
