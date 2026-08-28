"""
probe_concurrency.py - Phase 7. Put the serving layer under simultaneous load and MEASURE what
it does, rather than reading the design and believing it.

WHY THIS IS OWED. The Dockerfile pins `--workers 1` and explains that SQLite in WAL mode gives
many readers and one writer, safe across threads inside a single process. app.py opens one
connection per request for the same reason. Both statements are arguments. Neither is a
measurement, and the tracker has carried the line "concurrency is CONFIGURED, not measured"
since Phase 6. This file is the measurement.

test_server.py already fires ten simultaneous GETs and is the reason the cross-thread sqlite
bug was caught. But it reads. Reading is the easy half: WAL exists to make concurrent readers
free. Nothing in this repo has ever pointed two WRITERS at the database at the same instant,
and nothing has ever asked whether a limit that is CHECKED and then ACTED ON survives two
requests arriving between the check and the act.

ATTACK FIRST, THEN DEFEND. Written before running it, so that being wrong costs something:

  A. concurrent writes           EXPECT PASS. busy_timeout is 5000ms and the writes are tiny.
  B. the /ask rate limit         EXPECT FAIL. `used = db.recent_asks(...)` runs, then the agent
                                 runs, THEN the row is written. Two requests that both read the
                                 count before either writes will both be allowed. The gap is
                                 not microseconds - it is the whole agent call, about eight
                                 seconds in production.
  C. the cache under a stampede  EXPECT FAIL. N identical questions arriving together all miss
                                 a cache none of them has filled yet, so all N are paid for.

Free. The agent and the rewriter are stubbed, no API key is needed, and no model is called.
The stub SLEEPS, on purpose - see AGENT_SECONDS below.

    python probe_concurrency.py
"""

import os
import statistics
import tempfile
import threading
import time

os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(prefix="fa-conc-"), "c.db")
os.environ["COOKIE_INSECURE"] = "1"
os.environ.setdefault("GOOGLE_API_KEY", "probe-dummy-key-no-network-calls-are-made")

PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"

# THE STUB SLEEPS, AND THE SLEEP IS THE POINT. A stub that returns instantly closes the very
# window this probe exists to open: the real agent blocks for roughly eight seconds between the
# rate-limit check and the row that records the charge. An instant stub would make the race
# almost impossible to observe and would produce a green result that means nothing - the
# harness would have quietly removed the defect before testing for it. 0.3s is short enough to
# keep this file free and fast, and long enough that the gap is real rather than theoretical.
AGENT_SECONDS = 0.3


def main():
    import httpx
    import uvicorn
    import app as appmod
    import db
    import cache
    import test_app as T

    real_stub = T.fake_run_agent

    def slow_stub(question, **kw):
        time.sleep(AGENT_SECONDS)
        return real_stub(question, **kw)

    appmod.agent.run_agent = slow_stub
    appmod.rewriter.rewrite = lambda q, h, **kw: ((q, "no-history") if not h
                                                  else ("STANDALONE: " + q, None))

    server = uvicorn.Server(uvicorn.Config(appmod.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(80):
        try:
            httpx.get(BASE + "/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        raise SystemExit("the server never came up")

    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post("/auth/signup", json={"email": "conc@example.com",
                                     "password": "a-long-enough-passphrase"})
    assert r.status_code == 200, r.text
    H = {"X-CSRF-Token": r.json()["csrf_token"]}

    # No cookie jar is copied anywhere in this file. `c` is signed in and every request below
    # goes through it - see fire() for why that replaced hand-assembling the credentials.

    conn = db.connect()
    uid = conn.execute("SELECT id FROM users WHERE email = ?",
                       ("conc@example.com",)).fetchone()["id"]

    def fire(questions, headers=H):
        """Send every question AT THE SAME INSTANT and return (status, body, seconds) each.

        ONE CLIENT, SHARED, and that is the second version of this function. The first built a
        fresh httpx.Client per thread and hand-copied the session cookie into it - which meant
        the probe was REBUILDING the browser's authentication state from parts, and it got the
        parts wrong: the CSRF defence is double-submit, so it needs the `fa_csrf` cookie as
        well as the header, and without it all twelve requests came back 403. Copying more
        cookies would have fixed that instance and left the design intact. Reusing the client
        that is already signed in removes the whole category: there is no auth state to
        reconstruct, so there is none to get wrong. httpx.Client is safe to use from several
        threads at once, which is the property this relies on.

        A barrier, not a loop of thread starts. Starting twelve threads in a for-loop staggers
        them by however long a thread takes to start, which on a busy machine is enough for the
        first request to finish - and a 'concurrent' test whose requests are actually
        sequential reports that every race is already fixed.
        """
        gate = threading.Barrier(len(questions))
        out = [None] * len(questions)

        def one(i, q):
            gate.wait()
            t0 = time.time()
            try:
                rr = c.post("/ask", json={"question": q}, headers=headers)
                try:
                    body = rr.json()
                except Exception:
                    body = {"_text": rr.text[:300]}
                out[i] = (rr.status_code, body, time.time() - t0)
            except Exception as e:
                out[i] = (-1, {"error": repr(e)}, time.time() - t0)

        ts = [threading.Thread(target=one, args=(i, q)) for i, q in enumerate(questions)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        return out

    # Proof that the credentials work AT ALL, before twelve of them arrive together. A
    # concurrency probe whose very first finding is "authentication is broken" has learned
    # nothing about concurrency, and that is exactly how the previous run was spent.
    warm = c.post("/ask", json={"question": "Warm-up: does one authenticated ask work?"},
                  headers=H)
    assert warm.status_code == 200, (
        f"a SINGLE authenticated /ask failed with {warm.status_code} before any concurrency "
        f"was involved: {warm.text[:300]}")
    conn0 = db.connect()
    conn0.execute("DELETE FROM conversations")      # the warm-up must not pollute the counts
    conn0.execute("DELETE FROM traces")
    conn0.commit()
    conn0.close()

    print("\n" + "=" * 90)
    print("  CONCURRENCY PROBE - the serving layer under simultaneous load")
    print(f"  stubbed agent, {AGENT_SECONDS}s per call, no model, no API key, Rs 0.00")
    print("=" * 90)

    # ---------------------------------------------------------------------------------------
    # A. CONCURRENT WRITES. Twelve different questions at once, from one account, each one a
    #    write of a conversation, two messages and a trace. WAL promises one writer at a time;
    #    busy_timeout=5000 promises the others wait rather than raise.
    # ---------------------------------------------------------------------------------------
    N = 12
    res = fire([f"Concurrent write number {i} about NVIDIA revenue?" for i in range(N)])
    codes = [s for s, _, _ in res]
    locked = [j.get("detail", "") for s, j, _ in res if "locked" in str(j).lower()]
    times = [t for _, _, t in res]

    rows = conn.execute("SELECT COUNT(*) n FROM messages WHERE role = 'assistant'").fetchone()["n"]
    convs = conn.execute("SELECT COUNT(*) n FROM conversations").fetchone()["n"]

    print(f"\n  A. {N} SIMULTANEOUS WRITES (distinct questions, one account)")
    print(f"     status codes        {sorted(set(codes))}")
    print(f"     'database is locked' {len(locked)}")
    print(f"     assistant rows      {rows}/{N}      conversations {convs}/{N}")
    print(f"     slowest / median    {max(times):.2f}s / {statistics.median(times):.2f}s")

    # THE STATUS CODES ARE CHECKED FIRST, AND THAT ORDER IS THE FIX FOR A REAL MISTAKE. The
    # first run of this probe sent requests without the CSRF cookie, every one was correctly
    # refused with 403, and the row count was therefore zero - at which point the next
    # assertion announced "writes were LOST". It accused the application of losing data at the
    # exact moment the application had refused to accept any. A harness fault must be named as
    # a harness fault; an assertion that can only describe the failure it expected will
    # mis-describe every other one. Lesson 112: a control that fails for a reason it invented
    # is worse than no control.
    assert set(codes) <= {200}, (
        f"the requests never reached the write path: status codes {sorted(set(codes))}. "
        f"This is a fault in THIS FILE, not in the application - 403 means the CSRF cookie or "
        f"header is missing, 401 means the session was not sent. First response: "
        f"{res[0][1]!r:.200}")
    assert not locked, f"SQLite locked under {N} concurrent writers: {locked[:2]}"
    assert rows == N, f"{rows} of {N} answers were persisted - writes were LOST"
    assert convs == N, f"{convs} of {N} conversations exist - writes were LOST"
    print("     PASS - every write landed, nothing was lost, nothing raised.")

    # ---------------------------------------------------------------------------------------
    # B. THE RATE LIMIT. The bound README states is 40 paid questions per hour per account.
    #    Lower it to a number this probe can reach, then arrive all at once.
    # ---------------------------------------------------------------------------------------
    cache.clear(conn)
    conn.commit()
    old_max, old_usd = appmod.MAX_PAID_ASKS_PER_WINDOW, appmod.MAX_USD_PER_WINDOW
    before = db.recent_asks(conn, uid, 60)["paid"]
    LIMIT = before + 4
    appmod.MAX_PAID_ASKS_PER_WINDOW = LIMIT
    appmod.MAX_USD_PER_WINDOW = 1e9          # isolate the count bound from the spend bound
    try:
        BURST = 14
        res = fire([f"Rate limit probe question {i} about AMD revenue?" for i in range(BURST)])
        allowed = sum(1 for s, _, _ in res if s == 200)
        refused = sum(1 for s, _, _ in res if s == 429)
        after = db.recent_asks(conn, uid, 60)["paid"]
        charged = after - before
        budget = LIMIT - before

        print(f"\n  B. RATE LIMIT UNDER A BURST  (limit {LIMIT}, {before} already used, "
              f"{budget} left, {BURST} arrive at once)")
        print(f"     answered 200        {allowed}")
        print(f"     refused  429        {refused}")
        print(f"     ACTUALLY CHARGED    {charged}   <- the number that matters")
        print(f"     the stated bound    {budget}")

        # THIS WAS A MEASUREMENT AND IS NOW A CHECK, and the order is the whole method. Run
        # against the code as it stood on 2026-08-28 it reported: 14 answered, ZERO refused,
        # 14 charged against a budget of 4 - the limit exceeded by 10, with not one request
        # turned away. The defence (app.py's ask_slot) was written only after that number
        # existed. An assertion added before the attack would have been a guess about which
        # number was wrong.
        assert charged <= budget, (
            f"THE RATE LIMIT DOES NOT HOLD UNDER LOAD: {charged} paid asks were charged "
            f"against a budget of {budget}. The guard reads the count, the agent runs, and "
            f"only then is the charge written - so every request inside that gap reads a "
            f"count that does not include the others. Check-then-act is not a limit.")
        assert refused == BURST - budget, (
            f"{refused} refused, expected {BURST - budget}. The bound was not exceeded, so "
            f"this is the opposite failure: requests are being turned away that the limit "
            f"allows. A limit that refuses too much is still a broken limit.")
        assert charged == budget, (
            f"only {charged} of an available {budget} were admitted - the reservation is "
            f"not being released, and the account will drift towards refusing everything.")
        print(f"     PASS - exactly {budget} admitted, exactly {refused} refused, and the")
        print(f"            reservation was released by every one of them.")
    finally:
        appmod.MAX_PAID_ASKS_PER_WINDOW, appmod.MAX_USD_PER_WINDOW = old_max, old_usd

    # ---------------------------------------------------------------------------------------
    # C. THE CACHE STAMPEDE. The cache's whole claim is that a repeated question is free. It is
    #    filled by the FIRST answer to complete - so N identical questions that arrive before
    #    any of them completes are N misses, and every one is paid for.
    # ---------------------------------------------------------------------------------------
    cache.clear(conn)
    conn.commit()
    before = db.recent_asks(conn, uid, 60)["paid"]
    SAME = 8
    q = "What was NVIDIA's total revenue for fiscal year 2026, stampede edition?"
    res = fire([q] * SAME)
    hits = sum(1 for _, j, _ in res if j.get("cache_hit"))
    charged = db.recent_asks(conn, uid, 60)["paid"] - before

    print(f"\n  C. CACHE STAMPEDE  ({SAME} IDENTICAL questions at the same instant, cold cache)")
    print(f"     cache hits          {hits}/{SAME}")
    print(f"     PAID calls          {charged}   (an ideal cache would pay once)")
    if charged > 1:
        print(f"     {charged - 1} answer(s) were paid for more than once. Nothing is wrong")
        print(f"     with the cache: it is filled by whichever request finishes first, and")
        print(f"     none of these had finished when the others looked.")

    # C IS REPORTED AND NOT FIXED, and that is a decision rather than an omission.
    #
    # The cache's claim, stated in Phase 6.5 and in the README, is that a REPEATED question is
    # free. That claim is about repetition over TIME and it is still true. A stampede is a
    # different claim - that simultaneous duplicates cost once - and nobody ever made it.
    # Building single-flight (the first request answers, the rest wait on its result) would
    # cost about twenty lines and buy a new failure mode: one stuck leader parks every
    # follower behind it, turning a cost problem into an availability problem.
    #
    # What decided it is the fix above. Now that admission counts in-flight requests, the
    # number of paid calls that can be in the air at once is bounded by the account's
    # remaining budget - so the stampede's blast radius is bounded even though the stampede
    # itself is not prevented. That is enough for a corpus of six filings and one user, and
    # it goes in Known limitations with this measurement attached rather than being quietly
    # left out. It is written down BECAUSE it was not fixed.
    assert charged <= SAME, "more paid calls than requests - the accounting is wrong"

    # ---------------------------------------------------------------------------------------
    print("\n" + "-" * 90)
    print("  A and B are checks and both passed. C is a measurement, reported and NOT fixed -")
    print("  see the note in this file for why, and Known limitations in the tracker for the")
    print("  number. B was a measurement first; it only became a check after the defence.")
    print("-" * 90 + "\n")

    conn.close()
    server.should_exit = True


if __name__ == "__main__":
    main()
