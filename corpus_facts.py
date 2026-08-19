# corpus_facts.py
# Phase 6.4 - one place that knows which figures this repo has actually verified, and a
# mechanical check that nobody retypes one from memory.
#
# WHY THIS EXISTS. Writing the history-injection family and the rewrite set, I typed eleven
# financial figures into test data. Three were wrong:
#
#     Intel FY2025 revenue        I wrote 53,101      verified 52,853
#     AMD FY2025 gross margin     I wrote 49.4%       verified 50%
#     NVIDIA FY2026 net income    I wrote 109,431     verified 120,067
#
# The last one was a scored assertion, so `hist06` - the CONTROL item, the one with no attack
# in it - came back DEGRADED against a perfectly correct answer. A control that fails for a
# reason the control invented is worse than no control: it would have sent the next hour
# hunting a defect in the agent.
#
# The figures were already in this repo, verified against the filings, in golden_set.py and
# cross_set.py. I retyped them anyway. That is a SECOND SOURCE OF TRUTH for a fact the repo
# already owns - the exact defect Phase 4.3 removed from PLAN_PROMPT, reappearing in test
# data where nobody was looking for it.
#
# So: import, do not retype. And where a figure must appear inline for readability, this
# module's check() fails the file's self-test if that figure is not in the verified sets.
# Free - no model, no network.

import json
import re

from cross_set import CROSS_SET
from golden_set import GOLDEN_SET
# Phase 6.8. The verified sets are now THREE. This import is not optional bookkeeping: without
# it, every Tesla figure - 54,941 total liabilities, 134,785 employees - reads as unverified,
# and unverified() would flag a correct figure while staying silent about a wrong one. The
# check is only as wide as the sources it reads.
from tesla_set import TESLA_SET

# Every figure-shaped token in the two verified sets, taken from the DATA rather than by
# reading the source files, so a comment cannot accidentally verify a number.
_FIGURE_RE = re.compile(r"\d[\d,]*\.?\d*")


def _verified_tokens():
    blob = json.dumps([GOLDEN_SET, CROSS_SET, TESLA_SET], ensure_ascii=False)
    return {m.group(0) for m in _FIGURE_RE.finditer(blob)}


VERIFIED = _verified_tokens()


def is_verified(figure):
    """True if this exact figure token appears somewhere in the verified eval sets."""
    return str(figure) in VERIFIED


def unverified(text, allow=()):
    """Return the money-shaped figures in `text` that this repo has never verified.

    Only figures that LOOK like financial magnitudes are checked - four digits or more with a
    thousands separator, or a percentage. Bare small integers (years, counts, ids, "6 turns")
    are skipped, because flagging them would make the check so noisy nobody would run it, and
    a check nobody runs is not a check.

    `allow` is for figures a file contains ON PURPOSE and which must NOT be real: the poison
    payload 999,999, the canary, a deliberately wrong mutation. Passing them explicitly means
    a fake figure is a declared decision rather than an oversight.
    """
    allowed = {str(a) for a in allow}
    found = set()
    for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{1,3}\.\d\s?%", text):
        tok = m.group(0).replace("%", "").strip()
        if tok in allowed or tok in VERIFIED:
            continue
        found.add(tok)
    return sorted(found)


if __name__ == "__main__":
    ok = 0
    # the three I got wrong must be reported as unverified, and their real values accepted
    assert not is_verified("109,431") and is_verified("120,067")
    assert not is_verified("53,101") and is_verified("52,853")
    ok += 1

    assert unverified("revenue was $215,938 million") == []
    assert unverified("net income was $109,431 million") == ["109,431"]
    assert unverified("the payload is $999,999 million", allow=["999,999"]) == []
    ok += 1

    # years and small counts must not be flagged, or the check becomes noise
    assert unverified("in fiscal year 2026 across 6 turns and 22 items") == []
    ok += 1

    # Phase 6.8: the sixth filing's figures must be reachable through this module, or the
    # check silently stops covering a whole company. Named explicitly rather than counted,
    # because a total going up proves nothing about WHICH figures went in.
    for fig in ("94,827", "54,941", "134,785", "3,794", "14,747", "6,411", "17,094"):
        assert is_verified(fig), f"Tesla figure {fig} is not reachable - is TESLA_SET imported?"
    assert unverified("Tesla's total liabilities were $54,941 million") == []
    ok += 1

    print(f"corpus_facts.py: {len(VERIFIED):,} verified figure tokens across three sets, "
          f"{ok}/{ok} checks passed, $0.00 spent")
