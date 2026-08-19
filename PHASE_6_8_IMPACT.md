# Phase 6.8 — what adding Tesla does to the 94 eval references

**Status: nothing has been rebuilt or spent yet.** This document is the free part: what
changes, why, and what each new reference value is. Read it, then we rebuild.

**Source discipline.** Tesla's figures were read out of
`data/tesla_10k_fy2025.htm` today, from the parsed consolidated statements. NVIDIA's, AMD's
and Intel's were **not** re-derived — they came from `golden_set.py` / `cross_set.py`, which
this repo has already verified against the filings. That split is deliberate: re-deriving a
figure the repo already owns is the exact defect `corpus_facts.py` was written to prevent.

---

## The sixth filing

| | |
|---|---|
| file | `data/tesla_10k_fy2025.htm`, 2,391,529 bytes |
| form | 10-K, Tesla, Inc. |
| fiscal year | ended **31 December 2025** — *not* the 27 December that Intel and AMD share |
| parses to | **498 pieces** (73 tables, 425 narrative), avg 998 chars — in line with Intel's 667 and AMD's 463 |

## Tesla FY2025, as printed in the filing

| figure | value |
|---|---|
| Total revenues | **$94,827M** |
| Gross profit | $17,094M → gross margin **18.0%** |
| Research and development | $6,411M → **6.8%** of revenue |
| Income from operations | $4,355M *(positive)* |
| Provision for income taxes | $1,423M — an **expense**, not a benefit |
| Net income | $3,855M |
| Net income attributable to common stockholders | **$3,794M** |
| Total assets | **$137,806M** |
| Total liabilities | **$54,941M** — *stated on the balance sheet*, unlike AMD's |
| Net cash provided by operating activities | **$14,747M** |
| Employee headcount at 31 Dec 2025 | **134,785** |
| Segments | Automotive; Energy generation and storage. **No Data Center. No Gaming.** |

## The four-company picture

```
REVENUE      NVIDIA 215,938 > Tesla  94,827 > Intel  52,853 > AMD    34,639
TOTAL ASSETS Intel  211,429 > NVIDIA 206,803 > Tesla 137,806 > AMD    76,926
OP CASH      NVIDIA 102,718 > Tesla  14,747 > Intel   9,697 > AMD     7,709
EMPLOYEES    Tesla  134,785 > Intel  85,100 > NVIDIA  42,000 > AMD    31,000
GROSS MARGIN NVIDIA   71.1% > AMD      50%  > Intel    34.8% > Tesla    18.0%
R&D SHARE    Intel     26.1% > AMD    23.4% > NVIDIA    8.6% > Tesla     6.8%
NET MARGIN   NVIDIA    55.6% > AMD    12.5% > Tesla     4.0% > Intel     -0.5%
```

> ⚠️ One arithmetic note, stated rather than smoothed over: 17,152 / 34,639 computes to
> **49.5%**, while the verified set records AMD's gross margin as **50%**. The verified value
> stands — it is what the filing presents — and the 0.5pp is the filing's own rounding. The
> reference is not being changed to match my division.

---

## Scan result: 36 items flagged, 12 must change

The first scan looked for the phrase *"these filings"* and found 18. It **missed `x25`**
(*"which company employed the most people"*) because that question never says "these filings"
— and Tesla's 134,785 makes it the most wrong answer of the lot. Second scan flags on three
signals instead: the reference names all three companies, the `companies` field holds three or
more, or the question uses a superlative. That found **36**.

### 🔴 MUST CHANGE — the reference is now factually wrong

| id | was | becomes |
|---|---|---|
| `x18` | NVIDIA, by **$163,085M** more than Intel | NVIDIA, by **$121,111M** more than **Tesla** |
| `x23` | combined net income **$124,135M** | **$127,929M** (+ Tesla $3,794M) |
| `x25` | **Intel**, 85,100 people | **Tesla, 134,785** as of 31 Dec 2025 |
| `x27` | lowest gross margin **Intel 34.8%**, R&D share **26.1%** | **Tesla 18.0%**, R&D share **6.8%** |
| `d05` | NVIDIA 89.7%, AMD 48.0% | unchanged **plus** Tesla reports **no Data Center segment** — that must be said, not omitted |
| `d08` | combined revenue **$303,430M**, AMD share **11.4%** | **$398,257M**, AMD share **8.7%** |
| `w01` | NVIDIA > Intel > AMD | NVIDIA 215,938 > **Tesla 94,827** > Intel 52,853 > AMD 34,639 |
| `w03` | NVIDIA > Intel > AMD | NVIDIA 102,718 > **Tesla 14,747** > Intel 9,697 > AMD 7,709 |
| `x19` | NVIDIA most, vs Intel and AMD | leader unchanged; enumeration must include Tesla $6,411M |
| `x20` | "AMD has the lowest revenue **of the three**" | "**of the four**" |
| `x29` | leaders listed against two others | leaders unchanged; enumeration must include Tesla |
| `w02` | Intel > NVIDIA > AMD | leader unchanged; **Tesla 137,806 slots third** |

### 🟠 ENUMERATION INCOMPLETE — the verdict holds, the list does not

`d01` (Intel still leads R&D share at 26.1%; Tesla joins as the **lowest** at 6.8%) ·
`d03` (add Tesla **4.0%**; the highest-to-lowest gap stays **56.1pp**, NVIDIA to Intel) ·
`d04` (add Tesla **39.9%**; AMD still lowest at 18.1%) ·
`r01` (NVIDIA still the only one generating less cash than net income — Tesla's $14,747M
comfortably exceeds its $3,855M)

### 🔴 `r03` — the question itself breaks, and this is the interesting one

> *"For which company does reported net income depend on whether non-controlling interests
> are included?"*

Today the answer is Intel, uniquely. With Tesla in the corpus it is true of **two** companies:

```
Intel   incl NCI     26   attributable   (267)   diff  293   sign FLIPS
Tesla   incl NCI  3,855   attributable   3,794   diff   61   sign does not flip
```

So the question now has two defensible answers and the reference names one. Under this
project's standing rule — **fix the question, never lower the reference** — the fix is to
tighten the question to what it was always actually testing: *for which company does the
**sign** of reported net income depend on it?* That stays uniquely Intel, and it is a sharper
question than the one it replaces.

### ✅ VERIFIED SAFE — checked, not assumed

`q15` `q22` `p01` (NVIDIA-only) · `x06`–`x13`, `x17` (name both companies explicitly) ·
`x21` (highest gross margin is still NVIDIA at 71.1%; Tesla's 18.0% is nowhere near) ·
`x24` (highest revenue NVIDIA vs lowest revenue AMD — Tesla is neither; 13.3× holds) ·
`x30` (income tax **benefit** is still uniquely AMD; Tesla booked a $1,423M **expense**) ·
`r02` (operating loss with positive pre-tax income is still uniquely Intel; Tesla's income
from operations is **+$4,355M**) ·
`p02` (two companies sharing a fiscal year end is still exactly Intel and AMD on 27 December —
**Tesla's 31 December does not collide**, which is the specific thing this document promised
to check rather than assume)

### 🟡 Loose wording, worth noting but not blocking

`x26` and `x28` say *"the other chipmaker in these filings"*. That phrase was already loose
with three chipmakers in the corpus and Tesla does not make it worse — Tesla is not a
chipmaker. Recorded here so the looseness is a known thing rather than a surprise later.

---

## What this costs, and in what order

1. `corpus.py` — one dict. **Rs 0.**
2. Delete `chroma_db/`, rebuild. **~Rs 9** (≈670,000 tokens at $0.15/1M).
3. Apply the 12 + 4 + 1 reference edits above, and add Tesla questions so the sixth company is
   actually measured rather than merely indexed. **Rs 0.**
4. Free suite. **Rs 0.**
5. Full gate. **~Rs 21** — this is a legitimate gate under the cost rule.

Cached Tesla refusals need no attention: the index fingerprint is part of the cache key, so a
rebuild makes every one of them unreachable on its own.

---
---

# What actually happened

Written after the gate, against the predictions above. Kept in one file on purpose: a document
that only records the parts that came true is not a record, it is an advertisement.

## The gate

| | 6.4 gate | **6.8 gate** |
|---|---|---|
| regression | 40/40 correct, 40/40 grounded | **40/40, 40/40 — unmoved** |
| capability | 54/54, 54/54 | **52/54**, 54/54 |
| Tesla (new) | — | **8/8, 8/8** |
| byte-identical answers vs 6.4 | — | **50/94** |
| correctness verdict changes | — | **`d08`, `x27` — and nothing else** |
| groundedness verdict changes | — | **none** |
| cost | $0.2317 | **$0.2467** (≈ Rs 22; ≈ Rs 21 was quoted, the extra is the 8 new items) |

50/94 needs its scale: two gates on an **unchanged** corpus matched 93/94, and a noisier pair
matched 33/94. Fifty sits between them, which is what a changed corpus should produce. The
part that matters is that only two SCORED results moved.

`ts04` — the attractive nuisance, "what share of Tesla's revenue came from its Data Center
segment" — returned `Not stated in the filing.` It did not take the bait of seven "data
centers" mentions.

## Predictions that held

Every reference change listed above scored as intended. `p02` survived, as promised rather
than assumed — Tesla's 31 December does not collide with Intel's and AMD's 27 December.
`x30` stayed uniquely AMD's. `r02` stayed uniquely Intel's. The retrieval probe predicted the
gate: 15/15 before spending a rupee, and regression came back untouched.

## 🔴 The prediction that was WRONG, and it is the most interesting result here

`x27` was predicted to change answer to Tesla and be scored correct. It changed answer and was
scored **wrong**, and the reason is not the one this document assumed.

The system replied:

> Tesla (fiscal year 2025): **Not stated as a single percentage for the entire company**
> (Automotive segment gross margin is 16.2% and Energy generation and storage segment gross
> margin is 29.8%)

...and therefore picked Intel. But Tesla's MD&A prints, in the SAME TABLE the system was
quoting from and inside the SAME CHUNK:

```
Gross margin total automotive & services and other segment  | 16.2 %     <- it read this
Gross margin energy generation and storage segment          | 29.8 %     <- and this
Total gross profit                                          | $17,094
Total gross margin                                          | 18.0 %     <- and stopped here
```

It read two rows, stopped one row short of the total, and then made a **positive claim of
absence about a document it had in front of it**. That is a different and worse failure than
"could not derive the ratio", which is what this document first assumed and had to retract.

And it exposes something about the eval itself: `x27` passed three previous gates because
**every company in the corpus printed its own gross margin**. A question that appeared to test
multi-hop derivation was testing reading. Only a sixth filing could reveal that, and Tesla
revealed it by printing the figure one row further down than the system was willing to look.

## `d08` — the same defect family, second independent appearance

Four revenue figures listed correctly, then summed to **$397,857M** against a true
**$398,257M** — off by exactly 400. In the 6.4 gate the same question with three addends
summed correctly to 303,430. One more term is the only difference.

This is the `d04` family already on record: intermediate arithmetic wrong, headline verdict
survives. AMD's share came out 8.7% either way, so only the explicit sum exposed it. Two
independent appearances make it a pattern rather than an item, and it is now owed a fix that
is not a prompt tweak.

## Two defects introduced by this phase, both mine

**1. Question-id collision.** `tesla_set.py` shipped with ids `t01`–`t08`. `cross_set.py`
already used `t01`–`t03`, where `t` means TREND. Scoring was unaffected — each set runs its
own list and all 102 rows are present — but `--ids t01` became ambiguous, and the first
gate-comparison keyed on id silently merged rows from different questions. Renamed to
`ts01`–`ts08`; a cross-set uniqueness check now lives in `tesla_set.py` AND in `run_eval.py`,
which is where the ambiguity would actually be resolved. Same shape as `corpus_facts.py`
reading two sets when there were three: **a check is only as wide as what it looks at.**

**2. A false statement in my own gate report.** I reported "regression generation tokens fell
14.2%" by subtracting one run's median from another's. Paired per-question, the median
regression question moved **−30 tokens**, and capability context **grew** (+978 chars mean),
which is what a sixth filing should do. Median-of-medians moves when a handful of items cross
the middle; it is not a per-question effect and must not be reported as one. Third reporting
defect in this project, all three caught by reading output rather than by any test.
