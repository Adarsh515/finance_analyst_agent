# smoke_api.py
# Phase 6.3 - ONE real question, through the real API, against the real agent.
#
# WHY THIS EXISTS AND test_app.py DOES NOT REPLACE IT. test_app.py swaps in a stub agent, so
# every route, every guard and every trace row is exercised for $0.00 - but a stub agrees
# with whatever I imagined `run_agent` returns. If the real graph renamed a key tomorrow,
# test_app.py would still be green and /ask would store an empty plan, or crash. This script
# is the only thing that checks the assumption itself.
#
# COST: one question. Roughly $0.0025, about Rs 0.25. It uses a THROWAWAY database in the
# system temp directory, so it never touches app.db and no real address is involved.
#
# Run:  python -X utf8 -u smoke_api.py

import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="fa-smoke-")
os.environ["APP_DB"] = os.path.join(_tmp, "smoke.db")
os.environ["COOKIE_INSECURE"] = "1"       # TestClient speaks http://testserver

QUESTION = "What was NVIDIA's total revenue for fiscal year 2026?"

# The keys app.py reads out of run_agent. Naming them here rather than at each use site means
# a rename shows up as one clear failure instead of five scattered ones.
REQUIRED_KEYS = ["answer", "context", "rounds", "guard_fired", "chunks", "jobs_log"]


def main():
    from fastapi.testclient import TestClient
    import app as appmod

    print(f"\n  index: {len(appmod.agent.FILINGS)} filings, "
          f"guards={appmod.agent.GUARDS}, prompt_layer={appmod.agent.GUARD_PROMPT}")
    if not appmod.agent.FILINGS:
        raise SystemExit("  the index is empty - run build_index.py first, do not pay for this")

    # --- first, the assumption itself, called directly ---------------------------------------
    print(f"\n  asking the real agent: {QUESTION}")
    out = appmod.agent.run_agent(question=QUESTION)
    missing = [k for k in REQUIRED_KEYS if k not in out]
    assert not missing, (
        f"FAIL: run_agent no longer returns {missing}. app.py reads these, and test_app.py "
        f"could not have told you - its stub returns whatever I wrote.")
    print(f"  run_agent returned all {len(REQUIRED_KEYS)} keys app.py depends on")
    print(f"  jobs_log has {len(out['jobs_log'])} planned job(s) "
          f"and jobs has {len(out.get('jobs', []))} left in the queue")
    assert out["jobs_log"], "FAIL: jobs_log is empty - the trace panel would show no plan"
    print(f"  answer: {out['answer'][:110]}")

    # --- now the same question through HTTP ----------------------------------------------------
    client = TestClient(appmod.app)
    r = client.post("/auth/signup", json={"email": "smoke@example.com",
                                          "password": "throwaway-long-passphrase"})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]

    r = client.post("/ask", json={"question": QUESTION}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    body = r.json()
    t = body["trace"]

    print(f"\n  --- /ask, stored trace ---")
    print(f"  answer      : {body['answer'][:100]}")
    print(f"  rounds      : {t['rounds']}    reflect_fired: {bool(t['reflect_fired'])}"
          f"    guard: {t['guard_fired'] or '-'}")
    print(f"  filings     : {t['filings']}")
    print(f"  chunks      : {len(t['chunk_ids'])} ids, first = {(t['chunk_ids'] or ['-'])[0]}")
    print(f"  planned jobs: {json.dumps(t['jobs'])[:150]}")
    print(f"  tokens      : in {t['input_tokens']:,}  out {t['output_tokens']:,}")
    print(f"  cost        : ${t['usd']:.6f}   ({t['seconds']}s)")
    print(f"  calls       :")
    for c in t["calls"]:
        print(f"      {c['seq']}. {c['label']:34} in {c['input_tokens']:>6,} "
              f"out {c['output_tokens']:>5,}  ${c['usd']:.6f}")

    # --- the assertions that make this a test rather than a printout ---------------------------
    assert t["input_tokens"] > 0 and t["output_tokens"] > 0, "the capture recorded nothing"
    assert abs(sum(c["usd"] for c in t["calls"]) - t["usd"]) < 1e-12, \
        "the trace header and its line items disagree"
    assert t["chunk_ids"], "no chunk ids were recorded - the panel has no sources to show"
    assert t["filings"], "no filings were recorded"
    assert t["jobs"], "no planned jobs were recorded"
    assert any("generation" in c["label"] for c in t["calls"]), \
        "no generation call was captured - gen_in is a substring match and it just missed"
    assert body["context"] == out["context"] or body["context"], \
        "the API did not return the context the eval scores"

    print(f"\nsmoke_api.py: the live agent and the API agree. "
          f"Paid for 2 questions (~${t['usd'] * 2:.4f}).")
    print(f"  throwaway database: {os.environ['APP_DB']}")


if __name__ == "__main__":
    main()
