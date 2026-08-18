# smoke_cache.py
# Phase 6.5 - the cache, measured against the REAL agent through the REAL API.
#
# test_app.py already covers the cache with a stubbed agent: hit, miss, near-miss, cross-user,
# and the refusal to store an answer produced under attack. All of that is free and none of it
# can tell you the one thing that matters commercially - what fraction of real questions a
# normalised exact-match key actually catches, and what that is worth.
#
# WHAT IS BEING MEASURED, and the honest limit of it. This asks a small set of questions twice
# and reports the hit rate. Round two is a REPEAT by construction, so the hit rate here is not
# a forecast of production traffic - it is the answer to "when a question genuinely repeats,
# does the key catch it?", which is the part that is under this repo's control. What real users
# actually re-ask is unknown and will stay unknown until there is real traffic; saying "89%
# hit rate" from a script that repeats every question on purpose would be a manufactured
# number, and this project has retracted one of those already.
#
# The paraphrase round is the interesting one: same meaning, different wording, and the key
# only folds what normalise() folds. Whatever fraction of those miss is the price of refusing
# to key on embeddings - and probe_cache_keys.py is why that price is being paid.
#
# COST: 4 distinct questions + 3 near-misses paid once each, everything else free. About
# $0.005, call it Rs 0.45. Throwaway database - app.db is untouched.

import os
import tempfile

os.environ["APP_DB"] = os.path.join(tempfile.mkdtemp(prefix="fa-cache-"), "smoke.db")
os.environ["COOKIE_INSECURE"] = "1"

# Four questions that a demo or a returning analyst would plausibly repeat.
QUESTIONS = [
    "What was NVIDIA's total revenue for fiscal year 2026?",
    "What was AMD's total revenue for fiscal year 2025?",
    "What was Intel's total revenue for fiscal year 2025?",
    "What were NVIDIA's total assets at the end of fiscal year 2026?",
]

# Same meaning, different wording. normalise() folds case, whitespace, trailing punctuation
# and the FY spellings - and nothing else. These deliberately test both sides of that line.
PARAPHRASES = [
    ("What was NVIDIA's total revenue for FY2026?", True),      # folded: FY -> fiscal year
    ("what was amd's total revenue for fiscal year 2025", True),  # folded: case, punctuation
    ("How much revenue did Intel report in fiscal year 2025?", False),   # NOT folded: reworded
    ("What was NVIDIA's total asset balance at fiscal year-end 2026?", False),   # NOT folded
]

# Every one of these scored above a usable embedding threshold in probe_cache_keys.py. If any
# of them HITS, the key is unsafe and the whole design argument collapses.
NEAR_MISSES = [
    "What was NVIDIA's total revenue for fiscal year 2025?",
    "What was AMD's total revenue for fiscal year 2026?",
    "What was NVIDIA's net income for fiscal year 2026?",
]


def main():
    from fastapi.testclient import TestClient
    import app as appmod
    import cache

    if not appmod.agent.FILINGS:
        raise SystemExit("  the index is empty - run build_index.py first, do not pay for this")
    print(f"\n  index {len(appmod.agent.FILINGS)} filings   fingerprint "
          f"{appmod.CACHE_FINGERPRINT}   cache {'ON' if appmod.CACHE_ENABLED else 'OFF'}")

    c = TestClient(appmod.app)
    csrf = c.post("/auth/signup", json={"email": "cache@example.com",
                                        "password": "a-throwaway-long-passphrase"}
                  ).json()["csrf_token"]
    H = {"X-CSRF-Token": csrf}

    spent = []

    def ask(q):
        r = c.post("/ask", json={"question": q}, headers=H)
        assert r.status_code == 200, r.text
        j = r.json()
        spent.append(j["trace"]["usd"])
        return j

    print(f"\n  --- round 1: cold, every question paid for ---")
    for q in QUESTIONS:
        r = ask(q)
        assert r["cache_hit"] is False, f"a cold cache hit on {q!r}"
        note = "stored" if r["cached"] else f"NOT stored: {r['not_cached_because']}"
        print(f"    ${r['trace']['usd']:.6f}  {note:34} {q[:52]}")

    print(f"\n  --- round 2: the identical questions ---")
    hits = 0
    for q in QUESTIONS:
        r = ask(q)
        hits += r["cache_hit"]
        assert r["trace"]["usd"] == 0 or not r["cache_hit"], "a hit charged the user"
        print(f"    {'HIT ' if r['cache_hit'] else 'MISS'}  ${r['trace']['usd']:.6f}  {q[:60]}")

    print(f"\n  --- round 3: paraphrases (only what normalise() folds may hit) ---")
    para_ok = 0
    for q, expected_hit in PARAPHRASES:
        r = ask(q)
        got = r["cache_hit"]
        mark = "ok" if got == expected_hit else "UNEXPECTED"
        if got == expected_hit:
            para_ok += 1
        print(f"    {'HIT ' if got else 'MISS'}  expected {'HIT ' if expected_hit else 'MISS'}"
              f"  {mark:11} {q[:52]}")

    print(f"\n  --- round 4: near-misses. ANY hit here is a defect ---")
    for q in NEAR_MISSES:
        r = ask(q)
        print(f"    {'HIT ' if r['cache_hit'] else 'MISS'}  {q[:64]}")
        assert not r["cache_hit"], (
            f"CACHE COLLISION on a near-miss: {q!r}. The key is unsafe - this is the "
            f"wrong-year answer probe_cache_keys.py predicted.")

    conn = appmod.db.connect()
    s = cache.stats(conn)
    conn.close()
    spent_total = sum(spent)
    paid_calls = sum(1 for x in spent if x > 0)

    print(f"\n{'=' * 92}")
    print(f"  repeat hit rate      {hits}/{len(QUESTIONS)}   (round 2, identical questions)")
    print(f"  paraphrase behaviour {para_ok}/{len(PARAPHRASES)} matched what normalise() "
          f"claims to fold")
    print(f"  near-miss collisions 0/{len(NEAR_MISSES)}   <- the only number that must be zero")
    # The first version of this block printed "a repeated question costs 153% of what it cost
    # the first time", which is not merely a bad metric - it is FALSE. A repeated question
    # costs zero. The 153% came from dividing savings accumulated across every round by
    # round 1's spend alone: two numbers over different populations, put in a ratio because
    # they were both to hand. A report that states something untrue is worse than one that
    # states nothing, so what is printed now is only what was actually observed.
    print(f"\n  a cache hit costs        $0.000000   (measured above, every hit)")
    print(f"  entries stored           {s['entries']}")
    print(f"  hits served              {s['hits']}")
    print(f"  generation avoided       ${s['saved_usd']:.6f} and "
          f"{s['saved_input_tokens']:,} input tokens")
    print(f"  actually spent this run  ${spent_total:.6f} over {paid_calls} paid questions")
    print(f"  the same run with no cache would have cost "
          f"${spent_total + s['saved_usd']:.6f}")
    print(f"{'=' * 92}")
    print("\n  This hit rate is NOT a production forecast - round 2 repeats every question on")
    print("  purpose. It answers only: when a question genuinely repeats, does the key catch")
    print("  it? What real users re-ask is unknown until there is real traffic.")
    print(f"\n  throwaway database: {os.environ['APP_DB']}")


if __name__ == "__main__":
    main()
