# judges_scope.py
# A scope-aware groundedness judge, built BESIDE judges.py - that file stays byte-identical.
# Same rule as judges_rubric.py, and the same reason: nothing has to be replaced in order to
# find out whether the replacement is better.
#
# WHY THIS EXISTS, measured rather than assumed.
#
# judge_groundedness.py gave the existing judge its first test: 16 calls, controls 4/4,
# invented figures 3/3, wrong-company attribution 2/2, unsupported additions 3/3,
# self-contradiction 1/1 - and 0/2 on one claim appended to w02's answer:
#
#     "Intel therefore holds the largest asset base in the global chip industry."
#
# Three companies in the context. A statement about an industry. Scored grounded, twice.
# Its reasoning says exactly what it did:
#
#     "All figures for total assets and net revenue for the three companies are correctly
#      extracted from the provided financial statements"
#
# It audited the NUMBERS and never read the SENTENCE. Every figure traceable, the claim still
# unsupported. That is a SCOPE error, not a factual one.
#
# probe_gscope.py then separated the two candidate causes with a 2x2 and a length ladder:
#
#                   hard quantifier   soft quantifier
#     SHORT ctx           0                 1
#     LONG  ctx           0                 1
#
#     ladder 1.0x .. 2.6x (16,605 -> 43,175 chars): mutated 0 at every rung, control 1 at
#     every rung.
#
# A clean COLUMN effect. Context length is not the mechanism - the hard claim survives a
# context 2.6x its own size, well past the one it failed on. What decides the verdict is how
# BLUNTLY the over-generalisation is worded: "among ALL publicly traded semiconductor
# companies WORLDWIDE" is caught, "in the global chip industry" is not. Which is the worst
# possible shape for a defect, because real answers generalise softly.
#
# THE FIX, and it is the pattern that has now worked twice in this project:
#   ask the model for OBSERVATIONS, compute the VERDICT in code.
#
# The old prompt asks one fused question - "is every claim supported?" - and the model
# discharges it by checking figures, because figures are the checkable part. This one never
# asks whether anything is supported. For each claim it asks a question with a determinate
# answer: WHAT SET does this claim range over, and does the context hold data for every
# member of that set? "The global chip industry" ranges over every chip company; the context
# has three. That comparison is hard to wave through, and code does the ruling.

import re

from pydantic import BaseModel, Field

from judges import log_cost, to_text
from rag import llm

BASE_LLM = getattr(llm, "bound", llm)          # unwrap the retry policy, as agent.py does


class Claim(BaseModel):
    """One assertion made by the answer, described - never scored."""
    claim: str = Field(description="The assertion, quoted from the SYSTEM ANSWER")
    ranges_over: str = Field(description="The set of entities this claim speaks about, in the "
                                         "answer's own terms - e.g. 'NVIDIA in FY2026', "
                                         "'the three companies named', 'every publicly "
                                         "traded semiconductor company'")
    context_covers_that_whole_set: bool = Field(
        description="Does the CONTEXT contain data for EVERY member of that set? A claim "
                    "about three named companies needs those three. A claim about an "
                    "industry, a market, or 'all companies' needs every company in it - "
                    "which a context of a few filings does NOT have.")
    input_figures_in_context: bool = Field(
        description="Are the numbers this claim rests on present in the CONTEXT? For a "
                    "computed value, the INPUTS must be present; the computed value itself "
                    "need not be, and whether the arithmetic is right is not your concern.")
    asserts_absence: bool = Field(
        description="Is the claim itself that the context does NOT contain something - a "
                    "refusal, 'not stated', 'cannot be calculated'? Such a claim makes no "
                    "factual assertion about the world.")


class ScopeVerdict(BaseModel):
    """Observations only. The score is not asked for and must not be inferred from this."""
    claims: list[Claim] = Field(description="One entry per distinct assertion in the "
                                            "SYSTEM ANSWER")


SCOPE_PROMPT = """You are auditing an answer produced by a financial question-answering system,
against the CONTEXT it was written from.

Do NOT decide whether the answer is good, correct, or supported. Report observations only.

Step 1. List every distinct assertion the SYSTEM ANSWER makes. Include the summarising or
concluding sentences, not only the ones containing numbers - a sentence with no figures in it
is still an assertion.

Step 2. For each assertion, name the SET OF ENTITIES it speaks about. Be literal about the
words used:
  "NVIDIA's revenue was X"                     -> NVIDIA
  "AMD is smaller than Intel"                  -> AMD and Intel
  "the largest of the three companies"         -> the three companies named
  "the largest in the global chip industry"    -> every company in the global chip industry
  "the smallest among all listed chipmakers"   -> every listed chipmaker
An answer may quietly widen its scope in a closing sentence. Report the scope of the words as
written, not the scope you think was meant.

Step 3. For each assertion, say whether the CONTEXT holds data for EVERY member of that set.
The CONTEXT is a handful of filings from named companies. It can cover those companies. It
cannot cover an industry, a market, a sector, or "all companies" - no matter how confidently
or how gently the answer says so.

Step 4. For each assertion, say whether the numbers it rests on appear in the CONTEXT.
Arithmetic on context numbers is fine: for a difference, sum, ratio, percentage or growth
rate, only the INPUTS need to be present. Do not check whether the arithmetic is correct.

Step 5. Mark an assertion that merely reports something is MISSING from the context
(a refusal, "not stated", "cannot be calculated") with asserts_absence.

Judge the CONTENT and its SCOPE. Never the wording, length, tone or confidence.

QUESTION: {question}

CONTEXT:
{context}

SYSTEM ANSWER (being audited): {prediction}"""


def _trivial(c):
    """A claim that asserts an absence makes no factual assertion, so it cannot be ungrounded."""
    return c.asserts_absence


_HAS_DIGIT = re.compile(r"\d")


def _figures_ok(c):
    """The figures test, made vacuous for claims that have no figures.

    Found by the first full run. q21 was the ONLY answer in 94 that the AND newly marked
    ungrounded, and it was a false negative: the claim "management attributed this change to
    the transition from Hopper HGX systems to Blackwell" is fully supported by the context
    and contains no numbers at all. Asked "are the numbers this claim rests on present?",
    the model answered False - which is defensible, since there are none.

    So the question was wrong, not the answer. A claim with no digits rests on no figures,
    and a test with nothing to test passes. This is decided in CODE by looking for a digit,
    rather than by adding another instruction the model can forget - the fourth time in this
    project that a mechanical rule has replaced a reasoning one.

    Note the direction: this can only ever turn a 0 into a 1. It relaxes, so no answer that
    previously passed can start failing, and no historical score can move.

    AND IT DID COST A CATCH, which is why probe_scope_ab.py --recheck exists. r03's
    unsupported_add mutation - "Intel's auditors flagged this attribution as a material
    weakness in internal controls", a digit-free sentence about nothing in the filing - was
    scored 0 before this rule and 1 after it.

    Read what that actually says. The claim ranges over Intel, and the context covers Intel,
    so the SCOPE test passed it. It was only being caught because the model, asked whether
    the claim's figures were in the context, said no about a claim that has no figures. It
    was caught by a flag that was answering a different question. **A check that passes for
    the wrong reason is not a check** - it is a coincidence that will stop happening the
    moment anything nearby changes, which is exactly what happened.

    The catch was never this judge's job. An unsupported claim about a covered entity is a
    factual-support failure, and the binary judge catches all three of those mutations 3/3.
    This judge is for SCOPE. So the rule stays, and the ANDed pair still scores 21/21.

    THE DEPENDENCY THIS CREATES, stated plainly because it is a real liability: after this
    change the scope judge alone scores 15/21 and MUST NOT be used as a standalone
    groundedness metric. It is one half of an AND. If the binary judge is ever retired or
    replaced, this hole reopens, and the principled repair is a `support_quote` field - the
    model returns a verbatim span from the context and CODE checks the span is really there,
    so a claim with nothing to quote fails. That is parked, not forgotten.
    """
    if not _HAS_DIGIT.search(c.claim):
        return True
    return c.input_figures_in_context


def scope_judge(question, prediction, context):
    """Return {"score", "claims", "bad", "reasoning"} - score computed HERE, not by the model.

    The model never sees the scoring rule, so an answer's confident tone has nothing to argue
    with. Changing the rule below re-scores stored observations without a single new call.
    """
    judge = BASE_LLM.with_structured_output(ScopeVerdict, include_raw=True).with_retry(
        stop_after_attempt=3
    )
    result = judge.invoke(SCOPE_PROMPT.format(question=to_text(question),
                                              context=to_text(context),
                                              prediction=to_text(prediction)))
    log_cost("gemini-3.1-flash-lite", result["raw"], label="groundedness-scope")
    v = result["parsed"]
    if v is None:
        raise ValueError(f"scope output did not parse: {result.get('parsing_error')}")

    bad = [c for c in v.claims
           if not _trivial(c)
           and not (c.context_covers_that_whole_set and _figures_ok(c))]
    # An answer with no assertions at all is a refusal, and a refusal is trivially grounded -
    # the same rule the original judge states in its prompt, kept so the two are comparable.
    score = 0 if bad else 1
    why = "; ".join(
        f"{c.claim[:60]!r} ranges over {c.ranges_over[:40]!r}"
        + ("" if c.context_covers_that_whole_set else " - CONTEXT DOES NOT COVER THAT SET")
        + ("" if _figures_ok(c) else " - figures missing")
        for c in bad[:3])
    return {"score": score, "claims": len(v.claims), "bad": len(bad),
            "detail": [(c.claim, c.ranges_over, c.context_covers_that_whole_set,
                        c.input_figures_in_context, c.asserts_absence) for c in v.claims],
            "reasoning": why or f"all {len(v.claims)} claims within the context's scope"}
