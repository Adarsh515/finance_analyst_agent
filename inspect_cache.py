"""
inspect_cache.py - why did that question cost money again?

A cache that misses is invisible from the outside: the answer looks the same, the spend goes
up, and nothing in the UI says which key was looked for. This prints the two tables that
actually decide it, side by side, so the answer is read rather than guessed.

WHAT TO LOOK AT. The cache is keyed on the REWRITTEN question, not on what you typed
(Phase 6.5 - keying on the raw follow-up made "And AMD?" a single global key, which is the
catastrophic case the plan named in writing). So if the same typed text produces a different
rewrite, it produces a different key, and it pays again. The `rewritten` column below is the
one that matters; `you typed` is only there to show they can differ.

Free: reads app.db, calls no model, changes nothing.

    python inspect_cache.py            # the last 15 answered questions
    python inspect_cache.py --all      # ...and every row in the cache
"""

import sys

import cache
import db


def main():
    show_all = "--all" in sys.argv
    conn = db.connect()

    print(f"\n  database: {db.DB_PATH}   schema v{db.schema_version(conn)}")

    rows = conn.execute(
        "SELECT t.id, t.question_raw, t.question_rewritten, t.cache_hit, t.usd, "
        "       t.saved_usd, t.input_tokens, t.created_at, t.conversation_id "
        "FROM traces t ORDER BY t.id DESC LIMIT ?", (200 if show_all else 15,)
    ).fetchall()

    if not rows:
        print("\n  no answered questions yet.")
        return

    print(f"\n  --- the last {len(rows)} answered questions, newest first ---")
    for r in reversed(rows):
        asked = r["question_rewritten"] or r["question_raw"]
        mark = "HIT " if r["cache_hit"] else "PAID"
        print(f"\n  [{r['id']:>3}] {mark}  conv {r['conversation_id']}  ${r['usd']:.6f}"
              + (f"  saved ${r['saved_usd']:.6f}" if r["saved_usd"] else "")
              + f"  {r['created_at']}")
        print(f"        you typed : {r['question_raw']}")
        if r["question_rewritten"]:
            print(f"        rewritten : {r['question_rewritten']}")
        else:
            print(f"        rewritten : (no history - the raw question was used)")
        # The key is recomputed with TODAY'S fingerprint, which is the only one available -
        # traces do not store the fingerprint that was live when they ran. That matters, and
        # the first version of this script quietly got it wrong: two rows with an identical
        # rewrite print an identical key here even when one of them was stored under an OLDER
        # index and is now unreachable. So the reachability is checked against the cache table
        # rather than inferred from the key alone.
        k = cache.key_for(asked, _fingerprint())
        row = conn.execute("SELECT hits, fingerprint FROM answer_cache WHERE key_hash = ?",
                           (k,)).fetchone()
        reach = (f"reachable now (hits {row['hits']})" if row else
                 "NOT in the cache under today's index")
        print(f"        cache key : {k[:16]}…   {reach}")
        print(f"        normalised: {cache.normalise(asked)[:70]!r}")

    # Group by what was TYPED, so a repeat that paid twice is impossible to miss.
    print(f"\n  --- the same typed question, asked more than once ---")
    by_typed = {}
    for r in rows:
        by_typed.setdefault(cache.normalise(r["question_raw"]), []).append(r)
    repeats = {k: v for k, v in by_typed.items() if len(v) > 1}
    if not repeats:
        print("    none in this window.")
    for typed, group in repeats.items():
        paid = sum(1 for r in group if not r["cache_hit"])
        print(f"\n    {typed[:78]!r}")
        print(f"      asked {len(group)}x, PAID {paid}x")
        keys = {cache.key_for(r["question_rewritten"] or r["question_raw"],
                              _fingerprint()) for r in group}
        rews = {(r["question_rewritten"] or r["question_raw"]) for r in group}
        # TWO causes look identical from the outside and must not be reported as one.
        #   (a) the rewrite differed  -> genuinely different keys, a real miss
        #   (b) the INDEX was rebuilt -> same key, but the old entry was stored under a
        #       different fingerprint and is unreachable by design (lesson 122)
        # The first version of this script only checked (a) and so blamed the rewriter for
        # misses that a rebuild had caused. A diagnostic that cannot tell its two causes apart
        # will send someone to fix the wrong thing.
        fps = set()
        for r in group:
            e = conn.execute("SELECT fingerprint FROM answer_cache WHERE key_hash = ?",
                             (cache.key_for(r["question_rewritten"] or r["question_raw"],
                                            _fingerprint()),)).fetchone()
            fps.add(e["fingerprint"] if e else None)
        if len(keys) > 1:
            print(f"      🔴 {len(keys)} DIFFERENT cache keys, because the REWRITE differed:")
            for w in sorted(rews):
                print(f"           - {w}")
            print(f"      Same words typed, different standalone question, different key.")
            print(f"      The cache is exact-match by design (Phase 6.5).")
        else:
            print(f"      one key for all of them, so the rewrite is NOT the cause.")
            print(f"      Most likely an index rebuild: the fingerprint is part of the key,")
            print(f"      so entries made under an older index are unreachable on purpose.")
            print(f"      Check the timestamps against when build_index.py last ran.")

    print(f"\n  --- what is actually stored ---")
    s = cache.stats(conn)
    print(f"    entries {s['entries']}  (refusals {s['refusal_entries']})   "
          f"hits {s['hits']}  (on refusals {s['refusal_hits']})   "
          f"generation avoided ${s['saved_usd']:.6f}")
    limit = 1000 if show_all else 12
    for e in conn.execute(
            "SELECT normalised_question, hits, is_refusal, usd, created_at "
            "FROM answer_cache ORDER BY rowid DESC LIMIT ?", (limit,)):
        tag = "refusal" if e["is_refusal"] else "answer "
        print(f"    {tag}  hits {e['hits']:>2}  cost-when-made ${e['usd']:.6f}  "
              f"{e['normalised_question'][:64]!r}")

    conn.close()
    print("\n  Nothing was called and nothing changed. $0.00 spent.")


def _fingerprint():
    # Imported lazily: pulling in app.py drags the whole agent and the index with it, and this
    # script should stay runnable when they are slow to load.
    import app
    return app.CACHE_FINGERPRINT


if __name__ == "__main__":
    main()
