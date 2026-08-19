# cache.py
# Phase 6.5 - the answer cache, designed AFTER the measurement that killed the design it was
# supposed to have.
#
# ==========================================================================================
# THE PLAN SAID "SEMANTIC CACHE". THE MEASUREMENT SAYS NO SUCH THING IS SAFE HERE.
# ==========================================================================================
# probe_cache_keys.py embedded 20 questions with the same model the index uses:
#
#     lowest  genuine paraphrase   0.9858     a threshold must be BELOW this to ever hit
#     highest near-miss            0.9960     and ABOVE this to be safe
#
# There is no such number. The worst near-miss scores HIGHER than the weakest real
# paraphrase, so every possible cut-off either never hits or serves a wrong answer. Worse,
# look at WHICH pair scored 0.9960:
#
#     "Whose gross margin was HIGHER ... NVIDIA or AMD?"
#     "Whose gross margin was LOWER  ... NVIDIA or AMD?"
#
# The two questions with OPPOSITE answers are the two most similar vectors in the whole
# probe. One word apart. That is lesson 56 arriving with consequences: a cosine number is a
# fact about WORDING, not about meaning.
#
# The probe also showed which axes ARE separable, which matters for what gets built:
#
#     company swapped    0.917 - 0.922      separable
#     metric swapped     0.963 - 0.968      marginal
#     year swapped       0.9843             NOT separable (weakest paraphrase is 0.9858)
#     higher vs lower    0.9960             inverted - the danger scores highest of all
#
# So a structural key on (company, period, metric) is ALSO insufficient on its own: "higher"
# and "lower" agree on all three fields and have opposite answers.
#
# WHAT SHIPS: a normalised EXACT-MATCH cache. Not semantic. The normalisation folds case,
# whitespace and trailing punctuation, and canonicalises the fiscal-year spellings that mean
# the same thing - and nothing else, because every further liberty is a chance to serve the
# wrong year. If the hit rate turns out too low to be worth having, that is a measurement to
# report, not a reason to loosen the key.
#
# ==========================================================================================
# WHY THE CACHE LIVES IN THE SERVING LAYER AND NOT IN THE AGENT
# ==========================================================================================
# The contract is "cache OFF during evals". A flag would satisfy that contract only as long
# as every harness remembered to set it - and lesson 96 is precisely about a harness whose
# default contradicted the shipped configuration for weeks. So the cache is not wired into
# agent.run_agent at all. run_eval.py and red_team.py call run_agent directly and CANNOT
# reach it; only app.py's /ask consults it. "Off during evals" is a fact about the call
# graph, not a promise about a flag.
#
# Free to test: python cache.py

import hashlib
import json
import re

import db

# --- what is allowed to be folded together -------------------------------------------------
# Each rule here is a claim that two strings mean the same thing. The list is deliberately
# short: "FY2026" and "fiscal year 2026" are the same period, and that is about as far as
# certainty goes. Anything cleverer is a chance to serve a wrong-year answer, which is the
# exact failure the probe found no way to detect.
_FY = re.compile(r"\bfy\s*(\d{4})\b", re.I)
_FISCAL = re.compile(r"\bfiscal\s+(?:year\s+)?(\d{4})\b", re.I)
_WS = re.compile(r"\s+")


def normalise(question):
    """Fold only the differences that provably do not change the answer."""
    q = (question or "").strip().lower()
    q = _FY.sub(r"fiscal year \1", q)
    q = _FISCAL.sub(r"fiscal year \1", q)
    q = re.sub(r"[?!.,;:]+$", "", q)
    q = _WS.sub(" ", q)
    return q.strip()


def key_for(question, fingerprint):
    """The cache key. The FINGERPRINT is part of it, not a column to check afterwards.

    An entry keyed without it survives a corpus change and answers a new question with an old
    corpus's numbers - silently, because nothing downstream of a cache disagrees with it.
    Folding it into the key means a rebuilt index cannot hit a stale entry at all; the old
    rows simply become unreachable.
    """
    return hashlib.sha256(f"{fingerprint}\x00{normalise(question)}".encode()).hexdigest()


def index_fingerprint(filings, chunk_count=None):
    """A short digest of what the index currently holds."""
    blob = json.dumps([sorted(map(list, filings)), chunk_count], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --- what may never be cached ------------------------------------------------------------

_REFUSAL_PREFIXES = ("not stated", "not provided", "not available", "i cannot",
                     "the filings do not", "not disclosed")


def is_refusal(answer):
    """True if this answer declines to give a figure. One definition, used everywhere."""
    return (answer or "").strip().lower().startswith(_REFUSAL_PREFIXES)


def cacheable(answer, guard_fired, *, degraded="", chunk_count=None):
    """Return (ok, reason_if_not). Decided in code, on the record, per answer."""
    if guard_fired:
        # An answer produced while a guard was firing was produced UNDER ATTACK. Storing it
        # would turn one successful injection into a permanent one served to everybody -
        # a one-shot compromise upgraded to persistent, by us, for a saving of $0.0005.
        return False, f"produced under attack ({guard_fired[:40]})"
    low = (answer or "").strip().lower()
    if not low:
        return False, "empty answer"

    # ==========================================================================================
    # REFUSALS ARE CACHED FROM 6.7, AND THIS REVERSES A 6.5 DECISION. Here is what changed.
    # ==========================================================================================
    # 6.5 refused to store them, reasoning: "a refusal is also what a transient failure looks
    # like, and caching one would make a blip permanent." That reasoning had a testable claim
    # inside it - that refusals are unstable - and it was never tested. It has been now, on
    # data already paid for: three independent full gate runs, 94 questions each.
    #
    #     questions that refused in ANY run   5   (q24, q25, q26, q40, x17)
    #     ...that refused in ALL THREE        5
    #     ...with the byte-identical string   5   ("Not stated in the filing.")
    #     refusal <-> answer flips            0
    #
    # And the comparison that gives it teeth: in the run pair where only 33 of 94 answers were
    # byte-identical - 61 real answers reworded themselves between runs - all five refusals
    # came back character for character. Refusals are the MOST stable output this system has,
    # not the least. The 6.5 rule was protecting against the opposite of what happens.
    #
    # The blip it feared cannot reach here by the route it imagined either: llm.invoke has no
    # try/except around it, so a dropped connection RAISES out of /ask as a 500. It does not
    # come back as a polite refusal that then gets stored.
    #
    # WHAT IS STILL REFUSED, because one blip route is real. plan_node catches its own
    # exception and degrades to a single unfiltered search. That run keeps going, retrieves
    # worse context, and can refuse for an entirely transient reason - so a degraded run's
    # refusal is not stored. Nor is a refusal with no evidence behind it: "I looked and it is
    # not there" is a finding worth keeping, "I had nothing to look at" is an outage.
    if is_refusal(low):
        if degraded:
            return False, f"refusal from a degraded run ({degraded})"
        if not chunk_count:
            return False, "refusal with no retrieved context - an outage, not a finding"
    return True, None


# --- storage ------------------------------------------------------------------------------
# Schema v3. GLOBAL, not per-user, and that is a decision worth stating: these are answers
# about public SEC filings, identical for every reader, so per-user isolation would cost hit
# rate and buy nothing. What IS kept per-user is the TRACE and the spend - a cache hit still
# writes its own trace row against the user who asked, so nobody is billed for or credited
# with someone else's question. The producing user is recorded for audit only.

def get(conn, question, fingerprint):
    """Return the cached row for this exact normalised question, or None. Records the hit."""
    row = conn.execute("SELECT * FROM answer_cache WHERE key_hash = ?",
                       (key_for(question, fingerprint),)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE answer_cache SET hits = hits + 1, last_hit_at = ? WHERE key_hash = ?",
                 (db.utcnow(), row["key_hash"]))
    conn.commit()
    return row


def put(conn, *, question, fingerprint, answer, context, guard_fired="", jobs=None,
        filings=None, chunk_ids=None, rounds=None, input_tokens=0, output_tokens=0, usd=0.0,
        user_id=None, retrieval=None, degraded=""):
    """Store one answer, or refuse and say why. Returns (stored, reason_if_not).

    Keyword-only, like db.save_trace and for the same reason: this takes several strings in a
    row, and Phase 1 lost a day to a judge whose arguments were swapped by position.
    """
    ok, why = cacheable(answer, guard_fired, degraded=degraded,
                        chunk_count=len(chunk_ids or []))
    if not ok:
        return False, why
    conn.execute(
        "INSERT OR REPLACE INTO answer_cache (key_hash, normalised_question, question, "
        " answer, context, jobs_json, filings_json, chunk_ids_json, rounds, input_tokens, "
        " output_tokens, usd, fingerprint, created_by, created_at, retrieval_json, "
        " is_refusal, hits) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (key_for(question, fingerprint), normalise(question), question, answer, context,
         json.dumps(jobs) if jobs is not None else None,
         json.dumps(filings) if filings is not None else None,
         json.dumps(chunk_ids) if chunk_ids is not None else None,
         rounds, int(input_tokens), int(output_tokens), float(usd), fingerprint, user_id,
         db.utcnow(), json.dumps(retrieval) if retrieval is not None else None,
         int(is_refusal(answer))))
    conn.commit()
    return True, None


def stats(conn):
    """Cache totals. Refusals are counted apart, because they are a different kind of entry.

    An entry that says "not in these filings" still saves a full pipeline run when it is hit,
    so it belongs in saved_usd. It is NOT an answer, though, and a scoreboard that mixed the
    two would let a cache full of refusals read as a cache full of knowledge.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS entries, COALESCE(SUM(hits),0) AS hits, "
        "COALESCE(SUM(hits * usd),0.0) AS saved_usd, "
        "COALESCE(SUM(hits * input_tokens),0) AS saved_input_tokens, "
        "COALESCE(SUM(is_refusal),0) AS refusal_entries, "
        "COALESCE(SUM(CASE WHEN is_refusal = 1 THEN hits ELSE 0 END),0) AS refusal_hits "
        "FROM answer_cache").fetchone()
    return dict(row)


def clear(conn, refusals_only=False):
    """Empty the cache, or only its refusals.

    refusals_only exists for one specific event: the corpus grows to cover a company that was
    previously absent. Every stored "not in these filings" for that company is now WRONG, and
    the fingerprint in the key already handles it - a rebuilt index makes the old rows
    unreachable. This is the manual escape hatch for the case where the index did not change
    but the judgement did, and it is here so that the answer to "what if a cached refusal goes
    stale?" is one command rather than a shrug.
    """
    conn.execute("DELETE FROM answer_cache WHERE is_refusal = 1" if refusals_only
                 else "DELETE FROM answer_cache")
    conn.commit()


# --- self-test ------------------------------------------------------------------------------
# In-memory, no model, no network, $0.00.

if __name__ == "__main__":
    c = db.init_db(db.connect(":memory:"))
    ok = 0
    FP = index_fingerprint([("NVIDIA", "fiscal year 2026")], 2188)

    # the ONLY things normalisation is allowed to fold
    same = ["What was NVIDIA's total revenue for fiscal year 2026?",
            "what was nvidia's total revenue for FY2026",
            "  What was NVIDIA's   total revenue for fiscal 2026?  "]
    assert len({normalise(q) for q in same}) == 1, {normalise(q) for q in same}
    ok += 1

    # ...and the things it must NEVER fold. Every one of these scored above a usable
    # embedding threshold in probe_cache_keys.py; exact matching is what keeps them apart.
    base = "What was NVIDIA's total revenue for fiscal year 2026?"
    for other in ["What was NVIDIA's total revenue for fiscal year 2025?",
                  "What was AMD's total revenue for fiscal year 2026?",
                  "What was NVIDIA's net income for fiscal year 2026?",
                  "Whose gross margin was lower in the most recent fiscal year, NVIDIA or AMD?"]:
        assert normalise(base) != normalise(other), other
        assert key_for(base, FP) != key_for(other, FP)
    ok += 1

    # store and hit
    stored, why = put(c, question=base, fingerprint=FP, answer="Revenue was $215,938 million.",
                      context="ctx", jobs=[{"company": "NVIDIA"}], filings=["NVIDIA FY2026"],
                      chunk_ids=["a", "b"], rounds=1, input_tokens=4073, output_tokens=25,
                      usd=0.00058, user_id=1)
    assert stored and why is None
    assert get(c, base, FP) is None or get(c, base, FP)["answer"].startswith("Revenue")
    assert get(c, "what was NVIDIA's total revenue for FY2026", FP)["answer"].startswith("Revenue")
    ok += 1

    # a rebuilt index must not be able to reach the old entry AT ALL
    FP2 = index_fingerprint([("NVIDIA", "fiscal year 2026"), ("AMD", "fiscal year 2025")], 3000)
    assert get(c, base, FP2) is None, "a stale entry survived an index change"
    ok += 1

    # an answer produced under attack must never be stored
    stored, why = put(c, question="q2", fingerprint=FP, answer="Revenue was $999,999 million.",
                      context="ctx", guard_fired="quarantine:['999999'] -> regenerated")
    assert not stored and "under attack" in why, why
    ok += 1

    # nor an empty answer
    stored, why = put(c, question="q-empty", fingerprint=FP, answer="   ", context="c")
    assert not stored and why == "empty answer", why
    ok += 1

    # --- refusals: stored from 6.7, but only from a healthy run ------------------------------
    # A refusal with real evidence behind it is a FINDING - "I read these filings and the
    # figure is not in them" - and it is the most reproducible output this system has (three
    # gate runs, five refusals, byte-identical every time). It is stored, and marked.
    tesla = "What was Tesla's total revenue for fiscal year 2025?"
    stored, why = put(c, question=tesla, fingerprint=FP, answer="Not stated in the filing.",
                      context="ctx", chunk_ids=["a", "b", "c"], rounds=1,
                      input_tokens=3900, output_tokens=8, usd=0.00061, user_id=1)
    assert stored, why
    row = get(c, tesla, FP)
    assert row["answer"] == "Not stated in the filing." and row["is_refusal"] == 1
    ok += 1

    # ...but a refusal from a run whose planner fell back is a maybe, not a finding
    stored, why = put(c, question="q-degraded", fingerprint=FP, answer="Not stated in the filing.",
                      context="ctx", chunk_ids=["a"], degraded="planner-fallback")
    assert not stored and "degraded" in why, why
    # ...and a refusal with nothing retrieved is an outage wearing a refusal's clothes
    stored, why = put(c, question="q-nochunks", fingerprint=FP,
                      answer="Not stated in the filing.", context="", chunk_ids=[])
    assert not stored and "no retrieved context" in why, why
    ok += 1

    # a refusal produced under attack is still refused - the attack rule outranks the new one
    stored, why = put(c, question="q-attacked", fingerprint=FP,
                      answer="Not stated in the filing.", context="ctx", chunk_ids=["a"],
                      guard_fired="refusal-with-quarantine")
    assert not stored and "under attack" in why, why
    ok += 1

    s = stats(c)
    assert s["entries"] == 2, s                       # the real answer and the Tesla refusal
    assert s["refusal_entries"] == 1, s
    assert s["hits"] >= 2, s
    # saved_usd must count BOTH kinds: a hit on a refusal skips a full pipeline run too.
    # hits are read with a plain SELECT, never with get() - get() RECORDS a hit, so using it
    # to measure hits would change the number it is being used to check.
    def hits_of(q):
        r = c.execute("SELECT hits FROM answer_cache WHERE key_hash = ?",
                      (key_for(q, FP),)).fetchone()
        return r["hits"] if r else 0
    expect = 0.00058 * hits_of(base) + 0.00061 * hits_of(tesla)
    assert abs(s["saved_usd"] - expect) < 1e-12, (s["saved_usd"], expect)
    ok += 1

    # purging only the refusals must leave the real answers alone - the escape hatch for
    # "the corpus grew and now covers a company we used to decline"
    clear(c, refusals_only=True)
    s = stats(c)
    assert s["entries"] == 1 and s["refusal_entries"] == 0, s
    assert get(c, tesla, FP) is None, "a purged refusal was still served"
    assert get(c, base, FP) is not None, "purging refusals took a real answer with it"
    ok += 1

    clear(c)
    assert stats(c)["entries"] == 0 and get(c, base, FP) is None
    ok += 1

    print(f"cache.py self-test: {ok}/{ok} checks passed, schema v{db.SCHEMA_VERSION}, "
          f"$0.00 spent")
