# probe_cache_keys.py
# Phase 6.5, step 1 - measure whether an embedding can tell two questions apart BEFORE any
# cache is built on the assumption that it can.
#
# THE ASSUMPTION UNDER TEST. "Semantic cache" normally means: embed the incoming question,
# find the nearest cached question, and if the cosine similarity is above some threshold,
# serve the stored answer. That works when near-identical questions have near-identical
# answers. In THIS domain they do not:
#
#     "What was NVIDIA's total revenue for fiscal year 2026?"   ->  $215,938M
#     "What was NVIDIA's total revenue for fiscal year 2025?"   ->  $130,497M
#
# One character apart, and a 65% difference in the answer. Lesson 56 already recorded that
# unrelated text routinely scores 0.70-0.80 in this embedding space, so a threshold that
# rejects a year swap may well reject everything. This probe finds out with numbers instead
# of with an argument.
#
# WHY THIS RUNS FIRST. The tracker's plan for 6.5 says the poison test is written BEFORE the
# cache. A cache is a component whose failure is SILENT and DELAYED: it serves a plausible,
# confident, wrong answer, and nothing in the pipeline downstream of it disagrees. Building
# it first and testing it after would mean the first evidence of a bad key design is a wrong
# number in front of a user.
#
# COST: embeddings only, at $0.15 per million tokens. About 60 short questions is roughly
# 900 tokens - well under a hundredth of a rupee. No generation, no judges.

import itertools

from dotenv import load_dotenv

from rag import embeddings

load_dotenv()


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# --- the pairs, and what each one is asking of the embedding -------------------------------
# SAME: should hit the cache. Different wording, identical meaning and identical answer.
# NEAR-MISS: must NOT hit the cache. One token apart, materially different answer.
SAME = [
    ("What was NVIDIA's total revenue for fiscal year 2026?",
     "What was NVIDIA's total revenue in FY2026?"),
    ("What was NVIDIA's total revenue for fiscal year 2026?",
     "How much revenue did NVIDIA report for fiscal 2026?"),
    ("What was AMD's net income for fiscal year 2025?",
     "AMD's net income in fiscal 2025 was how much?"),
    ("What were NVIDIA's total assets at the end of fiscal year 2026?",
     "What was NVIDIA's total asset balance at fiscal year-end 2026?"),
    ("What was Intel's total revenue for fiscal year 2025?",
     "How much did Intel earn in revenue during fiscal year 2025?"),
]

NEAR_MISS = [
    # the period axis - the most dangerous one in this corpus, because every filing carries a
    # comparison column for the year before, so a wrong year returns a real, wrong number
    ("What was NVIDIA's total revenue for fiscal year 2026?",
     "What was NVIDIA's total revenue for fiscal year 2025?", "year swapped"),
    ("What was NVIDIA's revenue in the third quarter of fiscal year 2026?",
     "What was NVIDIA's revenue for the full fiscal year 2026?", "quarter vs annual"),
    # the entity axis
    ("What was NVIDIA's total revenue for fiscal year 2026?",
     "What was AMD's total revenue for fiscal year 2026?", "company swapped"),
    ("What was AMD's net income for fiscal year 2025?",
     "What was Intel's net income for fiscal year 2025?", "company swapped"),
    # the metric axis
    ("What was NVIDIA's total revenue for fiscal year 2026?",
     "What was NVIDIA's net income for fiscal year 2026?", "metric swapped"),
    ("What were NVIDIA's total assets at the end of fiscal year 2026?",
     "What were NVIDIA's total liabilities at the end of fiscal year 2026?", "metric swapped"),
    # direction, which changes the answer completely and barely changes the text
    ("Whose gross margin was higher in the most recent fiscal year, NVIDIA or AMD?",
     "Whose gross margin was lower in the most recent fiscal year, NVIDIA or AMD?",
     "higher vs lower"),
]

UNRELATED = [
    ("What was NVIDIA's total revenue for fiscal year 2026?",
     "Which companies are covered in this corpus?"),
    ("What was AMD's net income for fiscal year 2025?",
     "What are AMD's three reportable segments?"),
]

if __name__ == "__main__":
    texts = sorted({t for pair in SAME + UNRELATED for t in pair}
                   | {t for a, b, _w in NEAR_MISS for t in (a, b)})
    print(f"\n  embedding {len(texts)} short questions with the SAME model the index uses")
    vecs = dict(zip(texts, embeddings.embed_documents(texts)))
    print(f"  dimension {len(next(iter(vecs.values())))}\n")

    print(f"  {'kind':11} {'cos':>6}   pair")
    same_scores, miss_scores, un_scores = [], [], []
    for a, b in SAME:
        c = cosine(vecs[a], vecs[b])
        same_scores.append(c)
        print(f"  {'SAME':11} {c:6.4f}   {b[:66]}")
    print()
    for a, b, why in NEAR_MISS:
        c = cosine(vecs[a], vecs[b])
        miss_scores.append((c, why, b))
        print(f"  {'NEAR-MISS':11} {c:6.4f}   {why:18} {b[:48]}")
    print()
    for a, b in UNRELATED:
        c = cosine(vecs[a], vecs[b])
        un_scores.append(c)
        print(f"  {'UNRELATED':11} {c:6.4f}   {b[:66]}")

    lo_same = min(same_scores)
    hi_miss = max(c for c, _w, _b in miss_scores)
    hi_un = max(un_scores)

    print(f"\n{'=' * 100}")
    print(f"  lowest  SAME      {lo_same:.4f}   <- a threshold must be BELOW this to hit at all")
    print(f"  highest NEAR-MISS {hi_miss:.4f}   <- and ABOVE this to be safe")
    print(f"  highest UNRELATED {hi_un:.4f}")
    print(f"{'=' * 100}")

    if hi_miss >= lo_same:
        worst = max(miss_scores)
        print(f"\n  NO THRESHOLD EXISTS. The worst near-miss ({worst[1]}, {worst[0]:.4f}) scores")
        print(f"  AT OR ABOVE the weakest genuine paraphrase ({lo_same:.4f}), so any cut-off")
        print(f"  either misses real hits or serves a wrong-year / wrong-company answer.")
        print(f"  A cosine number is not a fact about meaning; it is a fact about wording.")
        print(f"\n  => the cache key CANNOT be embedding similarity alone. It must be")
        print(f"     structural - company, period and metric - with the embedding, at most,")
        print(f"     narrowing candidates that already agree on all three.")
    else:
        gap = lo_same - hi_miss
        print(f"\n  A threshold exists, in the band {hi_miss:.4f} - {lo_same:.4f} "
              f"(width {gap:.4f}).")
        print(f"  That band is what this repo would be betting a wrong-year answer on. It is")
        print(f"  measured on {len(SAME)} paraphrases and {len(NEAR_MISS)} near-misses that I")
        print(f"  wrote, which is far too few to trust a narrow gap - lesson 82. Structural")
        print(f"  keying is still the safer design; this only says it is not FORCED.")
