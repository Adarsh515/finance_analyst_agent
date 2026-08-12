import json
import re
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# 2. steady grader; model"gemini-3.5-flash" is the most capable, but "gemini-3.1-flash-lite" is cheaper and faster and still very good for grading.
judge_llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0).with_retry(
    stop_after_attempt=3, wait_exponential_jitter=True,
)
# .with_retry(...) wraps the model so that if a call throws (like a 503), 
# it automatically tries again instead of crashing; 
# stop_after_attempt=3 gives it up to three tries; 
# wait_exponential_jitter=True makes it wait longer between each retry (1s, 2s, 4s…) with a little randomness,
# which is exactly how you politely back off from an overloaded server.

PRICES = {                          # USD per 1 million tokens: (input, output)
    "gemini-3.5-flash":      (1.50, 9.00),
    "gemini-3.1-flash-lite": (0.125, 0.75),
}
def log_cost(model, response, label=""):
    u = getattr(response, "usage_metadata", None) or {}
    intok, outok = u.get("input_tokens", 0), u.get("output_tokens", 0)
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    cost = (intok * p_in + outok * p_out) / 1_000_000
    print(f"    $ {cost:.6f}   ({label}: in={intok}, out={outok}, {model})")
    return cost

# 3. flatten a str OR a list-of-parts into plain text
def to_text(content):
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    else:
        return str(content)

# 4. the rubric prompt (note: doubled braces {{ }} are literal JSON)
CORRECTNESS_PROMPT = """You are grading a financial question-answering system.

You are given a QUESTION, the correct REFERENCE ANSWER, and the SYSTEM ANSWER produced by
the system under test. Decide whether the SYSTEM ANSWER is correct, judged ONLY against the
REFERENCE ANSWER.

Grading rules:
- Score 1 if the SYSTEM ANSWER conveys the same key fact or number as the REFERENCE ANSWER,
  even if worded differently or with extra correct detail. Different units or phrasings of the
  same value are correct (e.g. "$215.9 billion" equals "$215,938 million").
- Score 0 if the SYSTEM ANSWER's key fact/number is wrong, missing, answers a different metric
  or a different period, or contradicts the REFERENCE ANSWER.
- If the REFERENCE ANSWER says the information is not in the filing (a refusal): score 1 ONLY if
  the SYSTEM ANSWER also refuses; score 0 if the SYSTEM ANSWER gives a specific answer.
- If the REFERENCE ANSWER gives a specific answer but the SYSTEM ANSWER refuses ("not stated"),
  score 0 -- the answer exists, so refusing is wrong.
- Judge ONLY against the reference. Do not use outside knowledge.

First restate each answer, THEN score. Return ONLY a JSON object:
{{"reference_says": "<one phrase>", "system_says": "<one phrase>", "score": 1 or 0, "reasoning": "one short sentence"}}

QUESTION: {question}

REFERENCE ANSWER (the ground truth): {reference}

SYSTEM ANSWER (being graded): {prediction}
"""

# 5. read the verdict back safely, even if wrapped in ```json fences
def parse_verdict(raw):
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"score": 0, "reasoning": f"unparseable: {raw[:80]}"}
    try:
        data = json.loads(match.group(0))
        return {"score": int(data["score"]), "reasoning": data.get("reasoning", "")}
    except Exception as e:
        return {"score": 0, "reasoning": f"parse error: {e}"}
    
# 6. the judge
def correctness_judge(question, reference, prediction):
    prompt = CORRECTNESS_PROMPT.format(
        question=to_text(question),
        reference=to_text(reference),
        prediction=to_text(prediction),
    )
    resp = judge_llm.invoke(prompt)
    log_cost("gemini-3.1-flash-lite", resp, label="correctness")
    return parse_verdict(to_text(resp.content))

GROUNDEDNESS_PROMPT = """You are checking whether a SYSTEM ANSWER is grounded in the provided CONTEXT.
Groundedness is about SUPPORT, not correctness: judge ONLY whether the CONTEXT backs up the
answer's claims. Do not use outside knowledge, and do not judge whether the answer is correct.

Rules:
- Score 1 if every factual claim and number in the SYSTEM ANSWER is supported by the CONTEXT.
- Score 0 if the SYSTEM ANSWER contains any claim or number NOT present in, or directly
  inferable from, the CONTEXT (a hallucination).
- Arithmetic performed on numbers that ARE in the CONTEXT counts as supported. Differences,
  sums, ratios, percentages, growth rates and per-share figures derived from context numbers
  are grounded, even though the computed value itself does not appear in the CONTEXT.
  Check only that the INPUT numbers are present; do not check whether the arithmetic is right.
- If the SYSTEM ANSWER refuses / says the information is not stated, score 1 (a refusal makes no
  factual claim, so it is trivially grounded).

Return ONLY a JSON object:
{{"supported": "<one phrase>", "score": 1 or 0, "reasoning": "one short sentence"}}

QUESTION: {question}

CONTEXT:
{context}

SYSTEM ANSWER (being checked): {prediction}
"""

def groundedness_judge(question, prediction, context):
    prompt = GROUNDEDNESS_PROMPT.format(
        question=to_text(question),
        context=to_text(context),
        prediction=to_text(prediction),
    )
    resp = judge_llm.invoke(prompt)
    log_cost("gemini-3.1-flash-lite", resp, label="groundedness")
    return parse_verdict(to_text(resp.content))


# ---- self-tests: run ONLY with `python judges.py`, never on import ----
if __name__ == "__main__":

    print("\n--- correctness ---")
    tests = [
        ("What was NVIDIA's total revenue for fiscal year 2026?",
         "NVIDIA's revenue was $215.9 billion.",
         "$215,938 million (about $215.9 billion).", 1),

        ("What was NVIDIA's total revenue for fiscal year 2026?",
         "About $130 billion.",
         "$215,938 million (about $215.9 billion).", 0),

        ("What is NVIDIA's exact percentage share of the global GPU market in fiscal 2026?",
         "Not stated in the filing.",
         "Not stated in the filing. The 10-K does not disclose a market-share percentage.", 1),

        ("What was NVIDIA's total revenue for fiscal year 2026?",   # real number, wrong metric
         "NVIDIA's net income was $120,067 million.",
         "$215,938 million (about $215.9 billion).", 0),

        ("What was NVIDIA's total revenue for fiscal year 2026?",   # wrongful refusal
         "Not stated in the filing.",
         "$215,938 million (about $215.9 billion).", 0),
    ]
    for q, pred, ref, expected in tests:
        v = correctness_judge(question=q, prediction=pred, reference=ref)
        flag = "OK" if v["score"] == expected else "MISMATCH"
        print(f"[{flag}] score={v['score']} expected={expected}  |  {v['reasoning']}")

    print("\n--- groundedness ---")
    ctx = "Consolidated Statements of Income (In millions). Fiscal Year 2026 Summary. Revenue $215,938  $130,497  Up 65%. Gross margin 71.1% 75.0%."
    g_tests = [
        ("What was revenue in FY2026?", "Revenue was $215,938 million.", ctx, 1),
        ("What was net income in FY2026?", "Net income was $88,000 million.", ctx, 0),
        ("What is NVIDIA's market share?", "Not stated in the filing.", ctx, 1),
        # derived value: inputs are in context, the computed number is not -> grounded
        ("How much did revenue grow in dollars?", "Revenue grew by $85,441 million.", ctx, 1),
        # derived from a figure that is NOT in context -> not grounded
        ("How much did gross profit grow?", "Gross profit grew by $60,000 million.", ctx, 0),
    ]
    for q, pred, c, expected in g_tests:
        v = groundedness_judge(question=q, prediction=pred, context=c)
        flag = "OK" if v["score"] == expected else "MISMATCH"
        print(f"[{flag}] score={v['score']} expected={expected}  |  {v['reasoning']}")