# judge_groundedness.py
# Phase 4.5.3 - the groundedness judge has never been tested, and both of the calibration
# set's disagreements live in it.
#
# It could not be tested before because re-judging groundedness needs the EXACT context the
# answer was written from, and no run stored it. run_eval.py now does, so this whole file
# costs a handful of judge calls and no agent time at all.
#
# Three things are measured, in order of how much they matter:
#
#   A. MUTATION - inject a claim the context cannot support and see whether it is caught.
#      This is the judge's entire job. Ground truth is certain because we wrote the claim.
#        unsupported_add   append a sentence about something no filing mentions
#        number_invent     replace a real figure with one absent from the context
#        entity_swap       attach a real figure to the wrong company
#      Every one must score 0.
#
#   B. PHRASING - the same unsupported claim, stated bluntly and stated softly. The binary
#      correctness judge splits on wording; the groundedness judge is a different prompt and
#      has never been checked for the same weakness.
#
#   C. THE TWO DISAGREEMENTS - d04 and r01, where the judge said grounded and the human label
#      said not. Both are STRUCTURAL claims: a figure given the wrong label, and a heading its
#      own entries contradict. Part A tells us whether the judge is blind to that whole class
#      or merely missed it at this strength, by re-testing the same defect made explicit.
#
# Every injected figure is verified ABSENT from the context before it is used, and every
# find-string is verified present. A mutation that silently fails to apply looks exactly
# like a judge success.

import json
import re
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from judges import groundedness_judge
from golden_set import GOLDEN_SET
from cross_set import CROSS_SET

load_dotenv()

EX = {e["id"]: e for e in list(GOLDEN_SET) + list(CROSS_SET)}
RUN = {}
for line in open("eval_45_ctx.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if "error" not in r:
        RUN[r["id"]] = r

assert all("context" in r for r in RUN.values()), \
    "this run has no stored context - re-run run_eval.py, it persists context now"


# --- A. claims the context cannot support ------------------------------------
# (id, kind, sentence appended to the real answer). All expect grounded = 0.
APPENDS = [
    ("x28", "unsupported_add",
     " This makes AMD the smallest chipmaker by assets among all publicly traded "
     "semiconductor companies worldwide."),
    ("r03", "unsupported_add",
     " Intel's auditors flagged this attribution as a material weakness in internal "
     "controls."),
    ("x10", "unsupported_add",
     " Analysts expect NVIDIA's Data Center revenue to double again next year."),
    # Same unsupported claim, blunt vs hedged. Both must score 0; a split means the
    # groundedness judge has the phrasing weakness the correctness judge has.
    ("w02", "phrasing_blunt",
     " Intel therefore holds the largest asset base in the global chip industry."),
    ("w02", "phrasing_hedged",
     " This would appear to suggest that Intel may well hold the largest asset base in "
     "the global chip industry, although the filings do not elaborate."),
]

# (id, kind, find, replace). Three of these were repaired by the pre-flight guard below
# BEFORE any call was made, and each repair is the same lesson: a mutation that silently
# fails to apply, or that turns out to be TRUE, scores as a judge success.
#   - "293" -> "329" was rejected because "329" already appears inside another figure in
#     r03's context, so the "invented" number was findable. Replaced with a verified-absent
#     value.
#   - the entity_swap find-string did not match the real answer, which puts the company name
#     in bold markdown ("**AMD's** total assets").
#   - the guard ITSELF was wrong for entity_swap: it demanded the injected digits be absent
#     from the context, but an entity swap keeps a REAL figure and moves it to the wrong
#     company. The figure must be PRESENT; what must be absent is the company. Two different
#     kinds of lie need two different proofs, so the guard now branches on kind.
SWAPS = [
    ("x28", "number_invent", "76,926", "79,626"),
    ("w02", "number_invent", "211,429", "214,129"),
    ("r03", "number_invent", "$293 million", "$3,291 million"),
    # x28 already names Intel with a DIFFERENT asset figure, so this swap is ungrounded AND
    # self-contradictory. x10 names only two companies, so its swap is a pure attribution
    # error with nothing else for the judge to catch it by. Both are here on purpose: if the
    # judge catches x28 and misses x10, it is detecting contradiction, not groundedness.
    ("x28", "entity_swap", "**AMD's** total assets were $76,926",
                           "**Intel's** total assets were $76,926"),
    ("x10", "entity_swap", "**AMD (fiscal year 2025, ended December 27, 2025):** $16,635",
                           "**Intel (fiscal year 2025, ended December 27, 2025):** $16,635"),
]

# Unchanged answers. If a control scores 0 the harness is broken and nothing below counts.
CONTROLS = ["x28", "w02", "r03", "x10"]

# --- C. the two disagreements, and the same defect made explicit -------------
# If the judge catches the explicit version it is a sensitivity problem; if it misses that
# too, it is blind to structural claims and the fix is a rubric, not a threshold.
#
# (id, kind, text, expected, graded). GRADED=False means the item is printed but kept OUT of
# the false-positive rate, because its ground truth is not clean.
#
# d04 is exactly that case, and finding out why is the most useful thing this file did.
# I built it expecting grounded=0: the answer calls $3,345m / $7,546m AMD's total liabilities
# and total assets when they are the "Total liabilities assumed" and "Total assets acquired"
# lines of an acquisition note. But probe_titles.py then showed that the chunk those figures
# came from is headed "AMD Consolidated Balance Sheets - fiscal year 2025" - a title OUR OWN
# parser wrote, from a substring match on "total assets" inside "Total assets acquired".
#
# So relative to the context as written, the claim IS supported, and a groundedness judge
# scoring it 1 is right. The human label of 0 was decided against the FILING. Those are two
# different questions, and scoring the judge against the wrong one would have manufactured a
# defect that does not exist and sent the next phase chasing it. The real defect is upstream
# in parse_filing.table_title, and it is fixed there.
EXPLICIT = [
    ("r01", "structural_explicit",
     "Intel generated LESS cash from operations than its net income: net income was "
     "$1,675 million and net cash provided by operating activities was $11,471 million.",
     0, True),
    ("d04", "mislabel_explicit",
     "AMD's consolidated balance sheet reports total liabilities of $3,345 million and "
     "total assets of $7,546 million, giving a ratio of 44.33%.",
     0, False),
]


def build():
    """Every case is (id, kind, prediction, expected, graded)."""
    cases = []
    for i in CONTROLS:
        cases.append((i, "control", RUN[i]["answer"], 1, True))
    for i, kind, extra in APPENDS:
        cases.append((i, kind, RUN[i]["answer"].rstrip() + extra, 0, True))
    for i, kind, find, repl in SWAPS:
        ans = RUN[i]["answer"]
        # Tables in the stored context carry no thousands separators ("76926", not "76,926"),
        # so every containment check is done on a comma-stripped copy.
        ctx = RUN[i]["context"].replace(",", "")
        assert find in ans, f"{i}/{kind}: {find!r} not in the answer"
        if kind == "number_invent":
            # The lie is the VALUE, so the value must be findable nowhere in the context.
            digits = "".join(ch for ch in repl if ch.isdigit())
            assert digits, f"{i}/{kind}: replacement has no digits to check"
            assert digits not in ctx, \
                f"{i}/{kind}: injected digits {digits!r} ARE in the context - pick another"
        elif kind == "entity_swap":
            # Take the money amount, not every digit in the string: an entity_swap
            # replacement carries a date too, and "December 27, 2025 ... $16,635" collapses
            # into one nonsense number that is of course absent from the context. That is a
            # guard that always passes, which is a guard that tests nothing.
            money = re.findall(r"\$\s*([\d,]+)", repl)
            assert money, f"{i}/{kind}: no $ amount found in the replacement"
            digits = money[-1].replace(",", "")
            # The lie is the ATTRIBUTION, so the value must be present and the company we
            # attach it to must appear nowhere near it. \b matters: a plain substring test
            # sees "Intel" inside "Artificial Intelligence" and rejects a valid mutation.
            hits = [m.start() for m in re.finditer(re.escape(digits), ctx)]
            assert hits, f"{i}/{kind}: figure {digits!r} is not in the context at all"
            who = re.search(r"\*\*([A-Za-z]+)", repl).group(1)
            for h in hits:
                window = ctx[max(0, h - 900):h + 300]
                assert not re.search(rf"\b{who}\b", window), \
                    f"{i}/{kind}: the context DOES put {who} near {digits} - not a lie"
        else:
            raise AssertionError(f"{i}: unguarded mutation kind {kind!r}")
        cases.append((i, kind, ans.replace(find, repl), 0, True))
    for i, kind, text, expected, graded in EXPLICIT:
        cases.append((i, kind, text, expected, graded))
    return cases


def judge_one(case):
    i, kind, prediction, expected, graded = case
    v = groundedness_judge(question=EX[i]["question"], prediction=prediction,
                           context=RUN[i]["context"])
    return i, kind, expected, v["score"], v.get("reasoning", ""), graded


if __name__ == "__main__":
    cases = build()
    print(f"\n{'=' * 84}\nGROUNDEDNESS JUDGE - {len(cases)} calls, no agent\n{'=' * 84}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(judge_one, cases))

    by_kind = {}
    print(f"\n  {'id':5} {'mutation':22} {'want':>4} {'got':>4}  verdict")
    for i, kind, want, got, why, graded in results:
        ok = got == want
        if graded:
            by_kind.setdefault(kind, [0, 0])
            by_kind[kind][1] += 1
            by_kind[kind][0] += ok
        mark = ("ok" if ok else "JUDGE MISSED IT") if graded else "not scored - see EXPLICIT"
        print(f"  {i:5} {kind:22} {want:>4} {got:>4}  {mark}")
        if not ok or not graded:
            print(f"        said: {str(why)[:170]}")

    print("\n  by kind:")
    for k, (ok, tot) in sorted(by_kind.items()):
        print(f"    {k:22} {ok}/{tot}")

    scored = [r for r in results if r[5]]
    ctrl = [r for r in scored if r[1] == "control"]
    muts = [r for r in scored if r[1] != "control"]
    ctrl_ok = sum(1 for _i, _k, e, g, _w, _s in ctrl if g == e)
    caught = sum(1 for _i, _k, e, g, _w, _s in muts if g == e)
    print(f"\n  controls passed     {ctrl_ok}/{len(ctrl)}"
          + ("" if ctrl_ok == len(ctrl) else "   <-- HARNESS BROKEN, ignore the rest"))
    print(f"  injected claims caught {caught}/{len(muts)} = {caught / len(muts):.0%}")
    print(f"  FALSE POSITIVE RATE    {(len(muts) - caught) / len(muts):.0%}")
    print(f"  ({len(results) - len(scored)} item(s) printed but not scored - their ground "
          f"truth is not clean)")

    ph = {k: g for _i, k, _e, g, _w, _s in results if k.startswith("phrasing_")}
    if len(ph) == 2:
        print(f"\n  phrasing pair: blunt={ph['phrasing_blunt']}  hedged={ph['phrasing_hedged']}"
              + ("   SPLIT - same claim, different verdict"
                 if ph["phrasing_blunt"] != ph["phrasing_hedged"] else "   consistent"))
