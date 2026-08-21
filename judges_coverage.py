# judges_coverage.py
# A SET-COVERAGE judge, built BESIDE judges.py and judges_scope.py - both stay byte-identical.
# Third time this project has added a judge rather than replaced one, and the reason has not
# changed: nothing has to be retired in order to find out whether the new thing is any good.
#
# ================================================================================================
# WHY THIS EXISTS, and it is a hole in the MEASUREMENT, not in the agent.
# ================================================================================================
#
# The 6.10 gate scored `x27` grounded on every scoreboard - binary 54/54, scope 54/54, and their
# strict AND 54/54, with zero disagreements. Here is the answer they passed:
#
#     AMD (FY2025):    50%
#     Intel (FY2025):  34.8%
#     NVIDIA (FY2026): 71.1%
#     Tesla (FY2025):  Not stated as a single percentage for the entire company
#                      (Automotive segment gross margin is 16.2% ...)
#     Comparing the stated gross margins, Intel has the lowest gross margin at 34.8%.
#
# It printed 16.2%, which is lower than the 34.8% it then crowned. When one member of the
# comparison went missing, it DROPPED THAT MEMBER and answered the superlative as though the
# set were complete.
#
# Every sentence in it is traceable to the context, so both existing judges pass it. They ask
# "is this claim supported?" Neither can ask "was the set you compared over complete?" Only the
# correctness judge caught it, and only because a human had written a reference answer.
#
# ================================================================================================
# THE SURFACE AREA, measured before this file was written (probe_setgap.py, free)
# ================================================================================================
#
#   30 of 102 gate questions rank, select or aggregate over a set - the population at risk.
#   1  matched x27's shape exactly (admitted the gap, ranked anyway).
#   2  more - x20 and x21 - assert a superlative over FOUR companies while never naming two of
#      them, with Intel and Tesla both sitting in the context they were handed.
#
# x20 and x21 are the reason this judge is worth building, and they are also why it is NOT
# ANDed into groundedness. Both are CORRECT: AMD really does have the lowest revenue of the
# four, NVIDIA really does have the highest gross margin. They are correct the way x27 was
# correct for three gates - by luck of which companies happen to be in the corpus. Add a fifth
# filing with revenue below AMD's and x20 silently becomes wrong, with nothing in this repo
# able to see it.
#
# ================================================================================================
# WHAT THIS JUDGE IS AND IS NOT
# ================================================================================================
#
# It is a SEPARATE SCOREBOARD, reported beside correctness and groundedness and never averaged
# with them, exactly as the Phase 4.5 scoreboards are. It is NOT part of any AND, so it cannot
# move a single historical number in the tracker - which is the whole reason this shape was
# chosen over folding it into groundedness.
#
# It answers one question: DID THE ANSWER DEMONSTRATE COVERAGE OF THE SET IT RANKED OVER?
# Not whether the ranking is right (that is correctness), not whether the figures are supported
# (that is groundedness). An answer can score 1 here and still be wrong, and that is correct
# behaviour - three judges, three questions, no averaging.
#
# THE HONEST BEHAVIOUR IT REWARDS. An answer that says "Tesla's company-wide gross margin is not
# stated, so I cannot say which company is lowest" scores 1. Declining to rank an incomplete set
# is the right output, and a judge that punished every mention of a gap would push the system
# toward exactly the confident guess it is meant to discourage. That case is a labelled control
# in judge_coverage_suite.py, because a rule nobody tested in the rewarding direction is a rule
# that only knows how to punish.

import re

from pydantic import BaseModel, Field

from judges import log_cost, to_text
from rag import llm

BASE_LLM = getattr(llm, "bound", llm)          # unwrap the retry policy, as agent.py does


class CoverageReport(BaseModel):
    """Observations only. The score is not asked for and must not be inferable from this."""

    requires_ranking: bool = Field(
        description="Does the QUESTION ask for a superlative ('the lowest', 'the highest'), a "
                    "ranking, a selection among entities ('which company...'), or an aggregate "
                    "over several entities ('the combined revenue of all')? A question about a "
                    "single named entity is False.")

    set_in_the_question: str = Field(
        description="The set of entities the QUESTION ranges over, in the question's own words "
                    "- e.g. 'NVIDIA and AMD', 'the companies in these filings', 'all the "
                    "companies'. Empty string if requires_ranking is False.")

    members_required: list[str] = Field(
        description="The entities that set actually contains, given the CONTEXT. If the "
                    "question names two companies, list those two and no others, even when the "
                    "context holds more. If the question says 'the companies in these filings' "
                    "or similar, list EVERY company the CONTEXT holds data for. This is the "
                    "denominator: the members that a complete answer would have to account for.")

    members_engaged: list[str] = Field(
        description="Of members_required, the ones the SYSTEM ANSWER actually accounted for: it "
                    "stated the relevant metric for that entity, OR explicitly stated that the "
                    "metric is unavailable for it. Merely mentioning the entity's name "
                    "somewhere, or quoting an unrelated figure for it, does NOT count as "
                    "accounting for it.")

    commits_to_a_selection: bool = Field(
        description="Does the SYSTEM ANSWER actually name a winner, produce a ranking, or state "
                    "an aggregate total? False if it declines - e.g. says it cannot determine "
                    "which is lowest because a figure is missing.")

    acknowledges_a_gap: bool = Field(
        description="Does the SYSTEM ANSWER state anywhere that it could not obtain the metric "
                    "for at least one member of the set?")

    members_called_unavailable: list[str] = Field(
        default_factory=list,
        description="The members the SYSTEM ANSWER said it could not obtain the metric for - "
                    "'not stated', 'not disclosed', 'not broken out'. Empty if there are none.")


class ExclusionFinding(BaseModel):
    """One member, and what the CONTEXT actually offers for it."""
    member: str = Field(description="The entity, named as the answer named it.")
    availability: str = Field(
        description="Exactly one of: 'stated' - the CONTEXT prints this entity's value for the "
                    "metric directly; 'derivable' - the CONTEXT prints the INPUTS and the "
                    "computation is one direct step the context sets up, such as a ratio of two "
                    "lines in the same table; 'absent' - neither.")
    quotes: list[str] = Field(
        default_factory=list,
        description="One entry PER LINE of verbatim text copied character-for-character from "
                    "the CONTEXT. For 'stated', the single line printing the value. For "
                    "'derivable', ONE ENTRY PER INPUT LINE - do not join two lines into one "
                    "string, they are usually not next to each other and a joined string will "
                    "not be found. Every entry is searched for in the CONTEXT and the whole "
                    "claim is DISCARDED if any of them is missing, so copy, never paraphrase, "
                    "never reconstruct from memory. Empty list for 'absent'.")


class ExclusionCheck(BaseModel):
    """The escalation. Asked about the CONTEXT, never about the answer's quality.

    x27 is why this exists, and the FIRST version of this class got x27 right for the wrong
    reason while getting a control wrong outright - so read both before changing it.

    THE SHAPE. Saying a figure is missing COUNTS as accounting for a member, correctly: an
    answer that reports a genuine gap has not dropped anything. What separates honest from
    broken is whether the gap is REAL, and that is a question about the CONTEXT which no
    reading of the answer can settle.

    🔴 WHAT THE FIRST VERSION DID, and it is the reason for the quote field. It returned a bare
    list of members plus a free-text `evidence` string that NOTHING CHECKED. On the suite's
    real-gap control - "Intel's Data Center revenue is not broken out", which is true, there is
    no Intel segment data in that context at all - it reported the figure as present. A
    fabricated presence, from the branch whose entire job is to detect a fabricated absence.
    It also passed x27, which was the label wanted, so the run read as 13/14 with one bad
    control rather than as a judge asserting things about a context it had not found.

    THE REPAIR is the one judges_scope.py parked in Phase 4.5 and never built: the model
    returns a VERBATIM span and CODE checks the span is really in the context. A claim with
    nothing quotable fails. That does not make the model honest - it can still quote a real but
    irrelevant line - but it removes the failure mode that actually occurred.

    'derivable' EXISTS BECAUSE OF WHAT x27'S CONTEXT REALLY HOLDS. Checking it by hand, against
    both the 6.8 and 6.10 gates: Tesla's total gross margin is NOT printed. `Gross profit
    17094` and `Total revenues 94827` are, in the same chunk, and 17094/94827 = 18.0%. The
    answer had already divided 13292/82056 to get the automotive segment's 16.2% one line
    earlier. So x27 did not fail to READ a figure; it declined to perform a division it was
    already performing, called the result unavailable, and ranked without Tesla. Collapsing
    'stated' and 'derivable' into one boolean would hide exactly that distinction - and the
    distinction is the finding.
    """
    findings: list[ExclusionFinding] = Field(
        description="One entry per member you were asked about. Include every one of them, "
                    "including the ones that are genuinely absent.")


EXCLUSION_PROMPT = """You are checking one narrow factual point about a CONTEXT.

An answer to the QUESTION below reported that it could not find the requested metric for these
entities: {suspects}

For each of those entities, decide what the CONTEXT actually offers for THE METRIC THE QUESTION
ASKS ABOUT - not some other metric for the same entity:

  stated     the CONTEXT prints that entity's value for this exact metric
  derivable  the CONTEXT does not print it, but it prints the INPUTS and the computation is one
             direct step the context sets up - a ratio of two lines in the same table, say
  absent     neither

Then copy the VERBATIM text from the CONTEXT that supports what you said, AS A LIST, ONE ENTRY
PER LINE. For 'stated' that is the single line printing the value. For 'derivable' it is one
entry for EACH input line - and those lines are usually not next to each other in the CONTEXT,
so do not join them into one string; a joined string will not be found and the whole claim will
be thrown away.

Each entry is searched for in the CONTEXT character by character. Copy exactly. Do not
paraphrase, do not tidy the spacing, do not reconstruct a line from memory, and do not quote a
line about a DIFFERENT metric - if the metric is a margin, quote the profit and revenue lines,
not whatever line happens to be nearby.

If an entity has no data for this metric in the CONTEXT, say 'absent' and quote nothing. That
is a normal and expected answer - many entities genuinely do not report many things - and
saying so is more useful than a guess.

Do not judge the answer. Do not decide whether it was reasonable to miss the figure.

QUESTION: {question}

CONTEXT:
{context}"""


COVERAGE_PROMPT = """You are auditing an answer produced by a financial question-answering
system, against the CONTEXT it was written from.

Do NOT decide whether the answer is good, correct, complete or supported. Report observations
only. Another program will do the scoring, and it does not tell you its rule.

Step 1. Decide whether the QUESTION asks for a superlative, a ranking, a selection among
entities, or an aggregate across entities. If it asks about one named entity only, set
requires_ranking to false and leave the remaining fields empty. Stop there.

Step 2. Name the set of entities the QUESTION ranges over, using the question's own words.
Be literal, and note that a question may restrict the set on purpose:
  "Whose gross margin was higher, NVIDIA or AMD?"          -> NVIDIA and AMD. Only those two.
  "Among the companies in these filings, which ..."        -> every company in the CONTEXT.
  "Rank all the companies in these filings by revenue"     -> every company in the CONTEXT.
A question that names its entities does NOT range over the whole corpus, no matter how many
companies the CONTEXT happens to hold.

Step 3. List the members that set actually contains, given the CONTEXT. This is the set of
entities a complete answer would have to account for.

Step 4. For each of those members, decide whether the SYSTEM ANSWER ACCOUNTED FOR it. A member
is accounted for if the answer states the relevant metric for it, or explicitly says the metric
is unavailable for it. A member is NOT accounted for if the answer merely names it in passing,
quotes some other figure for it, or never mentions it at all. List only the members that were
accounted for.

Step 5. Say whether the SYSTEM ANSWER actually commits to a winner, a ranking or a total, or
whether it declines to.

Step 6. Say whether the SYSTEM ANSWER states anywhere that it could not obtain the metric for
some member, and list those members. Report what it SAID; whether the figure is really absent
from the CONTEXT is not asked here and is not yours to decide.

Report what the answer DID, not what it should have done.

QUESTION: {question}

CONTEXT:
{context}

SYSTEM ANSWER (being audited): {prediction}"""


# Entity names are compared after normalising, because the model may return "NVIDIA Corporation"
# where the context says "NVIDIA", and a judge that failed an answer over a suffix would be
# measuring string formatting. Decided in CODE for the same reason as _figures_ok in
# judges_scope.py: a mechanical rule cannot forget itself the way a prompt instruction can.
# ============================================================================================
# 🔴 NOT CALIBRATED FOR THE CURRENT ANSWER STYLE. Set 2026-08-20 after the 6.10c gate.
#
# On the 6.10 gate this judge flagged 8 items and, read by hand, ZERO were false positives
# against a pre-registered 25% ceiling. On the 6.10c gate it flagged 7 and THREE were false
# positives - 43%. Nothing about the judge changed. The ANSWERS changed: the arithmetic rule
# asks them to show their working, and they now write things like
#
#   x27  "Not stated as a percentage in the provided tables. HOWEVER, calculating the gross
#         margin (Gross Profit / Total Revenues): 17,094 / 94,827 = 18.03%"
#        -> the judge read "not stated" as an EXCLUSION. The answer included Tesla and named
#           it correctly. The escalation then "confirmed" a gap that was never claimed.
#
#   x22  "AMD did not report a standalone Gaming segment revenue figure FOR FISCAL YEAR 2026"
#        -> true. The escalation found AMD's FY2025 Gaming revenue and called the gap unreal.
#           Right entity, right metric, WRONG PERIOD.
#
#   x24  lists all four revenues, ranks them, then computes a ratio over the two selected
#        -> the judge measured coverage against the RATIO's metric instead of the RANKING's.
#
# One root cause under all three: the escalation checks that an entity's metric exists SOMEWHERE
# in the context, and ignores the QUALIFIER the answer actually attached - "as a percentage",
# "for fiscal year 2026", "for this metric rather than that one".
#
# So the pre-registered rule binds: >25% false positives and this does not ship AS A REPORTED
# SCOREBOARD. It keeps running, because its candidate LIST is still worth reading and a check
# switched off is a check that gets forgotten - but run_eval.py prints no percentage for it
# until it is recalibrated against answers written in the current style.
#
# THE DEEPER POINT, which is lesson 147 for the third time: this judge's 0-false-positive record
# was measured on a corpus of answers that no longer exists. A calibration is a statement about
# INPUTS, and it expires when they change.
# RESOLVED 2026-08-20 by RETIRING THE ESCALATION rather than repairing it, and the decision was
# made from evidence that cost nothing: run_eval.py stores `coverage_report`, so both gates could
# be re-scored offline under the narrowed rule.
#
#   6.10 answers   escalation contributed 1 flag (x27).  The other 7 survive without it,
#                  INCLUDING x20 and x21 - the two cases this judge was built for.
#   6.10c answers  escalation contributed 2 flags. BOTH were false positives.
#
# Lifetime record: one catch, two false alarms - and the one catch is on an answer that no
# longer exists, because x27 is now correct and complete, so not flagging it is right rather
# than a loss. Without the escalation the 6.10c gate flags 5 of 35, one of them false: **20%,
# under the 25% ceiling.**
#
# THE ESCALATION WAS THE AMBITIOUS HALF and it is the half that failed. Its limitation was
# written into ExclusionCheck from the first day - a quote can be real and still irrelevant -
# and what actually broke it was narrower and worse: it checked that an entity's metric exists
# somewhere in the context while ignoring the QUALIFIER the answer attached ("as a percentage",
# "for fiscal 2026"). Under a tight budget the right move is not a cleverer second call; it is
# to keep the part that works and stop paying for the part that impresses.
#
# The code stays, switched off, because the measurement above is only legible next to it.
USE_ESCALATION = False

CALIBRATED = True
CALIBRATION_NOTE = ("escalation retired 2026-08-20; the simple coverage rule scores 5 flags of "
                    "35 applicable on the 6.10c gate, 1 false positive = 20%, under the 25% "
                    "pre-registered ceiling")


def observation_fingerprint():
    """A hash of everything that shapes a stored observation: the prompt and the schema.

    So that "the main prompt did not change, therefore the 102 stored observations are still
    valid and no re-run is owed" stops being something I remember and becomes something a run
    can check. It covers COVERAGE_PROMPT and CoverageReport ONLY - deliberately not the
    escalation, which is a separate call whose result is stored separately, and not the scoring
    rule, which is re-appliable for free with --rescore.
    """
    import hashlib
    import json as _json
    blob = COVERAGE_PROMPT + _json.dumps(CoverageReport.model_json_schema(), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_NORM = re.compile(r"[^a-z0-9]+")
_SUFFIX = re.compile(r"\b(corporation|corp|incorporated|inc|technologies|technology|ltd|"
                     r"limited|plc|company|co|holdings|group)\b")


def _key(name):
    n = _SUFFIX.sub(" ", (name or "").lower())
    return _NORM.sub("", n)


def verdict_from(v, false_exclusions=None):
    """THE SCORING RULE. Takes a CoverageReport, returns the result dict. No model in here.

    false_exclusions is the escalation's answer: members the answer called unavailable whose
    metric IS in the context. None means "not asked yet"; the caller is told to ask via
    needs_escalation in the returned dict.

    Deliberately a separate function from coverage_judge, and the self-test at the bottom calls
    THIS rather than re-implementing the branches. `search_filings` hand-rolled a second copy of
    a rule that already existed in agent.py and got it wrong (lesson 143); a self-test that
    re-implements the rule it is testing is the same mistake with a worse consequence, because
    it would pass while the shipped rule was broken.

    Two other properties this shape buys, both of which have mattered before in this project:
    stored observations can be re-scored under a changed rule for $0, the way
    probe_scope_ab.py --recorded does; and the rule is testable with no API key, so the part
    that changes most often is the part that is free to check.

    score is None when the question does not rank over a set. That is NOT a pass: an
    inapplicable item must be EXCLUDED from the denominator, never counted as a success -
    otherwise this scoreboard would rise every time a single-company question was added.
    """
    base = {"applicable": True, "needs_escalation": False,
            "required": list(v.members_required), "engaged": list(v.members_engaged),
            "declined": not v.commits_to_a_selection,
            "acknowledged": v.acknowledges_a_gap,
            "called_unavailable": list(v.members_called_unavailable),
            "false_exclusions": list(false_exclusions or []),
            "set_in_the_question": v.set_in_the_question}

    if not v.requires_ranking:
        return {**base, "score": None, "applicable": False, "required": [], "engaged": [],
                "missing": [],
                "reasoning": "question does not rank or aggregate over a set - not applicable"}

    engaged = {_key(m) for m in v.members_engaged}
    missing = [m for m in v.members_required if _key(m) not in engaged]
    base["missing"] = missing

    # An answer that DECLINES to rank scores 1 even with members missing. That is the honest
    # output for an incomplete set, and rewarding it is the point - see the file header. It is
    # also the branch most likely to be wrong in a way nobody notices, so it has its own
    # labelled control in the suite rather than only this comment.
    if not v.commits_to_a_selection:
        return {**base, "score": 1,
                "reasoning": "declined to rank rather than guess"
                             + (f" (missing {', '.join(missing)})" if missing else "")}

    if missing:
        return {**base, "score": 0,
                "reasoning": f"ranked over {len(v.members_required)} but accounted for "
                             f"{len(v.members_required) - len(missing)}; never accounted for "
                             f"{', '.join(missing)} (dropped silently)"}

    # ------------------------------------------------------------------------------------
    # THE BRANCH THE MUTATION SUITE ADDED, and the suite found it by failing x27 - the one
    # case this whole judge was built for.
    #
    # x27 accounted for all four members. It really did: it said Tesla's gross margin was
    # "not stated as a single percentage", and reporting a gap IS accounting for a member.
    # By the field definitions above the model answered correctly and the rule then passed
    # the defect. The spec was wrong, not the model.
    #
    # What x27 actually did was exclude Tesla on a gap THAT WAS NOT REAL - `Total gross
    # margin | 18.0 %` sat in the chunk it was quoting from. And that difference cannot be
    # read off the answer at any price; it is a question about the CONTEXT. So the check
    # escalates: only when an answer committed to a selection AFTER reporting a gap does a
    # second call go and look. On the 102-answer regression that shape occurred ONCE.
    #
    # The direction matters. If the gap is REAL - Tesla genuinely reports no Data Center
    # segment - excluding that member and ranking the rest is correct, and this branch must
    # pass it. That case is a labelled control in the suite, not just a sentence here.
    if USE_ESCALATION and v.acknowledges_a_gap and v.members_called_unavailable:
        if false_exclusions is None:
            return {**base, "score": 1, "needs_escalation": True,
                    "reasoning": "committed to a selection after reporting a gap - the context "
                                 "has not been checked yet, so this score is provisional"}
        if false_exclusions:
            return {**base, "score": 0,
                    "reasoning": f"excluded {', '.join(false_exclusions)} as 'not stated' and "
                                 f"ranked without them - but the CONTEXT does contain the "
                                 f"figure. A selection made over a set narrowed by a gap that "
                                 f"is not real."}
        return {**base, "score": 1,
                "reasoning": f"reported a genuine gap for "
                             f"{', '.join(v.members_called_unavailable)} - the context really "
                             f"does not hold it - and ranked the rest"}

    return {**base, "score": 1,
            "reasoning": f"accounted for all {len(v.members_required)}: "
                         f"{', '.join(v.members_required)}"}


_WS = re.compile(r"\s+")
_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def quote_is_in(quote, context, min_chars=12):
    """Is this span REALLY in the context? Whitespace-insensitive, and it must carry a figure.

    The check the first version of the escalation did not have, and the absence of which let it
    report a figure that is not in the context at all. Three conditions, all mechanical:

      * at least 12 characters once reduced to letters and digits, so a bare number cannot
        match by accident
      * contains a digit - every metric in this corpus is a number, so a quote with no digit
        cannot be evidence that a number is present
      * appears in the context once BOTH are reduced to letters and digits only

    WHY THE COMPARISON IGNORES PUNCTUATION, and it took two paid runs to arrive here. The
    first version required a verbatim span; the model returned two non-adjacent lines joined
    into one string, which cannot be found. The second asked for a LIST of lines; the model
    then returned `Total revenues 94827` for a context line reading
    `Total revenues | 94827 | 97690 | 96773`. It drops the pipes and the comparison columns -
    a compact restatement of a real line, not a fabrication.

    Twice now the instruction has been sharpened and twice the model has reformatted anyway.
    So the instruction stops being the fix. This is the fifth time in this project that a
    MECHANICAL RULE has replaced a reasoning one - the same move as `_figures_ok` in
    judges_scope.py - and the reasoning is the same: a rule cannot forget itself.

    WHAT THE CHECK STILL CATCHES after the loosening, which is the part that matters. The
    LABEL and the VALUE must be adjacent in the context. `Total gross margin 18.0%` reduces to
    `totalgrossmargin180`, and `totalgrossmargin` does not occur anywhere in x27's context, so
    the fabrication that started all this is still rejected. So is a real label with an
    invented number: `Total revenues 99999` is not in the reduced context either. Both are
    labelled cases below.

    It cannot tell a real-but-irrelevant quote from a relevant one - the model may still quote
    a true line about the wrong metric. That limit is real, it is written into the class
    docstring, and it is not fixed here.
    """
    q = _ALNUM.sub("", (quote or "")).lower()
    if len(q) < min_chars or not re.search(r"\d", q):
        return False
    return q in _ALNUM.sub("", context or "").lower()


def _check_exclusions(question, context, suspects):
    """The escalation: is the gap the answer reported actually there in the context?

    Returns (false_exclusions, evidence_lines, rejected) - rejected are the claims whose quote
    could not be found in the context, kept and reported rather than silently dropped, because
    a verifier that hides how often it fires cannot be judged.
    """
    judge = BASE_LLM.with_structured_output(ExclusionCheck, include_raw=True).with_retry(
        stop_after_attempt=3
    )
    result = judge.invoke(EXCLUSION_PROMPT.format(question=to_text(question),
                                                  context=to_text(context),
                                                  suspects=", ".join(suspects)))
    log_cost("gemini-3.1-flash-lite", result["raw"], label="coverage-exclusion")
    v = result["parsed"]
    if v is None:
        raise ValueError(f"exclusion output did not parse: {result.get('parsing_error')}")

    # Only members the answer actually excluded count. A model that helpfully volunteers one
    # nobody asked about would otherwise fail an answer for a claim it never made.
    asked = {_key(s) for s in suspects}
    ctx = to_text(context)

    confirmed, evidence, rejected = [], [], []
    for f in v.findings:
        if _key(f.member) not in asked:
            continue
        if (f.availability or "").strip().lower() not in ("stated", "derivable"):
            continue
        # EVERY quote must verify, not any. A 'derivable' claim rests on all of its inputs; one
        # real line beside one invented one is not evidence that the figure is there.
        bad = [q for q in (f.quotes or []) if not quote_is_in(q, ctx)]
        if f.quotes and not bad:
            confirmed.append(f.member)
            evidence.append(f"{f.member} [{f.availability}]: "
                            + " || ".join(_WS.sub(" ", q)[:80] for q in f.quotes))
        else:
            why = "no quote given" if not f.quotes else \
                  "not found in context: " + " || ".join(_WS.sub(" ", q)[:80] for q in bad)
            rejected.append(f"{f.member} [{f.availability}] claim REJECTED - {why}")
    return confirmed, evidence, rejected


def coverage_judge(question, prediction, context):
    """One model call for the observations, a second ONLY when the first cannot settle it."""
    judge = BASE_LLM.with_structured_output(CoverageReport, include_raw=True).with_retry(
        stop_after_attempt=3
    )
    result = judge.invoke(COVERAGE_PROMPT.format(question=to_text(question),
                                                 context=to_text(context),
                                                 prediction=to_text(prediction)))
    log_cost("gemini-3.1-flash-lite", result["raw"], label="coverage")
    v = result["parsed"]
    if v is None:
        raise ValueError(f"coverage output did not parse: {result.get('parsing_error')}")

    out = verdict_from(v)
    evidence, rejected, did_escalate = [], [], False
    if out["needs_escalation"]:
        did_escalate = True                 # set HERE, not inferred from the result - an
                                            # escalation that found nothing still happened,
                                            # and a counter that only counts hits under-reports
                                            # the cost of the thing it is counting
        false_exclusions, evidence, rejected = _check_exclusions(
            question, context, v.members_called_unavailable)
        out = verdict_from(v, false_exclusions=false_exclusions)
    out["escalated"] = did_escalate
    out["exclusion_evidence"] = evidence
    out["exclusion_rejected"] = rejected    # unverifiable claims, surfaced not swallowed
    out["raw_report"] = v.model_dump()      # so a run can be re-scored later without paying
    return out


# ---- free self-tests: the SCORING RULE only, no model, no API key -------------------------
# The rule is code, so it is testable without paying for anything. What cannot be tested for
# free is whether the model fills the fields correctly - that is judge_coverage_suite.py's job,
# and it costs money. Splitting them means the part that changes most often is the free part.
if __name__ == "__main__":
    def _V(**kw):
        """A hand-built CoverageReport. Built through the real model so that a field renamed
        here fails loudly instead of being silently ignored by a duck-typed stand-in."""
        kw.setdefault("set_in_the_question", "")
        kw.setdefault("members_required", [])
        kw.setdefault("members_engaged", [])
        return CoverageReport(**kw)

    def _score(v, false_exclusions=None):
        return verdict_from(v, false_exclusions)["score"]   # THE SHIPPED RULE, not a copy

    cases = [
        ("single-company question is N/A, not a pass",
         _V(requires_ranking=False, members_required=[], members_engaged=[],
            commits_to_a_selection=False, acknowledges_a_gap=False), None),

        ("x27: four required, three accounted for, ranked anyway",
         _V(requires_ranking=True, members_required=["AMD", "Intel", "NVIDIA", "Tesla"],
            members_engaged=["AMD", "Intel", "NVIDIA"],
            commits_to_a_selection=True, acknowledges_a_gap=True), 0),

        ("x20: four required, two accounted for, silent drop",
         _V(requires_ranking=True, members_required=["AMD", "Intel", "NVIDIA", "Tesla"],
            members_engaged=["AMD", "NVIDIA"],
            commits_to_a_selection=True, acknowledges_a_gap=False), 0),

        ("declining to rank an incomplete set is the HONEST output and must pass",
         _V(requires_ranking=True, members_required=["AMD", "Intel", "NVIDIA", "Tesla"],
            members_engaged=["AMD", "Intel", "NVIDIA"],
            commits_to_a_selection=False, acknowledges_a_gap=True), 1),

        ("a complete ranking passes",
         _V(requires_ranking=True, members_required=["AMD", "Intel", "NVIDIA", "Tesla"],
            members_engaged=["Tesla", "NVIDIA", "Intel", "AMD"],
            commits_to_a_selection=True, acknowledges_a_gap=False), 1),

        ("a question that NAMES two companies is not judged against the whole corpus",
         _V(requires_ranking=True, members_required=["NVIDIA", "AMD"],
            members_engaged=["NVIDIA", "AMD"],
            commits_to_a_selection=True, acknowledges_a_gap=False), 1),

        ("'not stated for one' counts as accounting for it, if the answer then declines",
         _V(requires_ranking=True, members_required=["AMD", "Tesla"],
            members_engaged=["AMD", "Tesla"],
            commits_to_a_selection=True, acknowledges_a_gap=True), 1),

        ("legal-suffix drift must not fail an answer",
         _V(requires_ranking=True, members_required=["NVIDIA Corporation", "Intel Corp"],
            members_engaged=["NVIDIA", "Intel"],
            commits_to_a_selection=True, acknowledges_a_gap=False), 1),

        ("case and punctuation drift must not fail an answer",
         _V(requires_ranking=True, members_required=["Advanced Micro Devices"],
            members_engaged=["advanced micro devices,"],
            commits_to_a_selection=True, acknowledges_a_gap=False), 1),

        ("an empty engaged list with members required is a failure, not a crash",
         _V(requires_ranking=True, members_required=["AMD", "NVIDIA"], members_engaged=[],
            commits_to_a_selection=True, acknowledges_a_gap=False), 0),
    ]

    # ---- the escalation branch, in BOTH directions ---------------------------------------
    # The suite found this branch by failing x27, so it gets its own controls here rather than
    # only in the paid suite: the free test is the one that gets run.
    X27_SHAPE = dict(requires_ranking=True,
                     members_required=["AMD", "Intel", "NVIDIA", "Tesla"],
                     members_engaged=["AMD", "Intel", "NVIDIA", "Tesla"],
                     commits_to_a_selection=True, acknowledges_a_gap=True,
                     members_called_unavailable=["Tesla"])

    # The escalation is RETIRED (USE_ESCALATION = False), so its cases run with the flag
    # forced on - they still describe what that branch does, and they are what a future
    # recalibration would have to keep passing. The retired-path case below is the one that
    # describes SHIPPED behaviour.
    # A PLAIN GLOBAL ASSIGNMENT, not `import judges_coverage as _self; _self.X = True`.
    # The first version did the latter and the flag never took: run as __main__ this file's
    # globals ARE the __main__ namespace, and verdict_from reads that, not the separately
    # imported module object. Two names for one module, and the test set the wrong one.
    USE_ESCALATION = True

    escalation_cases = [
        ("x27 shape, context has not been checked yet -> provisional 1, flagged for escalation",
         _V(**X27_SHAPE), None, 1, True),
        # NOT "18.0% was in the chunk" - it was not, in either gate. The context holds Gross
        # profit 17094 and Total revenues 94827 in the same table, so the figure is DERIVABLE
        # in one step, and the answer was already dividing to get segment margins.
        ("x27 shape, Tesla's margin derivable from the same table -> the exclusion was false",
         _V(**X27_SHAPE), ["Tesla"], 0, False),
        ("same shape, but the gap is REAL (no Data Center segment) -> ranking the rest is fine",
         _V(**X27_SHAPE), [], 1, False),
        ("a gap reported but NO member named -> nothing to escalate, ordinary pass",
         _V(requires_ranking=True, members_required=["AMD", "NVIDIA"],
            members_engaged=["AMD", "NVIDIA"], commits_to_a_selection=True,
            acknowledges_a_gap=True, members_called_unavailable=[]), None, 1, False),
        ("declining still wins over everything, even with a false exclusion",
         _V(**{**X27_SHAPE, "commits_to_a_selection": False}), ["Tesla"], 1, False),
    ]

    # ---- the quote verifier, which is the whole defence against a fabricated presence ------
    CTX = ("Tesla Consolidated Statements of Income - fiscal year 2025, in millions:\n"
           "Total revenues | 94827 | 97690 | 96773\n"
           "Gross profit | 17094 | 17450 | 17660\n"
           "Research and development | 6411 | 4540 | 3969\n")
    quote_cases = [
        ("a real line verifies", "Gross profit | 17094 | 17450 | 17660", True),
        ("whitespace differences are fine - tables arrive irregularly spaced",
         "Gross profit |   17094 |17450 | 17660", True),
        ("case differences are fine", "gross PROFIT | 17094 | 17450 | 17660", True),
        # what the model ACTUALLY returns: the label, the value, no pipes, no other columns
        ("a compact restatement of a real line verifies - this is what the model returns",
         "Total revenues 94827", True),
        ("...and so does the other input of the derivation",
         "Gross profit 17094", True),
        ("🔴 a fabricated line is REJECTED - the failure that actually happened",
         "Total gross margin | 18.0 %", False),
        ("🔴 a REAL label with an INVENTED number is REJECTED",
         "Total revenues 99999", False),
        ("a plausible line for a company with no such data is REJECTED",
         "Intel Data Center revenue | 12345", False),
        ("a quote with no digit cannot evidence a figure",
         "Consolidated Statements of Income - fiscal year", False),
        ("too short to be a quote", "17094", False),
        ("empty", "", False),
    ]

    ok = 0
    print("\n  judges_coverage.py - the QUOTE VERIFIER, no model\n")
    for name, quote, expected in quote_cases:
        got = quote_is_in(quote, CTX)
        good = got == expected
        ok += good
        print(f"  [{'ok  ' if good else 'FAIL'}] got={got!s:5} expected={expected!s:5}  {name}")

    print("\n  judges_coverage.py - the SCORING RULE, tested without a model\n")
    for name, v, expected in cases:
        got = _score(v)
        flag = "ok  " if got == expected else "FAIL"
        ok += got == expected
        print(f"  [{flag}] got={str(got):4} expected={str(expected):4}  {name}")

    print()
    for name, v, fx, expected, want_escalation in escalation_cases:
        out = verdict_from(v, fx)
        good = out["score"] == expected and out["needs_escalation"] == want_escalation
        ok += good
        print(f"  [{'ok  ' if good else 'FAIL'}] got={str(out['score']):4} "
              f"expected={str(expected):4}  esc={out['needs_escalation']!s:5}  {name}")
    # --- SHIPPED behaviour: the escalation is off, so x27's shape scores 1 -----------------
    # x27's 6.10c answer says "not stated as a percentage... however, calculating... 18.03%"
    # and names Tesla correctly. It did not exclude anything. With the escalation retired the
    # judge stays out of it, which is the whole point of the retirement.
    USE_ESCALATION = False
    retired = verdict_from(_V(**X27_SHAPE))
    good = retired["score"] == 1 and retired["needs_escalation"] is False
    ok += good
    print(f"\n  [{'ok  ' if good else 'FAIL'}] got={retired['score']} expected=1  "
          f"esc={retired['needs_escalation']}  SHIPPED: escalation retired, a reported gap on "
          f"an accounted-for member is not an exclusion")

    cases = cases + escalation_cases + quote_cases + [("shipped retired-path", None, None)]
    print(f"\n  {ok}/{len(cases)} checks passed (quote verifier + scoring rule). "
          f"No model was called.")
    print("  Whether the MODEL fills these fields correctly is judge_coverage_suite.py's job,")
    print("  and that one costs money. The rule is free to test, so it is tested separately.")
    raise SystemExit(0 if ok == len(cases) else 1)
