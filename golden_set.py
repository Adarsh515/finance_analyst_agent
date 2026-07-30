"""
Golden eval set for the NVIDIA FY2026 10-K (fiscal year ended January 25, 2026).

Every reference_answer was VERIFIED by a human against the filing text.
Rule that never breaks: an LLM may help phrase questions, but it must NOT be the
source of the answer key - otherwise a model's mistakes become our "truth".

Schema:
  id, question, reference_answer, evidence, difficulty, section, answer_type
  (evidence = WHERE in the filing + the figure/quote the groundedness judge checks)

Difficulty mix:  ~11 easy | ~7 medium | ~5 hard | 3 refusal
Verified figures (FY2026 / FY2025), all $ in millions unless noted:
  Revenue 215,938 / 130,497       Gross profit 153,463 / 97,858
  Net income 120,067 / 72,880     R&D 18,497 / 12,914
  Income tax 21,383 / 11,146      Basic EPS $4.93 / $2.97 ; Diluted $4.90 / $2.94
  Total assets 206,803 / 111,601  Total liabilities 49,510 / 32,274
  Total equity 157,293 / 79,327   Cash & equiv 10,605 / 8,589
  Op cash flow 102,718 / 64,089   Investing (52,228) / (20,421)  Financing (48,474) / (42,359)
  Data Center 193,737 / 115,186   Gaming 16,042 / 11,350
  Employees ~42,000 in 38 countries
"""

GOLDEN_SET = [
    # ================= EASY: one number, one place =================
    {"id": "q01",
     "question": "What was NVIDIA's total revenue for fiscal year 2026?",
     "reference_answer": "$215,938 million (about $215.9 billion).",
     "evidence": "Consolidated Statements of Income (Item 8): Revenue $215,938 (FY ended Jan 25, 2026).",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "q02",
     "question": "What was NVIDIA's net income for fiscal year 2026?",
     "reference_answer": "$120,067 million (about $120.1 billion).",
     "evidence": "Consolidated Statements of Income (Item 8): Net income $120,067.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "q03",
     "question": "What was NVIDIA's gross profit for fiscal year 2026?",
     "reference_answer": "$153,463 million.",
     "evidence": "Consolidated Statements of Income (Item 8): Gross profit $153,463.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "q04",
     "question": "How much did NVIDIA spend on research and development in fiscal year 2026?",
     "reference_answer": "$18,497 million.",
     "evidence": "Consolidated Statements of Income (Item 8): Research and development $18,497.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "q05",
     "question": "What was NVIDIA's basic earnings per share for fiscal year 2026?",
     "reference_answer": "$4.93 basic (diluted was $4.90).",
     "evidence": "Consolidated Statements of Income (Item 8): Net income per share Basic $4.93, Diluted $4.90.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "q06",
     "question": "What were NVIDIA's total assets as of the end of fiscal year 2026?",
     "reference_answer": "$206,803 million.",
     "evidence": "Consolidated Balance Sheets (Item 8): Total assets $206,803 as of Jan 25, 2026.",
     "difficulty": "easy", "section": "balance sheet", "answer_type": "number"},

    {"id": "q07",
     "question": "What were NVIDIA's total liabilities as of the end of fiscal year 2026?",
     "reference_answer": "$49,510 million.",
     "evidence": "Consolidated Balance Sheets (Item 8): Total liabilities $49,510.",
     "difficulty": "easy", "section": "balance sheet", "answer_type": "number"},

    {"id": "q08",
     "question": "What was NVIDIA's total shareholders' equity at the end of fiscal year 2026?",
     "reference_answer": "$157,293 million.",
     "evidence": "Consolidated Balance Sheets (Item 8): Total shareholders' equity $157,293.",
     "difficulty": "easy", "section": "balance sheet", "answer_type": "number"},

    {"id": "q09",
     "question": "How much cash and cash equivalents did NVIDIA hold at the end of fiscal year 2026?",
     "reference_answer": "$10,605 million.",
     "evidence": "Consolidated Balance Sheets (Item 8): Cash and cash equivalents $10,605.",
     "difficulty": "easy", "section": "balance sheet", "answer_type": "number"},

    {"id": "q10",
     "question": "What was NVIDIA's net cash provided by operating activities in fiscal year 2026?",
     "reference_answer": "$102,718 million.",
     "evidence": "Consolidated Statements of Cash Flows (Item 8): Net cash provided by operating activities $102,718.",
     "difficulty": "easy", "section": "cash flow", "answer_type": "number"},

    {"id": "q11",
     "question": "What was NVIDIA's Data Center revenue in fiscal year 2026?",
     "reference_answer": "$193,737 million.",
     "evidence": "Revenue by market platform (Notes / MD&A): Data Center $193,737.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    # ================= MEDIUM: locate + read, or narrative =================
    {"id": "q12",
     "question": "Why did NVIDIA's gross margin decrease in fiscal year 2026?",
     "reference_answer": "Because its business model transitioned from offering Hopper HGX systems to Blackwell full-scale data center solutions.",
     "evidence": "MD&A (Item 7): 'Gross margin decreased in fiscal year 2026 as our business model transitioned from offering Hopper HGX systems to Blackwell full-scale datacenter solutions.'",
     "difficulty": "medium", "section": "MD&A", "answer_type": "short-text"},

    {"id": "q13",
     "question": "Name one competition-related risk NVIDIA identifies in its Risk Factors.",
     "reference_answer": "That competition could adversely impact its market share and financial results.",
     "evidence": "Risk Factors Summary (Item 1A): 'Competition could adversely impact our market share and financial results.'",
     "difficulty": "medium", "section": "risk factors", "answer_type": "short-text"},

    {"id": "q14",
     "question": "By how much did NVIDIA's total revenue grow from fiscal 2025 to fiscal 2026, in dollars and percent?",
     "reference_answer": "It grew by $85,441 million (from $130,497M to $215,938M), about a 65% increase.",
     "evidence": "Income Statement (Item 8): Revenue $215,938 (FY26) vs $130,497 (FY25); 215,938-130,497 = 85,441; +65%.",
     "difficulty": "medium", "section": "income statement", "answer_type": "short-text"},

    {"id": "q15",
     "question": "Which of NVIDIA's market platforms generated the most revenue in fiscal 2026, and how much?",
     "reference_answer": "Data Center, with $193,737 million.",
     "evidence": "Revenue by market platform: Data Center $193,737 (largest, vs Gaming $16,042, etc.).",
     "difficulty": "medium", "section": "income statement", "answer_type": "short-text"},

    {"id": "q16",
     "question": "Approximately how many employees did NVIDIA have, and in how many countries, at fiscal 2026 year-end?",
     "reference_answer": "About 42,000 employees across 38 countries.",
     "evidence": "Business / Human Capital (Item 1): '42,000 employees in 38 countries'.",
     "difficulty": "medium", "section": "business (Item 1)", "answer_type": "short-text"},

    {"id": "q17",
     "question": "By how much did NVIDIA's Data Center revenue change from fiscal 2025 to fiscal 2026?",
     "reference_answer": "It rose by $78,551 million (from $115,186M to $193,737M), about a 68% increase.",
     "evidence": "Revenue by market platform: Data Center $193,737 (FY26) vs $115,186 (FY25); +78,551; ~68%.",
     "difficulty": "medium", "section": "income statement", "answer_type": "short-text"},

    {"id": "q18",
     "question": "What was NVIDIA's income tax expense in fiscal year 2026?",
     "reference_answer": "$21,383 million.",
     "evidence": "Consolidated Statements of Income (Item 8): Income tax expense $21,383.",
     "difficulty": "medium", "section": "income statement", "answer_type": "number"},

    # ================= HARD: cross-statement / multi-step =================
    {"id": "q19",
     "question": "In fiscal 2026, was NVIDIA's net income higher or lower than its net cash from operating activities?",
     "reference_answer": "Higher. Net income was $120,067M vs operating cash flow of $102,718M - net income exceeded operating cash flow by about $17.3 billion.",
     "evidence": "Income Statement: Net income $120,067M. Cash Flow: Net cash from operating activities $102,718M.",
     "difficulty": "hard", "section": "income statement + cash flow", "answer_type": "short-text"},

    {"id": "q20",
     "question": "Using NVIDIA's fiscal 2026 balance sheet, verify that assets equal liabilities plus equity, and state total equity.",
     "reference_answer": "It balances: $49,510M liabilities + $157,293M equity = $206,803M total assets. Total equity is $157,293M.",
     "evidence": "Balance Sheet (Item 8): Total liabilities $49,510 + Total equity $157,293 = Total assets $206,803.",
     "difficulty": "hard", "section": "balance sheet", "answer_type": "short-text"},

    {"id": "q21",
     "question": "How did NVIDIA's gross margin change from fiscal 2025 to fiscal 2026, and what did management attribute the change to?",
     "reference_answer": "Gross margin fell from 75.0% to 71.1% (down about 3.9 points), attributed to the shift from Hopper HGX systems to Blackwell full-scale data center solutions.",
     "evidence": "MD&A % table: gross profit 71.1% (FY26) vs 75.0% (FY25). MD&A narrative cites the Hopper-to-Blackwell transition.",
     "difficulty": "hard", "section": "income statement + MD&A", "answer_type": "short-text"},

    {"id": "q22",
     "question": "Did both NVIDIA's total assets and total shareholders' equity at least double from fiscal 2025 to fiscal 2026?",
     "reference_answer": "No. Total assets grew about 85% ($111,601M to $206,803M) and equity grew about 98% ($79,327M to $157,293M) - both grew sharply but neither quite doubled.",
     "evidence": "Balance Sheet: assets 206,803 vs 111,601 (x1.85); equity 157,293 vs 79,327 (x1.98).",
     "difficulty": "hard", "section": "balance sheet", "answer_type": "boolean"},

    {"id": "q23",
     "question": "In fiscal 2026, did NVIDIA use more cash for investing activities or for financing activities?",
     "reference_answer": "More for investing: $52,228M used in investing vs $48,474M used in financing.",
     "evidence": "Cash Flow (Item 8): investing $(52,228)M; financing $(48,474)M.",
     "difficulty": "hard", "section": "cash flow", "answer_type": "short-text"},

    # ================= REFUSAL: not in the filing (must decline) =================
    {"id": "q24",
     "question": "What is NVIDIA's exact percentage share of the global GPU market in fiscal 2026?",
     "reference_answer": "Not stated in the filing. The 10-K discusses competition and markets but discloses no specific market-share percentage.",
     "evidence": "No such figure is disclosed in the filing.",
     "difficulty": "medium", "section": "not-in-filing", "answer_type": "refusal"},

    {"id": "q25",
     "question": "What does NVIDIA project its total revenue will be for fiscal year 2027?",
     "reference_answer": "Not stated. The 10-K does not provide a specific fiscal 2027 revenue projection.",
     "evidence": "No specific forward revenue figure for FY2027 is given in the filing.",
     "difficulty": "medium", "section": "not-in-filing", "answer_type": "refusal"},

    {"id": "q26",
     "question": "What is NVIDIA's current stock price?",
     "reference_answer": "Not something this document can answer. A 10-K is a point-in-time annual report and does not contain a live/current stock price.",
     "evidence": "No live/current market price exists in the filing.",
     "difficulty": "easy", "section": "not-in-filing", "answer_type": "refusal"},

    # ================= HARDER SET (Phase 2.5 — add headroom) =================
    # -- multi-step math (retrieve a number, then compute) --
    {"id": "q27",
     "question": "What was NVIDIA's operating margin in fiscal year 2026?",
     "reference_answer": "About 60% (operating income $130,387M / revenue $215,938M = 60.4%).",
     "evidence": "Income Statement: Operating income $130,387M; Revenue $215,938M.",
     "difficulty": "hard", "section": "income statement", "answer_type": "number"},
    {"id": "q28",
     "question": "What was NVIDIA's effective tax rate in fiscal year 2026?",
     "reference_answer": "About 15% (income tax $21,383M / income before tax $141,450M = 15.1%).",
     "evidence": "Income Statement: Income tax expense $21,383M; Income before income tax $141,450M.",
     "difficulty": "hard", "section": "income statement", "answer_type": "number"},
    {"id": "q29",
     "question": "By how much did NVIDIA's net income grow from fiscal 2025 to fiscal 2026, in dollars and percent?",
     "reference_answer": "It grew by $47,187M (from $72,880M to $120,067M), about a 65% increase.",
     "evidence": "Income Statement: Net income $120,067M (FY26) vs $72,880M (FY25).",
     "difficulty": "hard", "section": "income statement", "answer_type": "short-text"},
    # -- prior-year distractors (read the RIGHT column) --
    {"id": "q30",
     "question": "What was NVIDIA's total revenue in fiscal year 2025?",
     "reference_answer": "$130,497 million.",
     "evidence": "Income Statement prior-year column: Revenue $130,497M (FY ended Jan 26, 2025).",
     "difficulty": "medium", "section": "income statement", "answer_type": "number"},
    {"id": "q31",
     "question": "What was NVIDIA's net income in fiscal year 2024?",
     "reference_answer": "$29,760 million.",
     "evidence": "Income Statement third column: Net income $29,760M (FY ended Jan 28, 2024).",
     "difficulty": "medium", "section": "income statement", "answer_type": "number"},
    # -- deep line items (find the specific row) --
    {"id": "q32",
     "question": "How much did NVIDIA hold in marketable securities at the end of fiscal year 2026?",
     "reference_answer": "$51,951 million.",
     "evidence": "Balance Sheet: Marketable securities $51,951M.",
     "difficulty": "medium", "section": "balance sheet", "answer_type": "number"},
    {"id": "q33",
     "question": "What was NVIDIA's accounts payable at the end of fiscal year 2026?",
     "reference_answer": "$9,812 million.",
     "evidence": "Balance Sheet: Accounts payable $9,812M.",
     "difficulty": "medium", "section": "balance sheet", "answer_type": "number"},
    {"id": "q34",
     "question": "What was NVIDIA's diluted earnings per share in fiscal year 2026?",
     "reference_answer": "$4.90.",
     "evidence": "Income Statement: Diluted net income per share $4.90.",
     "difficulty": "medium", "section": "income statement", "answer_type": "number"},
    {"id": "q35",
     "question": "How much net cash did NVIDIA use in financing activities in fiscal year 2026?",
     "reference_answer": "$48,474 million.",
     "evidence": "Cash Flow: Net cash used in financing activities $(48,474)M.",
     "difficulty": "medium", "section": "cash flow", "answer_type": "number"},
    {"id": "q36",
     "question": "What were NVIDIA's total current assets at the end of fiscal year 2026?",
     "reference_answer": "$125,605 million.",
     "evidence": "Balance Sheet: Total current assets $125,605M.",
     "difficulty": "medium", "section": "balance sheet", "answer_type": "number"},
    # -- another computation --
    {"id": "q37",
     "question": "What was NVIDIA's current ratio at the end of fiscal year 2026?",
     "reference_answer": "About 3.9 (current assets $125,605M / current liabilities $32,163M).",
     "evidence": "Balance Sheet: Total current assets $125,605M; Total current liabilities $32,163M.",
     "difficulty": "hard", "section": "balance sheet", "answer_type": "number"},
    # -- segment + narrative --
    {"id": "q38",
     "question": "What was NVIDIA's Gaming revenue in fiscal year 2026?",
     "reference_answer": "$16,042 million.",
     "evidence": "Revenue by market platform: Gaming $16,042M.",
     "difficulty": "medium", "section": "income statement", "answer_type": "number"},
    {"id": "q39",
     "question": "What export-related risk does NVIDIA identify in its filing?",
     "reference_answer": "Export control restrictions that limit its ability to serve customers outside the U.S. (affecting sales of its products, including to China).",
     "evidence": "Risk Factors / MD&A: cites export control restrictions impacting its products and ability to serve non-U.S. customers.",
     "difficulty": "medium", "section": "risk factors", "answer_type": "short-text"},
    # -- trap refusal (answer lives in the PROXY, not the 10-K) --
    {"id": "q40",
     "question": "What was the total compensation of NVIDIA's CEO in fiscal year 2026?",
     "reference_answer": "Not stated in this filing. Executive compensation is disclosed in NVIDIA's proxy statement (DEF 14A), not the 10-K.",
     "evidence": "The 10-K does not contain executive compensation figures.",
     "difficulty": "medium", "section": "not-in-filing", "answer_type": "refusal"},
]

if __name__ == "__main__":
    from collections import Counter
    print(f"Golden set: {len(GOLDEN_SET)} entries")
    print("By difficulty:", dict(Counter(e["difficulty"] for e in GOLDEN_SET)))
    print("By answer_type:", dict(Counter(e["answer_type"] for e in GOLDEN_SET)))
    for e in GOLDEN_SET:
        print(f"  {e['id']} [{e['difficulty']:<6}] {e['section']:<26} {e['question'][:52]}")
