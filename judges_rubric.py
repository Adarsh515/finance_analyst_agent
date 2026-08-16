# judges_rubric.py
# A rubric correctness judge, built BESIDE judges.py - that file stays byte-identical, the
# same rule the agent follows with rag.py. Both judges can be run over the same answers and
# compared; nothing has to be replaced to find out whether the replacement is better.
#
# WHY THIS EXISTS, measured rather than assumed:
#
#   n=3 on 40 stored answers produced ZERO flips. The binary judge is deterministic.
#   So the r03 story is not run-to-run variance, and my earlier lesson saying it was is
#   wrong. What actually happened is worse and more useful:
#
#     OLD  "For Intel, reported net income depends on whether non-controlling interests
#           are included. ... the net income (loss) attributable to non-controlling
#           interests was $293 million."                                  -> 1 / 1
#     LIVE "Based on the provided filings, Intel is the company for which reported net
#           income depends on the attribution of net income or loss to non-controlling
#           interests. According to the Intel 10-K financial table, the net income (loss)
#           attributable to non-controlling interests ... was $293 million."  -> 0 / 0
#
#   Same company. Same figure. Same omission. Different wording. Opposite verdicts, and
#   REPRODUCIBLY so. That is not noise - it is phrasing sensitivity, and a reproducible
#   defect is a fixable one.
#
# THE FIX, and it is a pattern this project already trusts:
#   Ask the model for OBSERVATIONS, and compute the VERDICT in code.
#
# The binary judge asks one fused question - "is this answer correct?" - which silently
# bundles fact-checking (mechanical) with completeness (a judgement call), and lets tone
# and length leak into both. The rubric splits them: for each fact the reference states,
# the model answers only "is this present, and is it right?". Code then decides the score.
# Same discipline as putting a loop bound in code instead of a prompt - the model reports,
# the code rules.

import re

from pydantic import BaseModel, Field

from judges import log_cost, to_text
from rag import llm

BASE_LLM = getattr(llm, "bound", llm)          # unwrap the retry policy, as agent.py does


class FactCheck(BaseModel):
    """One required fact from the reference answer, checked against the system answer."""
    fact: str = Field(description="The required fact, quoted from the REFERENCE ANSWER")
    present: bool = Field(description="Does the SYSTEM ANSWER state this fact at all?")
    correct: bool = Field(description="If present, is the value right? Different units or "
                                      "phrasings of the same value count as right "
                                      "($215.9 billion equals $215,938 million). "
                                      "False if absent.")


class RubricVerdict(BaseModel):
    """Observations only. The score is not asked for and must not be inferred from this."""
    facts: list[FactCheck] = Field(description="One entry per distinct fact the REFERENCE "
                                               "ANSWER presents as part of the answer")
    contradicts_itself: bool = Field(description="Does the answer state something its own "
                                                 "other statements contradict - a ranking "
                                                 "whose order disagrees with its numbers, "
                                                 "a heading its entries do not fit?")


RUBRIC_PROMPT = """You are auditing an answer produced by a financial question-answering system.

Do NOT decide whether the answer is good. Report observations only.

Step 1. Read the REFERENCE ANSWER and list every DISTINCT fact it presents AS THE ANSWER -
each figure, each named company, each comparison it draws. Ignore anything that is only
background or working.

DISTINCT is the important word. The same value written twice in different units or forms is
ONE fact, not two. "$215,938 million (about $215.9 billion)" is a single fact stated twice
over; listing it twice would demand that an answer repeat itself to be scored correct.
Likewise a figure and the arithmetic that produced it are one fact, not two.

Step 2. For each of those facts, check the SYSTEM ANSWER: is the fact stated at all, and if
so is the value right? A different unit or phrasing of the same value is right
("$215.9 billion" is "$215,938 million"). Extra correct detail in the SYSTEM ANSWER is not a
problem and is not your concern.

Step 3. Separately, say whether the SYSTEM ANSWER contradicts itself - for example a list
labelled as a ranking whose order disagrees with its own numbers, or a heading whose entries
do not belong under it.

Judge the CONTENT, never the wording, length or tone.

QUESTION: {question}

REFERENCE ANSWER: {reference}

SYSTEM ANSWER: {prediction}"""


_SCALE = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}


def _value(text):
    """First number in the text, scaled by any unit word right after it. None if no number.

    "$215,938 million" and "about $215.9 billion" both come back as 2.15938e11, which is
    the whole point: they are the same fact.
    """
    m = re.search(r"(-?\(?\$?\s*[\d,]+(?:\.\d+)?\)?)\s*(trillion|billion|million|thousand)?",
                  text, re.I)
    if not m:
        return None
    raw = m.group(1).replace("$", "").replace(",", "").replace(" ", "")
    neg = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()")
    try:
        n = float(raw)
    except ValueError:
        return None
    n *= _SCALE.get((m.group(2) or "").lower(), 1.0)
    return -n if neg else n


def _dedupe(facts):
    """Merge facts that state the same VALUE. A mechanical rule, not a reasoning one.

    The prompt already asks for distinct facts and the model mostly complies - but "mostly"
    is how q01 came back 1/2 and scored 0 for an answer that was entirely right: the
    reference's "(about $215.9 billion)" was counted as a second fact the answer had to
    repeat. A rule the model can forget belongs in code, which is a lesson this project has
    already paid for twice.

    Two facts merge when their values agree within 0.5%. A merged pair keeps the stricter
    verdict: if the answer got either rendering wrong, the fact is wrong.
    """
    kept = []
    for f in facts:
        v = _value(f.fact)
        hit = None
        if v is not None and v != 0:
            for g in kept:
                w = _value(g.fact)
                if w is not None and w != 0 and abs(v - w) / max(abs(v), abs(w)) < 0.005:
                    hit = g
                    break
        if hit is None:
            kept.append(f)
        else:
            hit.present = hit.present and f.present
            hit.correct = hit.correct and f.correct
    return kept


def rubric_judge(question, reference, prediction):
    """Return {"score", "facts_ok", "facts_total", "contradicts", "reasoning"}.

    The score is computed HERE, from the model's observations - the model never sees the
    scoring rule, so it cannot be talked into a verdict by an answer's confident tone.
    """
    judge = BASE_LLM.with_structured_output(RubricVerdict, include_raw=True).with_retry(
        stop_after_attempt=3
    )
    result = judge.invoke(RUBRIC_PROMPT.format(question=question, reference=reference,
                                               prediction=prediction))
    log_cost("gemini-3.1-flash-lite", result["raw"], label="rubric")
    v = result["parsed"]
    if v is None:
        raise ValueError(f"rubric output did not parse: {result.get('parsing_error')}")

    facts = _dedupe(v.facts)
    total = len(facts)
    ok = sum(1 for f in facts if f.present and f.correct)
    # The rule, in code and in one place: every required fact present and right, and no
    # self-contradiction. Stating it here rather than in the prompt means it can be changed
    # and re-measured without re-running a single model call.
    score = 1 if (total > 0 and ok == total and not v.contradicts_itself) else 0
    missing = [f.fact for f in facts if not (f.present and f.correct)]
    return {"score": score, "facts_ok": ok, "facts_total": total,
            "facts": [(f.fact, f.present, f.correct) for f in facts],
            "contradicts": v.contradicts_itself,
            "reasoning": ("self-contradictory; " if v.contradicts_itself else "")
                         + (f"missing/wrong: {missing}" if missing else "all facts present")}
