# reset_db.py
# Phase 6.1 - create, wipe, inspect or seed app.db.
#
# WHY THIS FILE EXISTS AT ALL. From 6.2 onwards this repo stores real email addresses and
# password hashes. `app.db` is gitignored, so it never travels - but "it is gitignored" only
# protects the instructor's copy, not mine, and a demo database that accumulates months of
# my own logins is the kind of thing that eventually gets attached to something. A one-command
# wipe means there is never a reason to keep one around.
#
# Nothing here is destructive by accident: --wipe and --reset both refuse unless --yes is
# given, and both print the row counts they are about to destroy first. Free to run.

import argparse
import os
import sqlite3
import sys

import db

TABLES = ("users", "credentials", "sessions", "conversations", "messages",
          "traces", "trace_calls", "login_attempts", "answer_cache")


def counts(conn):
    out = {}
    for t in TABLES:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        except sqlite3.OperationalError:
            out[t] = None          # table does not exist yet
    return out


def show(conn, path):
    c = counts(conn)
    v = db.schema_version(conn)
    print(f"\n  {path}  (schema v{v})")
    if v < db.SCHEMA_VERSION:
        # A file that is behind the code is the state where everything looks fine until one
        # query hits a table that does not exist yet. Say it out loud, every time it is true.
        print(f"  ** BEHIND: the code is at v{db.SCHEMA_VERSION}. "
              f"Run  python reset_db.py --init  to apply "
              f"{', '.join(f'v{n}' for n in sorted(db.MIGRATIONS) if n > v)}.")
    print(f"  {'table':16} {'rows':>8}")
    for t in TABLES:
        n = c[t]
        print(f"  {t:16} {'-' if n is None else n:>8}")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    print(f"\n  foreign_keys = {'ON' if fk else 'OFF  <-- cascades are not enforced'}")
    users = conn.execute("SELECT id, email, created_at, last_login_at FROM users "
                         "ORDER BY id").fetchall() if c["users"] else []
    if users:
        print(f"\n  {'id':>3}  {'email':38} {'created':21} last login")
        for u in users:
            print(f"  {u['id']:>3}  {u['email']:38} {u['created_at']:21} "
                  f"{u['last_login_at'] or '-'}")
    print()


def wipe(conn):
    """Delete every row, keep the schema. Ordered child-first so it works even if some
    future connection forgets the foreign_keys pragma - the delete must not depend on the
    same setting whose absence this project has already been bitten by."""
    for t in reversed(TABLES):
        conn.execute(f"DELETE FROM {t}")
    for t in TABLES:                      # reset AUTOINCREMENT counters
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (t,))
    conn.commit()


def seed(conn):
    """A demo user with one conversation and one fully populated trace.

    This is for building the UI in 6.6 without paying for a single API call, and for
    checking the trace panel against a row whose numbers are known by hand. The password
    hash is a placeholder string, NOT a real hash - 6.2 replaces it, and until then this
    account cannot be logged into, which is the safe direction to be wrong in.
    """
    uid = db.create_user(conn, "demo@example.com", "Demo Analyst")
    db.add_local_credential(conn, uid, "PLACEHOLDER-NOT-A-REAL-HASH")
    conv = db.create_conversation(conn, uid, "NVIDIA FY2026 revenue")
    db.add_message(conn, conv, "user", "What was NVIDIA's total revenue for fiscal year 2026?")
    mid = db.add_message(conn, conv, "assistant",
                         "NVIDIA's total revenue for fiscal year 2026 was $215,938 million.")
    db.save_trace(
        conn, message_id=mid, conversation_id=conv, user_id=uid,
        question_raw="What was NVIDIA's total revenue for fiscal year 2026?",
        jobs=[{"company": "NVIDIA", "period": "fiscal year 2026", "query": "total revenue"}],
        filings=["NVIDIA fiscal year 2026 10-K"],
        chunk_ids=["nvidia-fy2026-10k-t12-p0", "nvidia-fy2026-10k-t12-p1"],
        rounds=1, reflect_fired=False, guard_fired="", cache_hit=False,
        calls=[("agent-plan", 912, 118, "gemini-3.1-flash-lite", 0.0002025),
               ("agent-generation", 3736, 207, "gemini-3.1-flash-lite", 0.0006222)],
        seconds=7.9)
    return uid


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", default=db.DB_PATH, help="database file (default: app.db)")
    p.add_argument("--init", action="store_true", help="create the schema if absent")
    p.add_argument("--show", action="store_true", help="print row counts and users")
    p.add_argument("--wipe", action="store_true", help="delete every row, keep the schema")
    p.add_argument("--reset", action="store_true", help="delete the FILE and recreate it")
    p.add_argument("--seed", action="store_true", help="add one demo user, chat and trace")
    p.add_argument("--yes", action="store_true", help="required for --wipe and --reset")
    a = p.parse_args()

    if not any((a.init, a.show, a.wipe, a.reset, a.seed)):
        p.print_help()
        sys.exit(0)

    if a.reset:
        if not a.yes:
            sys.exit("\n  --reset DELETES the database file. Re-run with --yes if you mean it.\n")
        if os.path.exists(a.path):
            conn = db.connect(a.path)
            print("  deleting a database that currently holds:")
            show(conn, a.path)
            conn.close()
            os.remove(a.path)
            print(f"  removed {a.path}")
        db.init_db(db.connect(a.path)).close()
        print(f"  created {a.path} at schema v{db.SCHEMA_VERSION}")

    conn = db.init_db(db.connect(a.path)) if (a.init or a.seed) else db.connect(a.path)

    if a.wipe:
        if not a.yes:
            show(conn, a.path)
            sys.exit("  --wipe DELETES every row above. Re-run with --yes if you mean it.\n")
        wipe(conn)
        print(f"  wiped every row in {a.path}")

    if a.seed:
        uid = seed(conn)
        print(f"  seeded demo@example.com as user {uid} "
              f"(placeholder hash - cannot be logged into until 6.2)")

    if a.show or a.init or a.seed or a.wipe:
        show(conn, a.path)
    conn.close()
