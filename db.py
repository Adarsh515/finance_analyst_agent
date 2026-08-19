# db.py
# Phase 6.1 - the data layer, written once, on purpose, before any route exists.
#
# WHY SQLITE. One file, no daemon, no connection string, no container. The whole corpus is
# 5 filings and the whole traffic is one analyst at a time; Postgres would buy concurrency
# nobody needs in exchange for a deployment problem in Phase 7. SQLite is also the only
# database here that the instructor can open by double-clicking it.
#
# WHY THE SCHEMA IS BIGGER THAN 6.2 NEEDS. A migration on live user data is the expensive
# part of every app, and the cheap moment to avoid one is now, while there are zero rows.
# Everything below that is not used by 6.2 is there because a LATER phase needs it and
# adding it later would mean rewriting rows that already exist.
#
# NOTHING IN THIS FILE COSTS MONEY. `python db.py` runs a full end-to-end self-test against
# an in-memory database: no API key, no network, no tokens. That is deliberate - a data
# layer that can only be tested by paying for it will stop being tested.

import json
import os
import secrets
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("APP_DB", "app.db")

# Schema version. Every change gets a new numbered entry in MIGRATIONS below and bumps this.
# Recording the version from day one costs one table and removes the question "which shape is
# this file?" forever - a question that is unanswerable at exactly the moment it matters,
# which is when someone else's copy behaves differently from yours.
#
# v1  2026-08-18  Phase 6.1  baseline: users, credentials, sessions, conversations,
#                            messages, traces, trace_calls
# v2  2026-08-18  Phase 6.2  login_attempts (rate limiting)
# v3  2026-08-18  Phase 6.5  answer_cache (exact-match, fingerprint in the key)
# v4  2026-08-18  Phase 6.6  traces.retrieval_json + answer_cache.retrieval_json
# v5  2026-08-19  Phase 6.7  traces.saved_* (what the first run cost) + answer_cache.is_refusal
SCHEMA_VERSION = 5


def utcnow():
    """ISO-8601 UTC, second precision, sortable as a plain string.

    Stored as TEXT rather than as a unix integer so that `sqlite3 app.db "select * from
    messages"` is readable by a human with no conversion step. Sorting still works because
    ISO-8601 sorts lexicographically, which is the whole reason the format exists.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- schema ------------------------------------------------------------------------------
#
# ON `users` vs `credentials`, and why this DEPARTS from the plan written in PROJECT_TRACKER.
#
# The plan said: `users(..., auth_provider, password_hash NULLABLE)`, so that an OAuth user
# needs no schema change. That solves the wrong half of the problem. The case that actually
# breaks is a person who signs up with email+password in 6.2 and then clicks "Sign in with
# Google" in 6.9 with the SAME address. With one provider column per user you get either a
# duplicate account or a migration - and avoiding the migration was the entire stated reason
# for designing this table carefully.
#
# So identity is split from proof-of-identity:
#     users        - who someone is (one row per person, keyed by email)
#     credentials  - how they prove it (one row per method they have)
# Linking Google to an existing account in 6.9 becomes an INSERT. Local-only stays exactly
# as simple as it was. The cost today is one extra table and one JOIN in the login path.

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

-- One row per way this person can log in. A local account has password_hash set and
-- provider_subject NULL; an OAuth account is the mirror image. The CHECK makes the
-- impossible states unrepresentable rather than merely discouraged, because a rule that
-- lives only in application code is a rule that a second caller does not know about.
CREATE TABLE IF NOT EXISTS credentials (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL CHECK (provider IN ('local','google','github')),
    password_hash    TEXT,
    provider_subject TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE (user_id, provider),
    UNIQUE (provider, provider_subject),
    CHECK (
        (provider =  'local' AND password_hash IS NOT NULL AND provider_subject IS NULL) OR
        (provider <> 'local' AND password_hash IS     NULL AND provider_subject IS NOT NULL)
    )
);

-- Server-side sessions, so that "log out" and "log out everywhere" are real operations.
-- ONLY A HASH OF THE TOKEN IS STORED, for the same reason passwords are hashed: a stolen
-- copy of app.db must not be a set of working session cookies. The raw token exists in the
-- user's cookie and in one local variable at creation time, and nowhere else.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    revoked_at  TEXT,
    user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'New chat',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    archived_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_conv_user ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(conversation_id, id);

-- One row per ANSWERED question. This table is what the trace panel reads, and the contract
-- written in PROJECT_TRACKER is that NOTHING IN THE UI IS RECOMPUTED: the panel is a SELECT.
-- If the product recomputed its own numbers, the product and the eval would drift, and the
-- drift would be invisible because both sides would look self-consistent.
CREATE TABLE IF NOT EXISTS traces (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          INTEGER NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id     INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    question_raw        TEXT NOT NULL,   -- exactly what the user typed
    question_rewritten  TEXT,            -- what the 6.4 rewriter produced; NULL = no rewrite

    jobs_json           TEXT,            -- the planner's SearchJob list, verbatim
    filings_json        TEXT,            -- ["NVIDIA FY2026 10-K", ...] actually retrieved from
    chunk_ids_json      TEXT,            -- chunk ids in the context, in order
    rounds              INTEGER,
    reflect_fired       INTEGER NOT NULL DEFAULT 0,
    guard_fired         TEXT NOT NULL DEFAULT '',   -- '' = no guard, else the reason string
    cache_hit           INTEGER NOT NULL DEFAULT 0, -- Phase 6.5

    -- Cost, denormalised on purpose. trace_calls below holds the per-call truth; these are
    -- the sums, stored so the conversation list can show a running total without a GROUP BY
    -- over every call ever made. They are written in the same transaction as the calls.
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    usd                 REAL    NOT NULL DEFAULT 0.0,
    seconds             REAL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trace_msg  ON traces(message_id);
CREATE INDEX IF NOT EXISTS ix_trace_user ON traces(user_id, created_at DESC);

-- One row per PAID CALL - planner, generation, requarantine retry, reflect. This is the same
-- (label, input_tokens, output_tokens, model) tuple that run_eval.py already captures by
-- wrapping judges.log_cost, which is what makes "the product and the measurement cannot
-- drift" a fact about the code rather than an intention.
CREATE TABLE IF NOT EXISTS trace_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id      INTEGER NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    label         TEXT NOT NULL,        -- 'agent-plan', 'agent-generation', ...
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    usd           REAL NOT NULL,
    UNIQUE (trace_id, seq)
);
"""


# --- migrations ---------------------------------------------------------------------------
# SCHEMA above is the v1 BASELINE and is never edited again. Every later change is a numbered
# entry here, applied in order to whatever version the file is already at.
#
# This is deliberately more machinery than one extra table needs. The point is that the first
# migration happens NOW, while `app.db` holds one seeded demo row and a mistake costs nothing
# - not in Phase 6.6 with the learner's real chat history in it. A migration path that has
# never been executed is not a migration path, it is a plan.

MIGRATIONS = {
    # Phase 6.2. Deliberately NOT foreign-keyed to users: the whole purpose is to record
    # attempts against addresses that do not exist, which is exactly when someone is
    # guessing. A FK here would silently drop the attacker's most interesting rows.
    2: """
    CREATE TABLE IF NOT EXISTS login_attempts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        email        TEXT NOT NULL COLLATE NOCASE,
        ip           TEXT,
        succeeded    INTEGER NOT NULL,
        attempted_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_attempts_email ON login_attempts(email, attempted_at);
    CREATE INDEX IF NOT EXISTS ix_attempts_ip    ON login_attempts(ip, attempted_at);
    """,
    # Phase 6.5. GLOBAL by design - these are answers about public filings, identical for
    # every reader, so per-user rows would cost hit rate and buy nothing. `fingerprint` is
    # part of the KEY (see cache.key_for), not merely stored here, so a rebuilt index cannot
    # reach an old row rather than merely being expected not to.
    3: """
    CREATE TABLE IF NOT EXISTS answer_cache (
        key_hash            TEXT PRIMARY KEY,
        normalised_question TEXT NOT NULL,
        question            TEXT NOT NULL,
        answer              TEXT NOT NULL,
        context             TEXT,
        jobs_json           TEXT,
        filings_json        TEXT,
        chunk_ids_json      TEXT,
        rounds              INTEGER,
        input_tokens        INTEGER NOT NULL DEFAULT 0,
        output_tokens       INTEGER NOT NULL DEFAULT 0,
        usd                 REAL    NOT NULL DEFAULT 0.0,
        fingerprint         TEXT NOT NULL,
        created_by          INTEGER,
        created_at          TEXT NOT NULL,
        hits                INTEGER NOT NULL DEFAULT 0,
        last_hit_at         TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_cache_fp ON answer_cache(fingerprint);
    """,
    # Phase 6.6. What Chroma returned per job and which candidates survived selection. It is
    # a RECORD for the trace panel: the UI shows how nearest-neighbour selection actually
    # went, instead of asking the reader to take "retrieval worked" on trust.
    4: """
    ALTER TABLE traces ADD COLUMN retrieval_json TEXT;
    ALTER TABLE answer_cache ADD COLUMN retrieval_json TEXT;
    """,
    # Phase 6.7. Two changes, both about telling the truth on a cache hit.
    #
    # traces.saved_* - what the FIRST run of this question actually cost. A hit's own cost is
    # already in traces.usd (zero on a single-turn hit, the price of the rewrite on a
    # follow-up). Without the original alongside it there is no honest way to say what the
    # cache is worth: the UI would either claim a saving it cannot evidence, or show a zero
    # and imply the answer was free to create. Stored per trace, not recomputed in the UI,
    # for the same reason as every other number in the panel - see the 6.1 contract.
    #
    # answer_cache.is_refusal - refusals are cacheable from 6.7 and they are not ordinary
    # answers. Marking them lets the panel say WHICH kind of thing came back from the cache,
    # lets stats() report them apart from real answers, and makes it possible to purge only
    # the refusals if the corpus grows to cover one.
    5: """
    ALTER TABLE traces ADD COLUMN saved_usd REAL NOT NULL DEFAULT 0.0;
    ALTER TABLE traces ADD COLUMN saved_input_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE traces ADD COLUMN saved_output_tokens INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE answer_cache ADD COLUMN is_refusal INTEGER NOT NULL DEFAULT 0;
    """,
}


def migrate(conn):
    """Apply every migration newer than the file's recorded version. Returns those applied."""
    current = schema_version(conn)
    applied = []
    for version in sorted(MIGRATIONS):
        if version > current:
            conn.executescript(MIGRATIONS[version])
            conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                         "VALUES (?,?)", (version, utcnow()))
            conn.commit()
            applied.append(version)
    return applied


def connect(path=None):
    """Open a connection with the three PRAGMAs that SQLite does NOT set for you.

    foreign_keys is OFF by default in SQLite - every ON DELETE CASCADE above is decoration
    until it is switched on, PER CONNECTION. That is a silent failure: the schema reads as
    if it enforces something it does not, and the first sign of trouble is orphaned rows
    months later. It is switched on here, and the self-test checks that it actually bit.
    """
    # check_same_thread=False, and the reason is specific rather than a shrug.
    #
    # FastAPI resolves a dependency and runs the endpoint on its worker THREAD POOL, and it
    # does not promise both land on the same thread. A connection opened while resolving
    # `get_db` in thread A and used by the endpoint in thread B raises
    # "SQLite objects created in a thread can only be used in that same thread" - a 500 on
    # /conversations that looked, in the browser, exactly like "my history disappeared".
    #
    # This is SAFE here and it is worth being precise about why: the connection is handed
    # from one thread to the next SEQUENTIALLY, one request at a time, and is never used by
    # two threads at once. check_same_thread=False disables Python's ownership check; it does
    # NOT make a connection safe to share CONCURRENTLY, and nothing in this repo does that.
    # One connection per request stays the rule.
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")    # readers do not block the writer
    conn.execute("PRAGMA busy_timeout = 5000")   # wait, do not throw, on a brief lock
    return conn


def init_db(conn):
    """Create the v1 baseline if absent, then bring the file up to date. Safe on every start."""
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (1,?)",
                 (utcnow(),))
    conn.commit()
    migrate(conn)
    return conn


def schema_version(conn):
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return row["v"] if row and row["v"] is not None else 0


# --- users and credentials ----------------------------------------------------------------
# No password hashing lives here. Choosing argon2 vs bcrypt, the work factor, and the timing
# discipline of the login path are Phase 6.2's job and they get their own tests. This layer
# stores whatever opaque string it is handed. Keeping the hash function out of the data layer
# is also what makes THIS file testable with no dependencies.

def create_user(conn, email, display_name=None):
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO users (email, display_name, created_at) VALUES (?,?,?)",
        (email.strip(), display_name, now))
    conn.commit()
    return cur.lastrowid


def get_user_by_email(conn, email):
    return conn.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()


def add_local_credential(conn, user_id, password_hash):
    conn.execute(
        "INSERT INTO credentials (user_id, provider, password_hash, created_at) "
        "VALUES (?, 'local', ?, ?)", (user_id, password_hash, utcnow()))
    conn.commit()


def add_oauth_credential(conn, user_id, provider, subject):
    """Phase 6.9 uses this. It exists now so that 6.9 is an INSERT, not a migration."""
    conn.execute(
        "INSERT INTO credentials (user_id, provider, provider_subject, created_at) "
        "VALUES (?,?,?,?)", (user_id, provider, subject, utcnow()))
    conn.commit()


def get_credential(conn, user_id, provider):
    return conn.execute(
        "SELECT * FROM credentials WHERE user_id = ? AND provider = ?",
        (user_id, provider)).fetchone()


def touch_login(conn, user_id):
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (utcnow(), user_id))
    conn.commit()


# --- sessions -----------------------------------------------------------------------------

SESSION_DAYS = 14


def _hash_token(token):
    """SHA-256, no salt, on purpose.

    A session token is 32 bytes of `secrets.token_urlsafe` - already uniformly random and
    high entropy - so there is no dictionary to attack and nothing for a salt to defend
    against. Password hashing is a different problem with a different answer (6.2), and
    reusing the reasoning across the two is how people end up with a slow session lookup
    or a fast password check.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, user_id, user_agent=None, days=SESSION_DAYS):
    """Return the RAW token. It is never stored; only its hash is."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, user_agent) "
        "VALUES (?,?,?,?,?)",
        (_hash_token(token), user_id,
         now.isoformat().replace("+00:00", "Z"),
         (now + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
         user_agent))
    conn.commit()
    return token


def session_user(conn, token):
    """Resolve a raw cookie token to a user row, or None. Expiry and revocation in SQL."""
    if not token:
        return None
    return conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?",
        (_hash_token(token), utcnow())).fetchone()


def revoke_session(conn, token):
    conn.execute("UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                 (utcnow(), _hash_token(token)))
    conn.commit()


def revoke_all_sessions(conn, user_id):
    conn.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                 (utcnow(), user_id))
    conn.commit()


# --- conversations and messages -------------------------------------------------------------

def create_conversation(conn, user_id, title="New chat"):
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?,?,?,?)",
        (user_id, title, now, now))
    conn.commit()
    return cur.lastrowid


def list_conversations(conn, user_id, include_archived=False):
    sql = ("SELECT * FROM conversations WHERE user_id = ?"
           + ("" if include_archived else " AND archived_at IS NULL")
           + " ORDER BY updated_at DESC, id DESC")
    return conn.execute(sql, (user_id,)).fetchall()


def add_message(conn, conversation_id, role, content):
    now = utcnow()
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
        (conversation_id, role, content, now))
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
    conn.commit()
    return cur.lastrowid


def list_messages(conn, conversation_id):
    """Messages plus the few trace fields the message list itself needs to render.

    The badges above an answer - served from cache, guard fired, follow-up rewritten - must
    look the SAME whether the message has just been answered or is being read back from
    history a week later. The live path has the trace in hand from /ask; the history path did
    not, so a badge built only from the live response would appear on a fresh answer and
    vanish on reload. Fetching the full trace per message instead would mean forty requests to
    open a forty-message conversation, and the panel already loads that lazily on expand.
    A LEFT JOIN of five columns costs one query and removes the whole divergence.
    """
    return conn.execute(
        "SELECT m.*, t.cache_hit, t.usd, t.saved_usd, t.guard_fired, t.reflect_fired, "
        "       t.question_rewritten "
        "FROM messages m LEFT JOIN traces t ON t.message_id = m.id "
        "WHERE m.conversation_id = ? ORDER BY m.id", (conversation_id,)).fetchall()


def history_pairs(conn, conversation_id, limit_turns=6):
    """The last N turns as [(role, content)], oldest first - the rewriter's only input.

    Bounded HERE rather than at the call site, because an unbounded history is both a cost
    leak and, from Phase 6.4 on, an attack surface: everything returned by this function is
    attacker-authored text that will be fed to a model.
    """
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? "
        "AND role IN ('user','assistant') ORDER BY id DESC LIMIT ?",
        (conversation_id, limit_turns * 2)).fetchall()
    return [(r["role"], r["content"]) for r in reversed(rows)]


# --- traces --------------------------------------------------------------------------------

def save_trace(conn, *, message_id, conversation_id, user_id, question_raw,
               question_rewritten=None, jobs=None, filings=None, chunk_ids=None,
               rounds=None, reflect_fired=False, guard_fired="", cache_hit=False,
               calls=(), seconds=None, retrieval=None,
               saved_usd=0.0, saved_input_tokens=0, saved_output_tokens=0):
    """Write one answered question's full provenance, header and per-call rows, atomically.

    `calls` is the list of (label, input_tokens, output_tokens, model, usd) tuples captured
    from log_cost - the same tuple run_eval.py already collects. The header totals are SUMs
    of that list computed here, so the two can never disagree by construction; nobody passes
    a total in.

    Keyword-only arguments are not a style choice. This function takes three consecutive
    integer ids, and Phase 1 of this project lost a day to a judge whose reference and
    prediction were swapped by positional-argument order.
    """
    rows = [(i + 1, lab, model, int(intok), int(outok), float(usd))
            for i, (lab, intok, outok, model, usd) in enumerate(calls)]
    cur = conn.execute(
        "INSERT INTO traces (message_id, conversation_id, user_id, question_raw, "
        " question_rewritten, jobs_json, filings_json, chunk_ids_json, rounds, "
        " reflect_fired, guard_fired, cache_hit, input_tokens, output_tokens, usd, "
        " seconds, created_at, retrieval_json, "
        " saved_usd, saved_input_tokens, saved_output_tokens) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (message_id, conversation_id, user_id, question_raw, question_rewritten,
         json.dumps(jobs) if jobs is not None else None,
         json.dumps(filings) if filings is not None else None,
         json.dumps(chunk_ids) if chunk_ids is not None else None,
         rounds, int(bool(reflect_fired)), guard_fired or "", int(bool(cache_hit)),
         sum(r[3] for r in rows), sum(r[4] for r in rows), sum(r[5] for r in rows),
         seconds, utcnow(),
         json.dumps(retrieval) if retrieval is not None else None,
         # What the first run cost. Only ever non-zero on a cache hit, and the caller reads it
         # off the cached row rather than estimating it - a "saving" the product invented
         # would be marketing, not measurement.
         float(saved_usd), int(saved_input_tokens), int(saved_output_tokens)))
    trace_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO trace_calls (trace_id, seq, label, model, input_tokens, output_tokens, usd) "
        "VALUES (?,?,?,?,?,?,?)", [(trace_id, *r) for r in rows])
    conn.commit()
    return trace_id


def get_trace(conn, message_id):
    """Everything the trace panel shows, as stored. No arithmetic happens here."""
    t = conn.execute("SELECT * FROM traces WHERE message_id = ?", (message_id,)).fetchone()
    if t is None:
        return None
    out = dict(t)
    for k in ("jobs_json", "filings_json", "chunk_ids_json", "retrieval_json"):
        out[k[:-5]] = json.loads(out.pop(k)) if out[k] else None
    out["calls"] = [dict(r) for r in conn.execute(
        "SELECT seq, label, model, input_tokens, output_tokens, usd FROM trace_calls "
        "WHERE trace_id = ? ORDER BY seq", (t["id"],)).fetchall()]
    return out


# --- login attempts (Phase 6.2 rate limiting) -----------------------------------------------
# Stored, not held in memory, for one reason: an in-memory counter resets when the process
# restarts, and "restart the server" is not a step an attacker finds difficult.

def record_attempt(conn, email, succeeded, ip=None):
    conn.execute("INSERT INTO login_attempts (email, ip, succeeded, attempted_at) "
                 "VALUES (?,?,?,?)", (email.strip(), ip, int(bool(succeeded)), utcnow()))
    conn.commit()


def recent_failures(conn, since_iso, email=None, ip=None):
    """Failures for one address or one IP inside a time window, counted only since the last
    SUCCESS. A successful login clears the slate; otherwise one legitimate typo a month
    accumulates into a permanent lockout on a long-lived account.

    THE TIME WINDOW AND THE ORDERING ARE TWO DIFFERENT JOBS, and this function was wrong the
    first time for mixing them. `utcnow()` is second-precision, chosen so the tables are
    readable in a plain `sqlite3` prompt - which means a success and the failure that follows
    it routinely carry the SAME timestamp, and `attempted_at > last_success_time` then drops
    the failure. A brute-force loop lands many attempts per second, so this is not a corner
    case; it is the normal case for the exact traffic this function exists to count.

    So: `since_iso` bounds the WINDOW (a wall-clock question), and the autoincrement `id`
    orders EVENTS (a sequence question). A second-precision timestamp is not a sort key.
    """
    field, value = ("email", email.strip()) if email is not None else ("ip", ip)
    if value is None:
        return 0
    last_ok_id = conn.execute(
        f"SELECT COALESCE(MAX(id), 0) AS i FROM login_attempts "
        f"WHERE {field} = ? AND succeeded = 1", (value,)).fetchone()["i"]
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM login_attempts "
        f"WHERE {field} = ? AND succeeded = 0 AND id > ? AND attempted_at >= ?",
        (value, last_ok_id, since_iso)).fetchone()["n"]


def user_spend(conn, user_id):
    row = conn.execute(
        "SELECT COUNT(*) AS questions, COALESCE(SUM(input_tokens),0) AS input_tokens, "
        "COALESCE(SUM(output_tokens),0) AS output_tokens, COALESCE(SUM(usd),0.0) AS usd "
        "FROM traces WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row)


# --- self-test -------------------------------------------------------------------------------
# Runs against :memory:. No API key, no network, no cost. Every assertion below exists
# because the thing it checks can fail SILENTLY - a cascade that does not cascade, a CHECK
# that does not check, a total that drifts from its parts.

if __name__ == "__main__":
    c = init_db(connect(":memory:"))
    ok = 0

    assert schema_version(c) == SCHEMA_VERSION
    ok += 1

    # The migration path is exercised, not assumed. A v1 file must come up to v2 by itself,
    # and re-running must be a no-op - a migration that is not idempotent will be applied
    # twice by the first person who restarts the server during a deploy.
    v1 = connect(":memory:")
    v1.executescript(SCHEMA)
    v1.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)", (utcnow(),))
    v1.commit()
    assert schema_version(v1) == 1
    # Derived from MIGRATIONS, not typed out. A hard-coded [2, 3, 4] has to be edited by hand
    # every time a migration is added, and the edit is invisible until the assert fails on
    # someone else's machine - which is what happened when v5 landed.
    expected = sorted(v for v in MIGRATIONS if v > 1)
    assert migrate(v1) == expected and schema_version(v1) == SCHEMA_VERSION
    assert max(expected) == SCHEMA_VERSION, \
        f"SCHEMA_VERSION is {SCHEMA_VERSION} but the newest migration is {max(expected)}"
    assert migrate(v1) == [], "migrate() is not idempotent - it re-applied a done migration"
    v1.execute("SELECT COUNT(*) FROM login_attempts")     # raises if the table is missing
    v1.execute("SELECT COUNT(*) FROM answer_cache")
    v1.execute("SELECT retrieval_json FROM traces LIMIT 1")
    v1.execute("SELECT saved_usd, saved_input_tokens, saved_output_tokens FROM traces LIMIT 1")
    v1.execute("SELECT is_refusal FROM answer_cache LIMIT 1")
    ok += 1

    uid = create_user(c, "Adarsh@Example.COM", "Adarsh")
    add_local_credential(c, uid, "argon2$placeholder")
    # email is COLLATE NOCASE: the same person must not be able to create two accounts by
    # changing the capitalisation of their own address.
    assert get_user_by_email(c, "adarsh@example.com")["id"] == uid
    try:
        create_user(c, "ADARSH@example.com")
        raise SystemExit("FAIL: duplicate email accepted (case-insensitive UNIQUE is off)")
    except sqlite3.IntegrityError:
        ok += 1

    # a local credential with no password, and an oauth credential with a password, are both
    # meant to be unrepresentable - not merely discouraged in application code.
    for bad in ("INSERT INTO credentials (user_id, provider, created_at) VALUES (?, 'local', ?)",
                "INSERT INTO credentials (user_id, provider, password_hash, provider_subject,"
                " created_at) VALUES (?, 'google', 'x', 'sub-1', ?)"):
        try:
            c.execute(bad, (uid, utcnow()))
            raise SystemExit(f"FAIL: CHECK constraint did not fire for: {bad[:60]}")
        except sqlite3.IntegrityError:
            ok += 1

    # Phase 6.9 rehearsed today: linking Google to the SAME account is an INSERT.
    add_oauth_credential(c, uid, "google", "google-sub-123")
    assert get_credential(c, uid, "local")["password_hash"] == "argon2$placeholder"
    assert get_credential(c, uid, "google")["provider_subject"] == "google-sub-123"
    ok += 1

    tok = create_session(c, uid, user_agent="self-test")
    assert session_user(c, tok)["id"] == uid
    # the raw token must not be recoverable from the database
    stored = c.execute("SELECT token_hash FROM sessions").fetchone()["token_hash"]
    assert tok not in stored and len(stored) == 64
    ok += 1
    revoke_session(c, tok)
    assert session_user(c, tok) is None
    assert session_user(c, "not-a-real-token") is None
    ok += 1

    conv = create_conversation(c, uid, "NVIDIA revenue")
    m_user = add_message(c, conv, "user", "What was NVIDIA's total revenue for fiscal year 2026?")
    m_bot = add_message(c, conv, "assistant", "NVIDIA's total revenue for FY2026 was $215,938 million.")
    assert [r["role"] for r in list_messages(c, conv)] == ["user", "assistant"]
    assert history_pairs(c, conv)[0][1].startswith("What was NVIDIA")
    ok += 1

    try:
        c.execute("INSERT INTO messages (conversation_id, role, content, created_at) "
                  "VALUES (?, 'robot', 'x', ?)", (conv, utcnow()))
        raise SystemExit("FAIL: role CHECK constraint did not fire")
    except sqlite3.IntegrityError:
        ok += 1

    calls = [("agent-plan", 900, 120, "gemini-3.1-flash-lite", 0.0002),
             ("agent-generation", 3736, 210, "gemini-3.1-flash-lite", 0.00062),
             ("agent-generation-requarantine", 3100, 190, "gemini-3.1-flash-lite", 0.00053)]
    tid = save_trace(c, message_id=m_bot, conversation_id=conv, user_id=uid,
                     question_raw="What was NVIDIA's total revenue for fiscal year 2026?",
                     question_rewritten=None, jobs=[{"company": "NVIDIA", "query": "total revenue"}],
                     filings=["NVIDIA FY2026 10-K"], chunk_ids=["nvda-fy2026-t12-p0"],
                     rounds=1, reflect_fired=False,
                     guard_fired="quarantine:['999999'] -> regenerated from trusted chunks only",
                     calls=calls, seconds=8.4,
                     retrieval=[{"query": "revenue", "candidates": []}])
    t = get_trace(c, m_bot)
    # the header totals are SUMs of the call rows, computed in one place, so they cannot drift
    assert t["input_tokens"] == 900 + 3736 + 3100
    assert t["output_tokens"] == 120 + 210 + 190
    assert abs(t["usd"] - sum(x[4] for x in calls)) < 1e-12
    assert len(t["calls"]) == 3 and t["calls"][0]["label"] == "agent-plan"
    assert t["filings"] == ["NVIDIA FY2026 10-K"] and t["guard_fired"].startswith("quarantine:")
    assert t["retrieval"] == [{"query": "revenue", "candidates": []}], t.get("retrieval")
    # a paid run records no saving - "avoided by the cache" must be zero unless a cache hit
    # actually avoided something
    assert t["saved_usd"] == 0.0 and t["saved_input_tokens"] == 0
    ok += 1

    # ...and a cache hit records BOTH numbers: what the reader paid, and what the first run of
    # this question paid. The panel prints these side by side, so if they could not both be
    # stored the saving would have to be guessed in JavaScript.
    m_hit = add_message(c, conv, "assistant", "Revenue was $215,938 million.")
    save_trace(c, message_id=m_hit, conversation_id=conv, user_id=uid,
               question_raw="And AMD?", question_rewritten="What was AMD's total revenue?",
               cache_hit=True,
               calls=[("agent-rewrite", 210, 18, "gemini-3.1-flash-lite", 0.000048)],
               saved_usd=0.00062, saved_input_tokens=3736, saved_output_tokens=210)
    th = get_trace(c, m_hit)
    assert th["cache_hit"] == 1
    assert abs(th["usd"] - 0.000048) < 1e-12, "a follow-up cache hit is NOT free - the rewrite"
    assert abs(th["saved_usd"] - 0.00062) < 1e-12 and th["saved_input_tokens"] == 3736
    ok += 1

    # Spend counts BOTH traces, and counts the cache hit at what it really cost. The avoided
    # 3,736 tokens are deliberately NOT in here: user_spend is what this reader was charged,
    # not what they would have been charged in a world without a cache.
    spend = user_spend(c, uid)
    assert spend["questions"] == 2 and spend["input_tokens"] == 7736 + 210, spend
    ok += 1

    # failures accumulate, and a SUCCESS clears the slate - otherwise one typo a month
    # eventually locks a long-lived account out permanently.
    epoch = "1970-01-01T00:00:00Z"
    for _ in range(3):
        record_attempt(c, "attacker@example.com", False, ip="10.0.0.9")
    assert recent_failures(c, epoch, email="attacker@example.com") == 3
    assert recent_failures(c, epoch, ip="10.0.0.9") == 3
    # attempts are recorded for addresses that do not exist - that is the interesting case
    assert get_user_by_email(c, "attacker@example.com") is None
    # These three land in the SAME SECOND, which is the case that broke the first version:
    # ordering by a second-precision timestamp dropped the failures that followed a success.
    record_attempt(c, "attacker@example.com", True, ip="10.0.0.9")
    record_attempt(c, "attacker@example.com", False, ip="10.0.0.9")
    record_attempt(c, "attacker@example.com", False, ip="10.0.0.9")
    rows = c.execute("SELECT attempted_at FROM login_attempts ORDER BY id DESC LIMIT 3").fetchall()
    assert len({r["attempted_at"] for r in rows}) == 1, "same-second case not exercised"
    assert recent_failures(c, epoch, email="attacker@example.com") == 2
    # a window in the future must exclude everything, so the window is not vacuous either
    assert recent_failures(c, "2099-01-01T00:00:00Z", email="attacker@example.com") == 0
    ok += 1

    # one trace per assistant message, enforced by the database rather than by a comment
    try:
        save_trace(c, message_id=m_bot, conversation_id=conv, user_id=uid, question_raw="dup")
        raise SystemExit("FAIL: a second trace was allowed for one message")
    except sqlite3.IntegrityError:
        ok += 1

    # the cascade actually cascades - which it does NOT without PRAGMA foreign_keys = ON
    c.execute("DELETE FROM users WHERE id = ?", (uid,))
    c.commit()
    for table in ("credentials", "sessions", "conversations", "messages", "traces", "trace_calls"):
        n = c.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        assert n == 0, f"FAIL: {table} kept {n} orphan row(s) - foreign_keys pragma is off"
    ok += 1

    print(f"db.py self-test: {ok}/{ok} checks passed, schema v{SCHEMA_VERSION}, $0.00 spent")
