"""
cost_report.py - Phase 7, the last piece. Where the money actually went.

WHAT THIS ANSWERS THAT NOTHING ELSE DOES. The trace panel shows one answer's cost, and
/auth/me shows one account's running total. Both are correct and neither can answer the
question an operator has: *which part of the pipeline is expensive, and did that change when
we changed something?* Four paid calls happen behind one answer - plan, generation, an
occasional requarantine retry, an occasional reflect round - plus the rewriter in front of
them, and until now their costs have only ever been added together.

WHY IT IS A SCRIPT AND NOT A PAGE, which is a decision rather than laziness. A cost dashboard
is an OPERATOR's view: it spans every account, and the interesting groupings - by run version,
by call label - are not one user's business. This project has no admin role. Serving a global
view from an authenticated route would therefore mean either inventing a role system for one
page, or leaking every account's activity to every signed-in user. Reading the database file
directly needs neither: authorisation is filesystem access, which the operator already has and
nobody else does. If an admin role ever exists, this file's queries move behind it unchanged.

NOTHING HERE IS RECOMPUTED, which is the Phase 6.1 contract applied to a second reader. Every
figure is a SUM in SQL over rows that were written once. In particular the cache saving is
NOT estimated: `traces.saved_usd` is what the first run of that question actually cost, stored
at the time, because a saving the product invented for itself would be marketing.

    python cost_report.py                  # the default database (APP_DB, else app.db)
    python cost_report.py --db other.db
    python cost_report.py --days 7         # only the last 7 days
    python cost_report.py --selftest       # in-memory, known numbers, free
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

MODEL_PRICES_NOTE = ("prices are recorded per call at the time of the call; this report never "
                     "re-prices anything")


def _since(days):
    if not days:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _has_column(conn, table, column):
    """Does this database actually have that column?

    A REPORT READS DATABASES IT DID NOT CREATE, and that is the whole difference between this
    file and every other one here. app.py calls db.init_db() and therefore always migrates
    before it reads; this tool opens whatever file it is pointed at, which may be older than
    the code - a copy taken last month, a colleague's, a backup being investigated precisely
    BECAUSE something is wrong with it.

    It must not migrate. A reporting tool that writes to the file it is inspecting can turn a
    forensic copy into a modified one, and the person running it would have no idea. So the
    schema is probed and the affected section degrades with a sentence, rather than the whole
    report dying on `no such column`.
    """
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def recorded_version(conn):
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        return row["v"] if row and row["v"] is not None else 0
    except sqlite3.OperationalError:
        return 0


def _money(x):
    return f"${x:,.4f}"


def _bar(share, width=28):
    """A share of the total, drawn. Rounds UP off zero so a real cost never renders as blank."""
    n = int(round(share * width))
    if share > 0 and n == 0:
        n = 1
    return "#" * n + "." * (width - n)


# --- the queries ---------------------------------------------------------------------------
# Each one is a plain aggregate over stored rows. The WHERE clause on `created_at` is a string
# comparison, which is correct here for the reason db.utcnow() exists: ISO-8601 sorts
# lexicographically, so a text range is a time range.

def headline(conn, since):
    where = "WHERE created_at >= ?" if since else ""
    p = (since,) if since else ()
    row = conn.execute(f"""
        SELECT COUNT(*)                                      AS answers,
               COALESCE(SUM(cache_hit), 0)                   AS cache_hits,
               COALESCE(SUM(usd), 0.0)                       AS usd,
               COALESCE(SUM(saved_usd), 0.0)                 AS avoided_usd,
               COALESCE(SUM(input_tokens), 0)                AS input_tokens,
               COALESCE(SUM(output_tokens), 0)               AS output_tokens,
               COUNT(DISTINCT user_id)                       AS accounts
        FROM traces {where}""", p).fetchone()
    d = dict(row)
    d["paid"] = d["answers"] - d["cache_hits"]
    return d


def by_label(conn, since):
    """The money question. One row per paid call label, across every answer."""
    where = "WHERE t.created_at >= ?" if since else ""
    p = (since,) if since else ()
    return _rows(conn, f"""
        SELECT c.label                    AS label,
               COUNT(*)                   AS calls,
               SUM(c.input_tokens)        AS input_tokens,
               SUM(c.output_tokens)       AS output_tokens,
               SUM(c.usd)                 AS usd
        FROM trace_calls c JOIN traces t ON t.id = c.trace_id
        {where}
        GROUP BY c.label ORDER BY usd DESC""", p)


def by_run_version(conn, since):
    """What the versioning work bought: cost attributed to the configuration that incurred it.

    NULL is kept as its own bucket rather than folded into the newest version. Rows written
    before schema v6 genuinely do not record which system answered, and printing them under
    today's version would be the backfill this project refused to do, performed in the report
    instead of in the database.
    """
    where = "WHERE created_at >= ?" if since else ""
    p = (since,) if since else ()
    return _rows(conn, f"""
        SELECT run_version                AS run_version,
               COUNT(*)                   AS answers,
               COALESCE(SUM(usd), 0.0)    AS usd,
               MIN(created_at)            AS first_seen,
               MAX(created_at)            AS last_seen
        FROM traces {where}
        GROUP BY run_version ORDER BY last_seen DESC""", p)


def by_day(conn, since):
    where = "WHERE created_at >= ?" if since else ""
    p = (since,) if since else ()
    return _rows(conn, f"""
        SELECT substr(created_at, 1, 10)  AS day,
               COUNT(*)                   AS answers,
               COALESCE(SUM(cache_hit),0) AS cache_hits,
               COALESCE(SUM(usd), 0.0)    AS usd
        FROM traces {where}
        GROUP BY day ORDER BY day""", p)


def integrity(conn, since):
    """Do the denormalised header totals still equal the per-call rows they were summed from?

    db.save_trace computes the header from the call list in one place, so these CANNOT
    disagree - by construction, today. That is exactly the kind of sentence that stops being
    true after somebody adds a second writer, and the failure would be silent: every number in
    this report would still add up to itself. Checking costs one query.
    """
    where = "WHERE t.created_at >= ?" if since else ""
    p = (since,) if since else ()
    row = conn.execute(f"""
        SELECT COALESCE(SUM(t.usd), 0.0)  AS header_usd,
               (SELECT COALESCE(SUM(c.usd), 0.0)
                  FROM trace_calls c JOIN traces t2 ON t2.id = c.trace_id
                  {where.replace('t.', 't2.')}) AS call_usd
        FROM traces t {where}""", p + p).fetchone()
    h, c = row["header_usd"], row["call_usd"]
    return h, c, abs(h - c) < 1e-9


def report(conn, days=None):
    since = _since(days)
    out = []
    w = out.append
    scope = f"the last {days} days" if days else "all time"

    h = headline(conn, since)
    w("")
    w("=" * 86)
    w(f"  COST REPORT  -  {scope}")
    w("=" * 86)
    if not h["answers"]:
        w("  No answered questions in this window. Nothing to report, which is not the same")
        w("  as zero cost - check --days, and check you are reading the right database.")
        return "\n".join(out) + "\n"

    hit_rate = h["cache_hits"] / h["answers"]
    w(f"  answers            {h['answers']:>6}   ({h['paid']} paid, {h['cache_hits']} served "
      f"from cache = {hit_rate:.0%})")
    w(f"  accounts           {h['accounts']:>6}")
    w(f"  spent              {_money(h['usd']):>10}")
    # AVOIDED, not "saved". What a cache hit did NOT re-spend, read off the stored cost of the
    # first run of that question - never estimated, never a multiple of anything.
    w(f"  avoided by cache   {_money(h['avoided_usd']):>10}   (what the first run of each "
      f"repeated question actually cost)")
    w(f"  tokens             {h['input_tokens']:,} in / {h['output_tokens']:,} out")

    hdr, call, agrees = integrity(conn, since)
    w("")
    if agrees:
        w(f"  INTEGRITY  header totals == sum of per-call rows  ({_money(hdr)})")
    else:
        w(f"  🔴 INTEGRITY FAILED: headers total {_money(hdr)}, the call rows total "
          f"{_money(call)}.")
        w("     Every figure below is drawn from one side or the other of that disagreement.")

    rows = by_label(conn, since)
    total = sum(r["usd"] for r in rows) or 1.0
    w("")
    w("-" * 86)
    w("  WHERE THE MONEY GOES  -  by paid call, across every answer")
    w("-" * 86)
    w(f"  {'label':<34} {'calls':>6} {'usd':>11}  {'share':>6}")
    for r in rows:
        share = r["usd"] / total
        w(f"  {r['label']:<34} {r['calls']:>6} {_money(r['usd']):>11}  {share:>5.1%}  "
          f"{_bar(share)}")
    w(f"  {'':<34} {'':>6} {_money(sum(r['usd'] for r in rows)):>11}")

    w("")
    w("-" * 86)
    w("  BY RUN VERSION  -  which configuration incurred it")
    w("-" * 86)
    rows = by_run_version(conn, since) if _has_column(conn, "traces", "run_version") else None
    if rows is None:
        w(f"  UNAVAILABLE. This database is at schema v{recorded_version(conn)} and "
          f"`traces.run_version`")
        w("  arrives in v6, so these rows genuinely do not record which configuration answered.")
        w("  Nothing is wrong with the file - it is simply older than this report.")
        w("")
        w("  This tool will NOT migrate it: a report that writes to the database it is")
        w("  inspecting is the last thing you want pointed at a copy you are investigating.")
        w("  To migrate for real, start the app once, or:")
        w('      python -c "import db; db.init_db(db.connect())"')
        rows = []
    for r in rows:
        v = r["run_version"] or "not recorded"
        note = "" if r["run_version"] else "   <- written before schema v6; NOT backfilled"
        w(f"  {v:<16} {r['answers']:>5} answers  {_money(r['usd']):>11}   "
          f"{r['first_seen'][:16]} .. {r['last_seen'][:16]}{note}")
    if len(rows) > 1:
        w("")
        w("  More than one version appears above, which is the point of recording it: the")
        w("  cost of a configuration change is the difference between these rows, and before")
        w("  Phase 7 there was no way to draw that line through the data at all.")

    rows = by_day(conn, since)
    w("")
    w("-" * 86)
    w("  BY DAY")
    w("-" * 86)
    peak = max((r["usd"] for r in rows), default=0.0) or 1.0
    for r in rows:
        w(f"  {r['day']}  {r['answers']:>4} answers  {r['cache_hits']:>3} cached  "
          f"{_money(r['usd']):>10}  {_bar(r['usd'] / peak, 24)}")

    w("")
    w(f"  {MODEL_PRICES_NOTE}.")
    w("=" * 86)
    w("")
    return "\n".join(out)


# --- self-test ---------------------------------------------------------------------------
# An in-memory database with numbers chosen by hand, so that every total in the report has a
# known right answer. Free: no API key, no network, no model.

def selftest():
    import db
    ok = 0
    conn = db.init_db(db.connect(":memory:"))

    u1 = db.create_user(conn, "a@example.com")
    u2 = db.create_user(conn, "b@example.com")
    cv1 = db.create_conversation(conn, u1, "one")
    cv2 = db.create_conversation(conn, u2, "two")

    # Two paid answers on version "v1", one on "v2", and one cache hit that avoided $0.0080.
    def paid(cv, u, version, calls):
        m = db.add_message(conn, cv, "assistant", "an answer")
        db.save_trace(conn, message_id=m, conversation_id=cv, user_id=u,
                      question_raw="q", calls=calls, run_version=version)

    A = [("agent-plan", 900, 100, "m", 0.0010), ("agent-generation", 3000, 200, "m", 0.0040)]
    B = [("agent-plan", 900, 100, "m", 0.0010), ("agent-generation", 3000, 200, "m", 0.0040),
         ("agent-reflect", 500, 50, "m", 0.0005)]
    paid(cv1, u1, "v1", A)
    paid(cv1, u1, "v1", B)
    paid(cv2, u2, "v2", A)

    m = db.add_message(conn, cv2, "assistant", "a cached answer")
    db.save_trace(conn, message_id=m, conversation_id=cv2, user_id=u2, question_raw="q",
                  calls=(), cache_hit=True, saved_usd=0.0080, run_version="v2")

    h = headline(conn, None)
    assert h["answers"] == 4 and h["paid"] == 3 and h["cache_hits"] == 1, h
    assert h["accounts"] == 2, h
    assert abs(h["usd"] - (0.0050 + 0.0055 + 0.0050)) < 1e-12, h
    # A cache hit costs nothing and AVOIDS what the first run cost. Both halves are asserted,
    # because a report that added the avoided amount into the spend would look plausible and
    # be wrong in the direction that flatters the cache.
    assert abs(h["avoided_usd"] - 0.0080) < 1e-12, h
    ok += 1

    labels = {r["label"]: r for r in by_label(conn, None)}
    assert set(labels) == {"agent-plan", "agent-generation", "agent-reflect"}, list(labels)
    assert labels["agent-generation"]["calls"] == 3
    assert abs(labels["agent-generation"]["usd"] - 0.0120) < 1e-12, labels["agent-generation"]
    assert labels["agent-reflect"]["calls"] == 1
    # The label totals must reconstruct the headline exactly. If they did not, the "share"
    # column would be a percentage of a number that appears nowhere else.
    assert abs(sum(r["usd"] for r in labels.values()) - h["usd"]) < 1e-12
    ok += 1

    vers = {r["run_version"]: r for r in by_run_version(conn, None)}
    assert set(vers) == {"v1", "v2"}, list(vers)
    assert vers["v1"]["answers"] == 2 and vers["v2"]["answers"] == 2, vers
    assert abs(vers["v1"]["usd"] - 0.0105) < 1e-12, vers["v1"]
    ok += 1

    # THE NULL BUCKET MUST SURVIVE. A pre-v6 row has no version, and folding it into the
    # newest one would be the backfill the schema deliberately refused, done in the report.
    m = db.add_message(conn, cv1, "assistant", "from before v6")
    db.save_trace(conn, message_id=m, conversation_id=cv1, user_id=u1, question_raw="old",
                  calls=A)
    vers = {r["run_version"]: r for r in by_run_version(conn, None)}
    assert None in vers and vers[None]["answers"] == 1, list(vers)
    ok += 1

    hdr, call, agrees = integrity(conn, None)
    assert agrees, (hdr, call)
    ok += 1

    # AND THE INTEGRITY CHECK MUST BE ABLE TO FAIL. A check that has only ever been seen
    # passing is a check nobody has tested - this project has written that lesson twice. The
    # header is corrupted by hand, behind db.save_trace's back, which is exactly the shape of
    # the future defect it is there to catch.
    conn.execute("UPDATE traces SET usd = usd + 1.0 WHERE id = (SELECT MIN(id) FROM traces)")
    hdr, call, agrees = integrity(conn, None)
    assert not agrees and abs(hdr - call - 1.0) < 1e-9, (hdr, call)
    conn.execute("UPDATE traces SET usd = usd - 1.0 WHERE id = (SELECT MIN(id) FROM traces)")
    assert integrity(conn, None)[2]
    ok += 1

    # The RENDERED text, not just the queries. Every assertion above tests a dict; a report
    # nobody reads is a set of correct numbers that never reach a person.
    text = report(conn, None)
    assert "COST REPORT" in text and "WHERE THE MONEY GOES" in text
    assert "not recorded" in text, "the NULL version bucket vanished from the rendered report"
    ok += 1

    empty = db.init_db(db.connect(":memory:"))
    assert "Nothing to report" in report(empty, None)
    ok += 1

    # ==========================================================================================
    # AN OLDER DATABASE, and this control exists because its absence cost a run.
    # ==========================================================================================
    # Every check above builds its database with db.init_db(), which migrates to the newest
    # schema first - so they could only ever run against the one shape where the question
    # "what if this file is older than the code?" cannot arise. Pointed at a real app.db that
    # had not been through v6 yet, the report died on `no such column: run_version`.
    #
    # This is the same shape as lesson 168 and it arrived four days later: a tool whose ENTIRE
    # JOB is reading files it did not create, tested only against files it created itself. The
    # harness's convenience chose the environment, and the environment it chose was the one
    # that cannot fail.
    old_db = db.connect(":memory:")
    old_db.executescript(db.SCHEMA)
    for v in sorted(db.MIGRATIONS):
        if v <= 5:                       # stop one short, on purpose: this is a v5 file
            old_db.executescript(db.MIGRATIONS[v])
            old_db.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) "
                           "VALUES (?,?)", (v, db.utcnow()))
    old_db.execute("INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (1,?)",
                   (db.utcnow(),))
    old_db.commit()
    assert not _has_column(old_db, "traces", "run_version"), "the v5 fixture is not v5"
    assert recorded_version(old_db) == 5, recorded_version(old_db)

    ou = db.create_user(old_db, "old@example.com")
    ocv = db.create_conversation(old_db, ou, "old")
    om = db.add_message(old_db, ocv, "assistant", "answered before v6")
    # RAW INSERTS, because db.save_trace cannot write here - it names run_version, and this
    # fixture deliberately predates that column. That is not a defect in save_trace: app.py
    # migrates on startup, so the writer never meets a v5 file. It IS the proof that the
    # fixture is genuinely old rather than merely missing a value, and it is how a real
    # archived database would have been written - by an older version of this code.
    cur = old_db.execute(
        "INSERT INTO traces (message_id, conversation_id, user_id, question_raw, cache_hit, "
        " input_tokens, output_tokens, usd, created_at) VALUES (?,?,?,?,0,?,?,?,?)",
        (om, ocv, ou, "q", sum(c[1] for c in A), sum(c[2] for c in A),
         sum(c[4] for c in A), db.utcnow()))
    for i, (lab, intok, outok, model, usd) in enumerate(A, start=1):
        old_db.execute(
            "INSERT INTO trace_calls (trace_id, seq, label, model, input_tokens, "
            " output_tokens, usd) VALUES (?,?,?,?,?,?,?)",
            (cur.lastrowid, i, lab, model, intok, outok, usd))
    old_db.commit()

    text = report(old_db, None)
    assert "UNAVAILABLE" in text and "schema v5" in text, text
    # The REST of the report must still be there. Degrading one section is the point;
    # degrading the whole document would just be the crash with better manners.
    assert "WHERE THE MONEY GOES" in text and "agent-generation" in text and "BY DAY" in text
    assert _money(0.0050) in text, text
    ok += 1

    # AND IT MUST NOT HAVE MIGRATED THE FILE IT WAS READING.
    assert not _has_column(old_db, "traces", "run_version"), \
        "the report MIGRATED the database it was asked to read"
    assert recorded_version(old_db) == 5, "the report wrote to a database it should only read"
    old_db.close()
    ok += 1

    conn.close()
    empty.close()
    print(f"cost_report.py self-test: {ok}/{ok} checks passed, $0.00 spent")
    print("  Known numbers in, known totals out - including the cache row, which must add to")
    print("  the avoided column and to nothing else, and the integrity check in both directions.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=os.environ.get("APP_DB", "app.db"))
    p.add_argument("--days", type=int, default=None, help="only the last N days")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    if not os.path.exists(args.db):
        raise SystemExit(f"no database at {args.db!r}. Set APP_DB or pass --db.")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        print(report(conn, args.days))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
