# test_server.py
# Phase 6.6 - drive the app through a REAL uvicorn server over REAL HTTP.
#
# WHY THIS EXISTS, and it is not "more of test_app.py". test_app.py uses FastAPI's TestClient,
# which runs the whole request on one thread. Uvicorn does not: a sync endpoint and the sync
# dependency in front of it are dispatched to a worker THREAD POOL, and FastAPI does not
# promise they land on the same thread.
#
# That difference hid a real bug for a whole phase. `get_db` opened a sqlite3 connection while
# resolving the dependency in thread A; the endpoint then used it in thread B; sqlite3 raised
#
#     SQLite objects created in a thread can only be used in that same thread
#
# and /conversations returned 500. In the browser that looked like "my chat history is gone" -
# signed in, empty sidebar, no error - and it was intermittent, because whether it broke
# depended on which pool thread each request happened to get. Nineteen passing checks in
# test_app.py could not see it, because that harness has no thread pool to get wrong.
#
# THE LESSON THIS FILE IS: a test harness that is SIMPLER than production is a harness whose
# passes only cover what it happens to model. This one costs a few seconds and models the
# thing that broke.
#
# Free: the agent and the rewriter are stubbed, so no API key, no network, no cost.

import os
import tempfile
import threading
import time

os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(prefix="fa-srv-"), "s.db")
os.environ["COOKIE_INSECURE"] = "1"

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def main():
    import httpx
    import uvicorn
    import app as appmod
    import test_app as T

    appmod.agent.run_agent = T.fake_run_agent
    appmod.rewriter.rewrite = lambda q, h: ((q, "no-history") if not h
                                            else ("STANDALONE: " + q, None))

    server = uvicorn.Server(uvicorn.Config(appmod.app, host="127.0.0.1", port=PORT,
                                           log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(60):                       # wait for the port, do not sleep and hope
        try:
            httpx.get(BASE + "/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        raise SystemExit("the server never came up")

    ok = 0
    c = httpx.Client(base_url=BASE, timeout=20)
    r = c.post("/auth/signup", json={"email": "srv@example.com",
                                     "password": "a-long-enough-passphrase"})
    assert r.status_code == 200, r.text
    H = {"X-CSRF-Token": r.json()["csrf_token"]}

    # Ask enough times that several requests land on DIFFERENT pool threads. With the old
    # code this loop failed within the first two or three iterations.
    ids = []
    for i in range(6):
        r = c.post("/ask", json={"question": f"Question number {i} about NVIDIA?"}, headers=H)
        assert r.status_code == 200, f"/ask #{i} -> {r.status_code}: {r.text[:300]}"
        ids.append(r.json()["conversation_id"])
    ok += 1

    # ...and read them back, which is the call that actually broke
    for i in range(6):
        r = c.get("/conversations")
        assert r.status_code == 200, f"/conversations -> {r.status_code}: {r.text[:300]}"
        assert len(r.json()["conversations"]) == 6, r.json()
    ok += 1

    # a "new tab": a second client carrying only the session cookie, exactly what a browser
    # sends. This is the flow the learner reported as broken.
    tab = httpx.Client(base_url=BASE, timeout=20,
                       cookies={"fa_session": c.cookies.get("fa_session")})
    me = tab.get("/auth/me")
    assert me.status_code == 200, me.text
    convs = tab.get("/conversations")
    assert convs.status_code == 200 and len(convs.json()["conversations"]) == 6, convs.text
    ok += 1

    # and the thread each request lands on must not change the answer
    detail = tab.get("/conversations/" + str(ids[0]))
    assert detail.status_code == 200 and len(detail.json()["messages"]) == 2, detail.text
    ok += 1

    # CONCURRENTLY, because "one connection per request" is only true if requests really do
    # get their own. Ten at once through the pool.
    errors = []

    def hammer():
        try:
            rr = httpx.get(BASE + "/conversations", timeout=20,
                           cookies={"fa_session": c.cookies.get("fa_session")})
            if rr.status_code != 200:
                errors.append(f"{rr.status_code}: {rr.text[:120]}")
        except Exception as e:
            errors.append(repr(e))

    ts = [threading.Thread(target=hammer) for _ in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, f"concurrent reads failed: {errors[:3]}"
    ok += 1

    # the UI is served and is the real one
    page = c.get("/")
    assert page.status_code == 200 and "authform" in page.text and "convs" in page.text
    ok += 1

    server.should_exit = True
    print(f"test_server.py: {ok}/{ok} checks passed against a real uvicorn server, $0.00 spent")
    print("  This is the harness that would have caught the cross-thread sqlite bug;")
    print("  TestClient runs one thread and could not.")


if __name__ == "__main__":
    main()
