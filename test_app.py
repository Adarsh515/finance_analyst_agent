# test_app.py
# Phase 6.3 - exercise every route with NO API calls and NO real database file.
#
# The agent is replaced by a stub that returns a fixed answer and logs two fake paid calls
# through the same log_cost path the real one uses. That is the point: the stub is swapped in
# at the ONE seam the contract runs through, so everything downstream of it - the capture, the
# trace rows, the totals, the response shape - is the real code under test.
#
# WHAT THIS CANNOT TEST, said plainly: whether the real agent still returns the keys this file
# reads out of it. A stub agrees with whatever I imagined. That gap is closed by one paid smoke
# request against the live agent, and by nothing else.
#
# Free: no key, no network, no cost.  Run:  python test_app.py

import os
import sys
import tempfile

# Point the app at a throwaway database BEFORE importing it, and allow http cookies so the
# TestClient (which speaks http://testserver) actually receives them. Getting this wrong makes
# every authenticated request 401 and looks exactly like broken auth.
_tmp = tempfile.mkdtemp(prefix="fa-test-")
os.environ["APP_DB"] = os.path.join(_tmp, "test.db")
os.environ["COOKIE_INSECURE"] = "1"

import judges                      # noqa: E402
import telemetry                   # noqa: E402


class FakeResponse:
    def __init__(self, intok, outok):
        self.usage_metadata = {"input_tokens": intok, "output_tokens": outok}


class FakeDoc:
    def __init__(self, cid, company, period):
        self.id = cid
        self.page_content = f"{company} table for {period}"
        self.metadata = {"company": company, "period": period, "type": "table"}


ANSWER = "NVIDIA's total revenue for fiscal year 2026 was $215,938 million."


# What the stub was last called with. The 6.6 live test found that /ask never passed history
# at all - the 6.4 rewriter was built, tested in isolation and never wired - and no test here
# could see it, because the stub ignored the argument exactly as confidently as the app did.
LAST_CALL = {}


def fake_run_agent(question, **kw):
    """Stands in for agent.run_agent. Logs paid calls exactly the way the real graph does,
    so the capture, the pricing and the trace rows are all genuinely exercised."""
    import agent as _agent
    LAST_CALL.clear()
    LAST_CALL.update({"question": question, **kw})
    _ = kw
    _agent.log_cost("gemini-3.1-flash-lite", FakeResponse(912, 118), label="agent-plan")
    _agent.log_cost("gemini-3.1-flash-lite", FakeResponse(3736, 207), label="agent-generation")
    return {"question": question, "answer": ANSWER,
            "context": "<context>NVIDIA fiscal year 2026 revenue 215,938</context>",
            "rounds": 1, "guard_fired": "",
            "jobs": [],          # drained by retrieve_node, exactly like the real graph
            "jobs_log": [{"company": "NVIDIA", "period": "fiscal year 2026",
                          "query": "total revenue"}],
            "chunks": [FakeDoc("nvda-fy2026-t12-p0", "NVIDIA", "fiscal year 2026"),
                       FakeDoc("nvda-fy2026-t12-p1", "NVIDIA", "fiscal year 2026")],
            "seen_ids": ["nvda-fy2026-t12-p0", "nvda-fy2026-t12-p1"]}


def main():
    from fastapi.testclient import TestClient
    import app as appmod
    import db

    appmod.agent.run_agent = fake_run_agent
    # The rewriter is stubbed too, and for the same reason the agent is: this suite must cost
    # nothing. Before /ask passed history it never called the rewriter, so this was not needed
    # - which is itself a small sign that the wiring was missing.
    appmod.rewriter.rewrite = lambda q, h: ((q, "no-history") if not h
                                            else ("STANDALONE: " + q, None))
    client = TestClient(appmod.app)
    ok = 0
    skipped = []

    # --- health reports the CONFIGURATION, not just liveness --------------------------------
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["guards"] is True and h["guard_prompt"] is False, h
    assert h["schema_version"] == db.SCHEMA_VERSION
    assert "langsmith_tracing" in h and "cookie_secure" in h
    ok += 1

    # /filings reads the real Chroma index, which is a gitignored build artefact. On a
    # machine that has not run build_index.py it is legitimately empty - so the shape is
    # asserted when there is anything to assert, and the SKIP is printed loudly rather than
    # counted as a pass. A test that silently checks nothing is the failure this repo hunts.
    f = client.get("/filings").json()["filings"]
    if f:
        assert "company" in f[0] and "period" in f[0], f[0]
        assert len(f) == len(appmod.agent.FILINGS)
        ok += 1
    else:
        skipped.append("/filings shape - the index is empty here (run build_index.py)")

    # --- everything private is private -------------------------------------------------------
    for method, path in [("get", "/auth/me"), ("get", "/conversations"),
                         ("post", "/ask"), ("get", "/conversations/1"),
                         ("get", "/messages/1/trace")]:
        kw = {"json": {"question": "hi"}} if method == "post" else {}
        r = getattr(client, method)(path, **kw)
        # 401 and not 403: the auth dependency must run BEFORE the CSRF guard, so an
        # anonymous caller is told "sign in", not handed a hint about the token scheme.
        assert r.status_code == 401, f"FAIL: {method.upper()} {path} answered {r.status_code}"
    ok += 1

    # --- signup, and the password policy is enforced at the edge -----------------------------
    r = client.post("/auth/signup", json={"email": "a@example.com", "password": "short"})
    assert r.status_code == 400 and r.json()["error"] == "weak_password", r.json()
    r = client.post("/auth/signup", json={"email": "not-an-email", "password": "long-enough-pw"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_email", r.json()
    ok += 1

    r = client.post("/auth/signup", json={"email": "adarsh@example.com",
                                          "password": "a-long-enough-passphrase",
                                          "display_name": "Adarsh"})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    assert client.cookies.get(appmod.SESSION_COOKIE), "no session cookie was set"
    # the session cookie must be HttpOnly; the csrf cookie must NOT be, because the front end
    # has to read it. Checked on the raw header, since the cookie jar drops the attributes.
    set_cookies = r.headers.get_list("set-cookie")
    sess_hdr = next(c for c in set_cookies if c.startswith(appmod.SESSION_COOKIE))
    csrf_hdr = next(c for c in set_cookies if c.startswith(appmod.CSRF_COOKIE))
    assert "httponly" in sess_hdr.lower(), "session cookie is readable by page JavaScript"
    assert "httponly" not in csrf_hdr.lower(), "csrf cookie is unreadable by the front end"
    assert "samesite=lax" in sess_hdr.lower()
    ok += 1

    r = client.post("/auth/signup", json={"email": "adarsh@example.com",
                                          "password": "another-long-passphrase"})
    assert r.status_code == 409 and r.json()["error"] == "email_taken"
    ok += 1

    # --- CSRF: a state-changing request without the header must be refused -------------------
    r = client.post("/ask", json={"question": "What was NVIDIA's revenue?"})
    assert r.status_code == 403, f"FAIL: /ask accepted a request with no CSRF header ({r.status_code})"
    r = client.post("/ask", json={"question": "x"}, headers={"X-CSRF-Token": "wrong-value"})
    assert r.status_code == 403, "FAIL: /ask accepted a mismatched CSRF token"
    ok += 1

    H = {"X-CSRF-Token": csrf}

    # --- ask, and check the stored trace against numbers computed by hand --------------------
    r = client.post("/ask", json={"question": "What was NVIDIA's total revenue for FY2026?"},
                    headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == ANSWER
    assert body["guard_fired"] == "" and body["rounds"] == 1
    assert "context" in body, "the eval scores `context`; the API must return it too"

    t = body["trace"]
    p_in, p_out = judges.PRICES["gemini-3.1-flash-lite"]
    expect_usd = ((912 * p_in + 118 * p_out) + (3736 * p_in + 207 * p_out)) / 1_000_000
    assert t["input_tokens"] == 912 + 3736, t["input_tokens"]
    assert t["output_tokens"] == 118 + 207
    assert abs(t["usd"] - expect_usd) < 1e-12, (t["usd"], expect_usd)
    assert [c["label"] for c in t["calls"]] == ["agent-plan", "agent-generation"]
    assert abs(sum(c["usd"] for c in t["calls"]) - t["usd"]) < 1e-12, \
        "the trace header and its line items disagree"
    assert t["filings"] == ["NVIDIA | fiscal year 2026"]
    assert t["chunk_ids"] == ["nvda-fy2026-t12-p0", "nvda-fy2026-t12-p1"]
    # the stub returns jobs=[] like the real graph does; the panel must read jobs_log
    assert t["jobs"] == [{"company": "NVIDIA", "period": "fiscal year 2026",
                          "query": "total revenue"}], \
        "the trace recorded the drained work queue instead of the planned jobs"
    ok += 1

    conv_id, msg_id = body["conversation_id"], body["message_id"]

    # a follow-up lands in the SAME conversation, and the title came from the first question
    r2 = client.post("/ask", json={"question": "And AMD?", "conversation_id": conv_id},
                     headers=H).json()
    assert r2["conversation_id"] == conv_id
    convs = client.get("/conversations").json()["conversations"]
    assert len(convs) == 1 and convs[0]["title"].startswith("What was NVIDIA")
    msgs = client.get(f"/conversations/{conv_id}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    ok += 1

    # the trace endpoint returns what was stored, with no recomputation
    got = client.get(f"/messages/{msg_id}/trace").json()
    assert got["usd"] == t["usd"] and got["calls"] == t["calls"]
    ok += 1

    spend = client.get("/auth/me").json()["spend"]
    assert spend["questions"] == 2 and spend["input_tokens"] == 2 * (912 + 3736)
    ok += 1

    # --- a second user must not be able to reach the first one's data (IDOR) ------------------
    other = TestClient(appmod.app)
    # NB: the password may not contain the email's local part, so not "mallorys-...".
    # The policy caught this while writing the test, which is the cheapest place to find out.
    r = other.post("/auth/signup", json={"email": "mallory@example.com",
                                         "password": "a-different-long-passphrase"})
    assert r.status_code == 200, r.text
    other_csrf = r.json()["csrf_token"]
    assert other.get(f"/conversations/{conv_id}").status_code == 404, \
        "FAIL: another user read someone else's conversation"
    assert other.get(f"/messages/{msg_id}/trace").status_code == 404, \
        "FAIL: another user read someone else's trace - that is the cost and the sources"
    assert other.delete(f"/conversations/{conv_id}",
                        headers={"X-CSRF-Token": other_csrf}).status_code == 404
    # and the first user's data is untouched by the attempt
    assert len(client.get(f"/conversations/{conv_id}").json()["messages"]) == 4
    ok += 1

    # --- login, logout, and a revoked cookie is dead ---------------------------------------------
    assert client.post("/auth/logout", headers=H).json()["ok"] is True
    assert client.get("/auth/me").status_code == 401, "FAIL: session survived logout"
    r = client.post("/auth/login", json={"email": "adarsh@example.com",
                                         "password": "a-long-enough-passphrase"})
    assert r.status_code == 200 and client.get("/auth/me").json()["user"]["id"] == 1
    ok += 1

    r = client.post("/auth/login", json={"email": "adarsh@example.com", "password": "wrong-pw-here"})
    assert r.status_code == 401 and r.json()["error"] == "invalid_credentials"
    r = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-pw-here"})
    assert r.status_code == 401 and r.json()["error"] == "invalid_credentials", \
        "FAIL: the API distinguishes a wrong password from a missing account"
    ok += 1

    # --- the rate limiter reaches the HTTP layer as a 429 ------------------------------------------
    for _ in range(auth.MAX_FAILURES_PER_EMAIL):
        client.post("/auth/login", json={"email": "target@example.com", "password": "guessing-away"})
    r = client.post("/auth/login", json={"email": "target@example.com", "password": "guessing-away"})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited", r.json()
    ok += 1

    # --- the cache (Phase 6.5) ----------------------------------------------------------------
    import cache
    # The CSRF token was rotated by the logout/login above, so the old header is stale. That
    # is the double-submit scheme working exactly as designed - a token that outlived its
    # session would be a defect - but it means this block needs the current one.
    H = {"X-CSRF-Token": client.post("/auth/login",
                                     json={"email": "adarsh@example.com",
                                           "password": "a-long-enough-passphrase"}
                                     ).json()["csrf_token"]}
    Q = "What was NVIDIA's total revenue for fiscal year 2026?"
    # get_db() is a request-scoped generator dependency - taking one value from it and walking
    # away leaves the connection to be closed by the generator's cleanup. Open a plain one.
    _c = db.connect()
    cache.clear(_c)
    _c.close()

    _r = client.post("/ask", json={"question": Q}, headers=H)
    assert _r.status_code == 200, f"/ask failed {_r.status_code}: {_r.text[:400]}"
    first = _r.json()
    assert first["cache_hit"] is False and first["cached"] is True, first.get("not_cached_because")

    # a paraphrase that only differs in the ways normalise() folds must HIT
    second = client.post("/ask", json={"question": "what was nvidia's total revenue for FY2026"},
                         headers=H).json()
    assert second["cache_hit"] is True, "the normalised paraphrase missed"
    assert second["answer"] == first["answer"]
    # and it must cost the asking user nothing, while still being THEIR trace
    assert second["trace"]["usd"] == 0 and second["trace"]["input_tokens"] == 0
    assert second["trace"]["calls"] == [] and second["trace"]["cache_hit"] == 1
    ok += 1

    # the near-misses from probe_cache_keys.py must all MISS. Every one of these scored above
    # a usable embedding threshold; exact matching is the only reason they are safe.
    for near in ["What was NVIDIA's total revenue for fiscal year 2025?",
                 "What was AMD's total revenue for fiscal year 2026?",
                 "What was NVIDIA's net income for fiscal year 2026?"]:
        r = client.post("/ask", json={"question": near}, headers=H).json()
        assert r["cache_hit"] is False, f"CACHE COLLISION on a near-miss: {near}"
    ok += 1

    # a second USER gets the hit too - the corpus is public, so the cache is global - but the
    # trace and the spend stay with whoever asked
    o2 = TestClient(appmod.app)
    _s = o2.post("/auth/signup", json={"email": "reader@example.com",
                                       "password": "a-second-long-passphrase"})
    assert _s.status_code == 200, f"signup failed: {_s.text[:200]}"
    o2h = {"X-CSRF-Token": o2.post("/auth/login",
                                   json={"email": "reader@example.com",
                                         "password": "a-second-long-passphrase"}
                                   ).json()["csrf_token"]}
    r = o2.post("/ask", json={"question": Q}, headers=o2h).json()
    assert r["cache_hit"] is True and r["answer"] == first["answer"]
    assert o2.get("/auth/me").json()["spend"]["usd"] == 0, "a cache hit billed the reader"
    assert client.get("/auth/me").json()["spend"]["usd"] > 0, "the producer's spend vanished"
    ok += 1

    # an answer produced UNDER ATTACK must never be stored - one successful injection must
    # not be upgraded by us into a permanent one served to everybody
    def attacked_agent(question, **_):
        out = fake_run_agent(question, **_)
        out["answer"] = "NVIDIA's total revenue was $999,999 million."
        out["guard_fired"] = "quarantine:['999999'] -> regenerated from trusted chunks only"
        return out
    appmod.agent.run_agent = attacked_agent
    r = client.post("/ask", json={"question": "a question answered under attack"},
                    headers=H).json()
    assert r["cached"] is False and "under attack" in r["not_cached_because"], r
    appmod.agent.run_agent = fake_run_agent
    ok += 1

    # the badge above an answer is built from fields list_messages joins in, so a reloaded
    # conversation shows the same badges a fresh answer did. If those columns stop arriving,
    # the badge silently disappears on reload only - the hardest kind of bug to notice.
    conv_id = client.get("/conversations").json()["conversations"][0]["id"]
    replayed = client.get("/conversations/" + str(conv_id)).json()["messages"]
    bot = [m for m in replayed if m["role"] == "assistant"]
    assert bot, "no assistant message to check"
    for field in ("cache_hit", "usd", "saved_usd", "guard_fired", "question_rewritten"):
        assert field in bot[0], f"list_messages dropped {field} - badges vanish on reload"
    ok += 1

    # --- Phase 6.7: a company that is not in the filings ---------------------------------------
    # The learner's requirement, in his words: it should go through the pipeline exactly like
    # NVIDIA does, answer, and then come from the database the second time. That is three
    # separate claims and each one is checked.
    def refusing_agent(question, **kw):
        out = fake_run_agent(question, **kw)
        out["answer"] = "Not stated in the filing."
        return out
    appmod.agent.run_agent = refusing_agent
    TESLA = "What was Tesla's total revenue for fiscal year 2025?"

    r1 = client.post("/ask", json={"question": TESLA}, headers=H).json()
    assert r1["cache_hit"] is False, "a cold question hit the cache"
    assert r1["answer"].startswith("Not stated"), r1["answer"]
    # it went through the real pipeline: it was PAID for, and it has a trace with sources
    assert r1["trace"]["usd"] > 0, "the out-of-corpus question was not actually run"
    assert r1["trace"]["calls"], "no model calls recorded for an out-of-corpus question"
    # ...and unlike 6.5, the refusal is now STORED
    assert r1["cached"] is True, r1.get("not_cached_because")
    ok += 1

    # the second ask is served from the database, free, and is the same refusal
    r2 = client.post("/ask", json={"question": TESLA}, headers=H).json()
    assert r2["cache_hit"] is True, "the stored refusal was not served"
    assert r2["answer"] == r1["answer"]
    assert r2["cached_is_refusal"] is True, r2
    assert r2["trace"]["usd"] == 0, "a single-turn cache hit charged the reader"
    # the saving is recorded, and it equals what the first run actually paid - not an estimate
    assert abs(r2["trace"]["saved_usd"] - r1["trace"]["usd"]) < 1e-12, (r2["trace"], r1["trace"])
    assert r2["trace"]["saved_input_tokens"] == r1["trace"]["input_tokens"]
    ok += 1

    # a refusal from a run whose PLANNER FELL BACK must NOT be stored. That run searched blind,
    # so its refusal may be transient - the one blip route that can still reach here.
    def degraded_agent(question, **kw):
        out = refusing_agent(question, **kw)
        out["degraded"] = "planner-fallback: TimeoutError"
        return out
    appmod.agent.run_agent = degraded_agent
    r = client.post("/ask", json={"question": "What was Rivian's net income in 2025?"},
                    headers=H).json()
    assert r["cached"] is False and "degraded" in r["not_cached_because"], r
    appmod.agent.run_agent = fake_run_agent
    ok += 1

    # --- the UI is served, and it is the real one -----------------------------------------
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    page = r.text
    # These four are the things the 6.3 mockup did not have and the learner asked for. A
    # smoke test that only checked for "200 OK" would happily pass on the old mockup.
    for needed in ("authform", "convs", "trace", "askform"):
        assert needed in page, f"the served UI has no {needed} - is this still the mockup?"
    # NOT a substring check on "ui_mockup" - the real file mentions the mockup by name in its
    # header, explaining what it replaces, so that check failed on a correct page. Check for
    # the mockup's own marker instead: the thing that would be true if the WRONG file were
    # being served.
    assert "DESIGN ONLY" not in page, "app.py is serving the 6.3 mockup, not the real UI"
    ok += 1

    # --- follow-ups actually reach the rewriter, and the cache is keyed on the REWRITE ------
    # Both of these were live defects found by using the UI, not by any test here:
    #   1. /ask called run_agent with no history, so the 6.4 rewriter never ran in the app.
    #   2. the cache was keyed on the RAW question, so "And AMD?" became a global key - the
    #      catastrophic cache key the tracker named in the 6.5 plan, shipped by accident.
    import cache as _cache
    import rewriter as _rw
    _c2 = db.connect(); _cache.clear(_c2); _c2.close()

    seen_rewrites = []

    def fake_rewrite(question, history):
        seen_rewrites.append((question, list(history or [])))
        if not history:
            return question, "no-history"
        return "REWRITTEN " + question, None

    real_rewrite, appmod.rewriter.rewrite = appmod.rewriter.rewrite, fake_rewrite
    try:
        first = client.post("/ask", json={"question": "Base question about NVIDIA?"},
                            headers=H).json()
        cid = first["conversation_id"]
        assert seen_rewrites, (
            "FAIL: /ask never called the rewriter at all. The 6.4 rewriter was built, tested "
            "in isolation, and never wired into the serving path.")
        assert seen_rewrites[-1][1] == [], "a first turn must have no history"

        follow = client.post("/ask", json={"question": "And AMD?", "conversation_id": cid},
                             headers=H).json()
        # the rewriter must have SEEN the conversation
        q_seen, hist_seen = seen_rewrites[-1]
        assert q_seen == "And AMD?", q_seen
        assert len(hist_seen) >= 2, (
            f"FAIL: /ask passed {len(hist_seen)} history turns - the rewriter cannot resolve "
            f"a follow-up it was never shown. This is the defect the UI exposed.")
        assert hist_seen[-1][0] == "assistant", "history should end with the previous answer"
        assert not any(h[1] == "And AMD?" for h in hist_seen), \
            "the question being asked must not be inside its own history"
        # ...and the trace must record what the pipeline was actually asked
        assert follow["trace"]["question_rewritten"] == "REWRITTEN And AMD?", follow["trace"]
        ok += 1

        # THE CACHE KEY. "And AMD?" must be stored under the REWRITTEN question, so the same
        # words in a different conversation cannot collect someone else's answer.
        _c3 = db.connect()
        keys = [r["normalised_question"] for r in
                _c3.execute("SELECT normalised_question FROM answer_cache").fetchall()]
        _c3.close()
        assert "and amd?" not in keys and "and amd" not in keys, (
            f"FAIL: the cache is keyed on the raw follow-up. Keys: {keys}. "
            f'"And AMD?" means something different in every conversation.')
        assert any(k.startswith("rewritten and amd") for k in keys), keys
        ok += 1
    finally:
        appmod.rewriter.rewrite = real_rewrite

    # --- export: the transcript, and ONLY the transcript ------------------------------------
    conv_for_export = client.get("/conversations").json()["conversations"][0]["id"]
    detail = client.get("/conversations/" + str(conv_for_export)).json()
    said = [m["content"] for m in detail["messages"]]
    for fmt, sig in (("docx", b"PK"), ("pdf", b"%PDF")):
        r = client.get(f"/conversations/{conv_for_export}/export?format={fmt}")
        assert r.status_code == 200, f"{fmt}: {r.status_code} {r.text[:200]}"
        assert r.content[:4].startswith(sig), f"{fmt} is not a real {fmt} file"
        assert "attachment" in r.headers.get("content-disposition", "")
        assert len(r.content) > 800, f"{fmt} export is suspiciously small"
    # a docx is a zip of XML, so the transcript text is greppable inside it - which lets the
    # test check the thing that actually matters: the conversation is in, the analysis is out.
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(
        client.get(f"/conversations/{conv_for_export}/export?format=docx").content))
    xml = z.read("word/document.xml").decode("utf-8", "replace")
    assert any(t[:30] in xml for t in said), "the export does not contain the conversation"
    for leaked in ("agent-generation", "chunk_ids", "nvda-fy2026", "input_tokens",
                   "gemini-3.1-flash-lite"):
        assert leaked not in xml, f"the transcript export leaked analysis: {leaked!r}"
    ok += 1

    # another user must not be able to export this conversation
    assert other.get(f"/conversations/{conv_for_export}/export").status_code == 404
    ok += 1

    # --- app.py must survive being imported TWICE --------------------------------------------
    # Not a hypothetical. `python app.py` runs this file as `__main__`, then uvicorn's import
    # string re-imports it as `app`, and the second pass died on
    #     AssertionError: cost tracking reached only []
    # because the start-up check asserted on what telemetry.install() CHANGED rather than on
    # what was true. Every route test above passed the whole time - they import the module once,
    # like every harness in this repo, so none of them could see it. Booting the module a second
    # time is the smallest thing that can.
    import importlib.util
    spec = importlib.util.spec_from_file_location("app_second_import", appmod.__file__)
    second = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(second)          # must not raise
    assert not appmod.telemetry.unpatched(appmod.judges, appmod.rag,
                                          appmod.agent, appmod.rewriter), \
        "a second import left cost tracking detached"
    ok += 1

    print(f"\ntest_app.py: {ok}/{ok} route checks passed, $0.00 spent")
    for note in skipped:
        print(f"  SKIPPED: {note}")
    print("  NOT covered here: that the real agent still returns the keys /ask reads.")
    print("  A stub agrees with whatever I imagined. One paid smoke request closes that.")


if __name__ == "__main__":
    import auth  # noqa: F401  (used above; imported here so the module-level swap runs first)
    sys.exit(main())
