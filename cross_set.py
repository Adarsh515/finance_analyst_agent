"""
Cross-document eval set: NVIDIA FY2026 10-K + AMD FY2025 10-K.

Same rules as golden_set.py - every reference_answer is HUMAN-verified against
the filings. New field: "companies" = which filings an answer legitimately needs.
That field is what lets us score single-company vs cross-company separately.

Period trap: AMD fiscal 2025 ended Dec 27, 2025. NVIDIA fiscal 2026 ended Jan 25, 2026.
Different labels, nearly the same calendar year. Compare periods, not FY numbers.
"""

CROSS_SET = [
    # ===== A. AMD-only: does a second company work at all? =====
    {"id": "x01", "companies": ["AMD"],
     "question": "What was AMD's net revenue for fiscal year 2025?",
     "reference_answer": "$34,639 million (about $34.6 billion).",
     "evidence": "AMD Consolidated Statements of Operations: Net revenue $34,639 (FY ended Dec 27, 2025).",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "x02", "companies": ["AMD"],
     "question": "What was AMD's net income for fiscal year 2025?",
     "reference_answer": "$4,335 million.",
     "evidence": "AMD Consolidated Statements of Operations: Net income $4,335.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "x03", "companies": ["AMD"],
     "question": "How much did AMD spend on research and development in fiscal year 2025?",
     "reference_answer": "$8,091 million.",
     "evidence": "AMD Consolidated Statements of Operations: Research and development $8,091.",
     "difficulty": "easy", "section": "income statement", "answer_type": "number"},

    {"id": "x04", "companies": ["AMD"],
     "question": "What was AMD's Data Center segment revenue in fiscal year 2025?",
     "reference_answer": "$16,635 million.",
     "evidence": "AMD segment results: Data Center net revenue $16,635 (vs $12,579 in FY2024).",
     "difficulty": "easy", "section": "segments", "answer_type": "number"},

    {"id": "x05", "companies": ["AMD"],
     "question": "What were AMD's total assets at the end of fiscal year 2025?",
     "reference_answer": "$76,926 million.",
     "evidence": "AMD Consolidated Balance Sheets: Total assets $76,926 as of Dec 27, 2025.",
     "difficulty": "easy", "section": "balance sheet", "answer_type": "number"},

    # ===== B. True comparisons: the answer needs BOTH filings =====
    {"id": "x06", "companies": ["NVIDIA", "AMD"],
     "question": "Which company had higher total revenue in its most recent fiscal year, NVIDIA or AMD, and by how much?",
     "reference_answer": "NVIDIA, by $181,299 million. NVIDIA's revenue was $215,938M (FY2026) versus AMD's $34,639M (FY2025) - roughly 6.2 times larger.",
     "evidence": "NVIDIA income statement: Revenue $215,938. AMD income statement: Net revenue $34,639. 215,938-34,639 = 181,299.",
     "difficulty": "medium", "section": "cross-company", "answer_type": "short-text"},

    {"id": "x07", "companies": ["NVIDIA", "AMD"],
     "question": "Compare NVIDIA's and AMD's research and development spending in their most recent fiscal years.",
     "reference_answer": "NVIDIA spent $18,497 million versus AMD's $8,091 million - NVIDIA spent $10,406 million more, about 2.3 times as much.",
     "evidence": "NVIDIA R&D $18,497 (FY2026); AMD R&D $8,091 (FY2025).",
     "difficulty": "medium", "section": "cross-company", "answer_type": "short-text"},

    {"id": "x08", "companies": ["NVIDIA", "AMD"],
     "question": "Whose gross margin was higher in the most recent fiscal year, NVIDIA or AMD?",
     "reference_answer": "NVIDIA's, at about 71.1% versus AMD's 50% - roughly 21 percentage points higher.",
     "evidence": "NVIDIA MD&A percentage table: gross margin 71.1% (FY2026). AMD income statement: Gross margin 50% (FY2025).",
     "difficulty": "medium", "section": "cross-company", "answer_type": "short-text"},

    {"id": "x09", "companies": ["NVIDIA", "AMD"],
     "question": "Which company spent a larger share of its revenue on research and development, NVIDIA or AMD?",
     "reference_answer": "AMD, by a wide margin. AMD spent $8,091M of $34,639M revenue, about 23.4%, while NVIDIA spent $18,497M of $215,938M, about 8.6%.",
     "evidence": "AMD 8,091/34,639 = 23.4%. NVIDIA 18,497/215,938 = 8.6%.",
     "difficulty": "hard", "section": "cross-company", "answer_type": "short-text"},

    {"id": "x10", "companies": ["NVIDIA", "AMD"],
     "question": "Compare NVIDIA's and AMD's Data Center revenue in their most recent fiscal years.",
     "reference_answer": "NVIDIA's Data Center revenue was $193,737 million versus AMD's $16,635 million - NVIDIA's was roughly 11.6 times larger.",
     "evidence": "NVIDIA Data Center $193,737 (FY2026); AMD Data Center $16,635 (FY2025).",
     "difficulty": "medium", "section": "cross-company", "answer_type": "short-text"},

    {"id": "x11", "companies": ["NVIDIA", "AMD"],
     "question": "Compare net cash provided by operating activities for NVIDIA and AMD in their most recent fiscal years.",
     "reference_answer": "NVIDIA generated $102,718 million versus AMD's $7,709 million - about 13 times more operating cash flow.",
     "evidence": "NVIDIA cash flow: operating activities $102,718. AMD cash flow: Operating activities $7,709 (including $1,216 from discontinued operations).",
     "difficulty": "hard", "section": "cross-company", "answer_type": "short-text"},

    {"id": "x12", "companies": ["NVIDIA", "AMD"],
     "question": "How many employees did NVIDIA and AMD each report?",
     "reference_answer": "NVIDIA reported about 42,000 employees across 38 countries; AMD reported approximately 31,000 employees in its global workforce. AMD does not state a country count.",
     "evidence": "NVIDIA Item 1 Human Capital: 42,000 employees in 38 countries. AMD Item 1 Human Capital: 'approximately 31,000 employees in our global workforce'.",
     "difficulty": "medium", "section": "cross-company", "answer_type": "short-text"},

    # ===== C. Traps: designed to catch company-mixing and sign errors =====
    {"id": "x13", "companies": ["NVIDIA", "AMD"],
     "question": "Both NVIDIA and AMD report a Gaming segment. What was Gaming revenue for each?",
     "reference_answer": "NVIDIA's Gaming revenue was $16,042 million (FY2026); AMD's Gaming revenue was $3,910 million (FY2025).",
     "evidence": "NVIDIA revenue by market platform: Gaming $16,042. AMD segment results: Gaming $3,910.",
     "difficulty": "hard", "section": "cross-company trap", "answer_type": "short-text"},

    {"id": "x14", "companies": ["NVIDIA", "AMD"],
     "question": "What exact date did AMD's fiscal 2025 end, and what exact date did NVIDIA's fiscal 2026 end?",
     "reference_answer": "AMD's fiscal 2025 ended December 27, 2025. NVIDIA's fiscal 2026 ended January 25, 2026.",
     "evidence": "AMD cover page: 'For the fiscal year ended December 27, 2025'. NVIDIA cover page: fiscal year ended January 25, 2026.",
     "difficulty": "medium", "section": "cross-company trap", "answer_type": "short-text"},

    {"id": "x15", "companies": ["AMD"],
     "question": "What were AMD's total liabilities at the end of fiscal year 2025?",
     "reference_answer": "About $13,927 million. AMD's balance sheet does not present a 'Total liabilities' subtotal, so it must be derived: total assets $76,926M minus total stockholders' equity $62,999M.",
     "evidence": "AMD Balance Sheet: Total assets $76,926; Total stockholders' equity $62,999; no 'Total liabilities' line is presented.",
     "difficulty": "hard", "section": "balance sheet trap", "answer_type": "short-text"},

    {"id": "x16", "companies": ["AMD"],
     "question": "What was AMD's income tax provision for fiscal year 2025?",
     "reference_answer": "A benefit of $103 million, shown as $(103) - not an expense. AMD recorded a net income tax benefit in fiscal 2025.",
     "evidence": "AMD Consolidated Statements of Operations: Income tax provision (benefit) $(103) for FY2025, versus $381 expense in FY2024.",
     "difficulty": "hard", "section": "income statement trap", "answer_type": "short-text"},

    # ===== D. Refusal: in neither filing =====
    {"id": "x17", "companies": [],
     "question": "Which company holds a larger share of the AI accelerator market, NVIDIA or AMD?",
     "reference_answer": "Not stated in the filings. Neither 10-K discloses a specific AI accelerator market-share figure for either company.",
     "evidence": "No market-share percentage is disclosed in either filing.",
     "difficulty": "medium", "section": "not-in-filing", "answer_type": "refusal"},

     # ===== E. Implicit reference: needs BOTH filings, names NEITHER company =====
    # These are built to defeat detect_companies(). None of them contains the
    # strings "nvidia", "nvda", "amd", or "advanced micro devices".
    {"id": "x18", "companies": ["NVIDIA", "AMD"],
     "question": "Between the two companies covered by these filings, which reported higher total revenue in its most recent fiscal year, and by how much?",
     "reference_answer": "NVIDIA, by $181,299 million. NVIDIA's revenue was $215,938M (FY2026) versus $34,639M (FY2025) - roughly 6.2 times larger.",
     "evidence": "NVIDIA income statement: Revenue $215,938. AMD income statement: Net revenue $34,639. 215,938-34,639 = 181,299.",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "short-text"},

    {"id": "x19", "companies": ["NVIDIA", "AMD"],
     "question": "Which of them spent more on research and development, and what were the two figures?",
     "reference_answer": "NVIDIA spent more: $18,497 million versus $8,091 million - $10,406 million more, about 2.3 times as much.",
     "evidence": "NVIDIA R&D $18,497 (FY2026); AMD R&D $8,091 (FY2025).",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "short-text"},

    {"id": "x20", "companies": ["NVIDIA", "AMD"],
     "question": "For the larger of the two by revenue, what was its gross margin, and how does that compare with the smaller one's?",
     "reference_answer": "The larger by revenue is NVIDIA, with a gross margin of about 71.1%, versus AMD's 50% - roughly 21 percentage points higher.",
     "evidence": "NVIDIA MD&A percentage table: gross margin 71.1% (FY2026). AMD income statement: Gross margin 50% (FY2025). Revenue 215,938 > 34,639.",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "short-text"},

    {"id": "x21", "companies": ["NVIDIA", "AMD"],
     "question": "The company with the higher gross margin also reports a Data Center segment. How much bigger was its Data Center revenue than the other company's?",
     "reference_answer": "$177,102 million bigger. NVIDIA (the higher-margin company at 71.1%) reported Data Center revenue of $193,737M versus AMD's $16,635M - about 11.6 times larger.",
     "evidence": "NVIDIA Data Center $193,737 (FY2026); AMD Data Center $16,635 (FY2025). 193,737-16,635 = 177,102.",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "short-text"},

    {"id": "x22", "companies": ["NVIDIA", "AMD"],
     "question": "And how did their Gaming segments compare in those same periods?",
     "reference_answer": "NVIDIA's Gaming revenue was $16,042 million (FY2026); AMD's was $3,910 million (FY2025) - NVIDIA's was $12,132 million higher, about 4.1 times larger.",
     "evidence": "NVIDIA revenue by market platform: Gaming $16,042. AMD segment results: Gaming $3,910.",
     "difficulty": "hard", "section": "cross-company implicit trap", "answer_type": "short-text"},

    {"id": "x23", "companies": ["NVIDIA", "AMD"],
     "question": "What was the combined net income of both chipmakers in their most recent fiscal years covered by these filings?",
     "reference_answer": "$124,402 million (about $124.4 billion): NVIDIA's $120,067M for FY2026 plus AMD's $4,335M for FY2025. The two fiscal years are not identical periods.",
     "evidence": "NVIDIA net income $120,067 (FY ended Jan 25, 2026); AMD net income $4,335 (FY ended Dec 27, 2025). 120,067+4,335 = 124,402.",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "number"},

    {"id": "x24", "companies": ["NVIDIA", "AMD"],
     "question": "How many times more cash did the bigger company generate from operations than the smaller one?",
     "reference_answer": "About 13.3 times. NVIDIA generated $102,718 million from operating activities versus AMD's $7,709 million.",
     "evidence": "NVIDIA cash flow: operating activities $102,718. AMD cash flow: operating activities $7,709. 102,718/7,709 = 13.3.",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "short-text"},

    {"id": "x25", "companies": ["NVIDIA", "AMD"],
     "question": "Which of the two employed more people at fiscal year end, and roughly how many did each report?",
     "reference_answer": "NVIDIA employed more: about 42,000 employees versus approximately 31,000 - roughly 11,000 more.",
     "evidence": "NVIDIA Item 1 Human Capital: 42,000 employees in 38 countries. AMD Item 1 Human Capital: approximately 31,000 employees.",
     "difficulty": "hard", "section": "cross-company implicit", "answer_type": "short-text"},

    # ===== E. Phase 4.0: questions the single-round pipeline should fail =====
    {"id": "x26", "companies": ["NVIDIA", "AMD"],
     "question": "How much bigger was NVIDIA's gross profit than the other chipmaker's in these filings?",
     "reference_answer": "$136,311 million bigger: NVIDIA's gross profit was $153,463M (FY2026) versus AMD's $17,152M (FY2025).",
     "evidence": "NVIDIA income statement: Gross profit $153,463. AMD income statement: Gross profit $17,152. 153,463-17,152 = 136,311.",
     "difficulty": "hard", "section": "cross-company one-name", "answer_type": "number"},

    {"id": "x27", "companies": ["NVIDIA", "AMD"],
     "question": "Of the two companies in these filings, whichever had the lower gross margin - what percentage of its revenue did that company spend on research and development?",
     "reference_answer": "AMD had the lower gross margin (50% versus NVIDIA's 71.1%), and AMD spent about 23.4% of its revenue on R&D ($8,091M of $34,639M).",
     "evidence": "AMD gross margin 50%, NVIDIA gross margin 71.1%. AMD R&D $8,091 / net revenue $34,639 = 23.4%.",
     "difficulty": "hard", "section": "cross-company multi-hop", "answer_type": "short-text"},

     {"id": "x28", "companies": ["NVIDIA", "AMD"],
     "question": "How much smaller were AMD's total assets than the other chipmaker's in these filings?",
     "reference_answer": "$129,877 million smaller: AMD's total assets were $76,926M (FY2025) versus NVIDIA's $206,803M (FY2026).",
     "evidence": "AMD balance sheet: Total assets $76,926. NVIDIA balance sheet: Total assets $206,803. 206,803-76,926 = 129,877.",
     "difficulty": "hard", "section": "cross-company one-name", "answer_type": "number"},

    {"id": "x29", "companies": ["NVIDIA", "AMD"],
     "question": "Across the two companies in these filings, which one leads on gross margin, which leads on R&D as a share of revenue, and which leads on cash generated from operations?",
     "reference_answer": "NVIDIA leads on gross margin (71.1% vs 50%) and on operating cash flow ($102,718M vs $7,709M). AMD leads on R&D as a share of revenue (about 23.4% vs about 8.6%).",
     "evidence": "Gross margins 71.1% / 50%. R&D 18,497/215,938 = 8.6%; 8,091/34,639 = 23.4%. Operating cash flow 102,718 / 7,709.",
     "difficulty": "hard", "section": "cross-company breadth", "answer_type": "short-text"},

    {"id": "x30", "companies": ["NVIDIA", "AMD"],
     "question": "For whichever of these two companies reported an income tax benefit rather than an expense, what were its total liabilities at fiscal year end?",
     "reference_answer": "AMD, which reported an income tax benefit of $(103) million, had total liabilities of $13,927 million (total assets $76,926M less stockholders' equity $62,999M).",
     "evidence": "AMD income statement: income tax provision $(103) - a benefit. AMD balance sheet has no 'Total liabilities' line; 76,926-62,999 = 13,927.",
     "difficulty": "hard", "section": "cross-company multi-hop derived", "answer_type": "number"},


    # ===== E. Derived figures: arithmetic is the thing under test =====
    # Every reference below was computed from figures already verified in
    # PROJECT_TRACKER.md and re-checked against the filings before being added.

    {"id": "d01", "companies": ["NVIDIA", "AMD"], "derived": True,
     "question": "Which company spent a larger share of its revenue on research and development, "
                 "and by how many percentage points?",
     "reference_answer": "AMD, by about 14.8 percentage points. AMD spent 8,091/34,639 = 23.4% of "
                         "net revenue on R&D; NVIDIA spent 18,497/215,938 = 8.6%.",
     "evidence": "NVIDIA income statement R&D $18,497, revenue $215,938. AMD income statement R&D $8,091, net revenue $34,639.",
     "difficulty": "hard", "section": "derived ratio, both companies", "answer_type": "short-text"},

    # Reworded 2026-08-12. The first version asked about "four reportable segments", which is
    # wrong: AMD combined Client and Gaming into ONE reportable segment in Q1 FY2025, leaving
    # three. The system caught the false premise on its own. The question was fixed; the
    # reference answer's key fact (34,639) was not lowered.
    {"id": "d02", "companies": ["AMD"], "derived": True,
     "question": "Do AMD's reportable segment revenues add up to its total net revenue for fiscal 2025? "
                 "Name the segments and show the total.",
     "reference_answer": "Yes. AMD reports three segments: Data Center $16,635M, Client and Gaming "
                         "$14,550M, and Embedded $3,454M. 16,635 + 14,550 + 3,454 = $34,639 million, "
                         "which equals reported total net revenue.",
     "evidence": "AMD 10-K Note 4 Segment Reporting: 'The Company's three reportable segments are: "
                 "the Data Center segment, the Client and Gaming segment, and the Embedded segment.' "
                 "Segment net revenue table: Data Center 16,635; Client and Gaming 14,550 (Client 10,640 "
                 "and Gaming 3,910 shown as product lines within it); Embedded 3,454; Total 34,639.",
     "difficulty": "hard", "section": "segment note, three-number sum", "answer_type": "short-text"},

    {"id": "d03", "companies": ["NVIDIA", "AMD"], "derived": True,
     "question": "What was each company's net profit margin, and what is the gap between them in percentage points?",
     "reference_answer": "NVIDIA 120,067/215,938 = 55.6%; AMD 4,335/34,639 = 12.5%. Gap about 43.1 percentage points.",
     "evidence": "NVIDIA net income $120,067 on revenue $215,938. AMD net income $4,335 on net revenue $34,639.",
     "difficulty": "hard", "section": "derived ratio, both companies", "answer_type": "short-text"},

    {"id": "d04", "companies": ["NVIDIA", "AMD"], "derived": True,
     "question": "What were total liabilities as a percentage of total assets for each company, and which was lower?",
     "reference_answer": "AMD was lower, by about 5.8 percentage points. NVIDIA 49,510/206,803 = 23.9%. "
                         "AMD has no 'Total liabilities' line, so it must be derived: 76,926 - 62,999 = 13,927; "
                         "13,927/76,926 = 18.1%.",
     "evidence": "NVIDIA balance sheet: total liabilities 49,510, total assets 206,803. AMD balance sheet: total assets 76,926, stockholders' equity 62,999.",
     "difficulty": "hard", "section": "derived ratio requiring a derived input", "answer_type": "short-text"},

    {"id": "d05", "companies": ["NVIDIA", "AMD"], "derived": True,
     "question": "What share of each company's total revenue came from its Data Center segment?",
     "reference_answer": "NVIDIA 193,737/215,938 = about 89.7%. AMD 16,635/34,639 = about 48.0%.",
     "evidence": "NVIDIA Data Center 193,737 of revenue 215,938. AMD Data Center 16,635 of net revenue 34,639.",
     "difficulty": "hard", "section": "segment share, both companies", "answer_type": "short-text"},

    {"id": "d06", "companies": ["NVIDIA"], "derived": True,
     "question": "What was NVIDIA's operating cash flow as a percentage of its net income in fiscal year 2026?",
     "reference_answer": "About 85.6% (102,718 / 120,067).",
     "evidence": "NVIDIA cash flow statement: net cash provided by operating activities 102,718. Income statement: net income 120,067.",
     "difficulty": "hard", "section": "cross-statement ratio", "answer_type": "number"},

    {"id": "d07", "companies": ["NVIDIA"], "derived": True,
     "question": "By how much did NVIDIA's net income increase from fiscal 2024 to fiscal 2026, in dollars and as a multiple?",
     "reference_answer": "It increased by $90,307 million (120,067 - 29,760), about 4.0 times the fiscal 2024 figure.",
     "evidence": "NVIDIA income statement: net income 120,067 (FY2026), 29,760 (FY2024).",
     "difficulty": "hard", "section": "two-year growth", "answer_type": "short-text"},

    {"id": "d08", "companies": ["NVIDIA", "AMD"], "derived": True,
     "question": "What is the combined revenue of both companies for their latest fiscal years, and what share of that combined figure is AMD's?",
     "reference_answer": "$250,577 million combined (215,938 + 34,639). AMD's share is about 13.8% (34,639 / 250,577).",
     "evidence": "NVIDIA revenue 215,938 (FY2026). AMD net revenue 34,639 (FY2025).",
     "difficulty": "hard", "section": "sum then ratio", "answer_type": "short-text"},

    {"id": "d09", "companies": ["AMD"], "derived": True,
     "question": "What was AMD's operating cash flow from continuing operations in fiscal 2025, and what was it as a percentage of net revenue?",
     "reference_answer": "$6,493 million (7,709 total less 1,216 from discontinued operations), about 18.7% of net revenue of $34,639 million.",
     "evidence": "AMD cash flow statement: operating cash flow 7,709 including 1,216 from discontinued operations; continuing 6,493. Net revenue 34,639.",
     "difficulty": "hard", "section": "subtraction then ratio", "answer_type": "short-text"},

    {"id": "d10", "companies": ["NVIDIA"], "derived": True,
     "question": "For NVIDIA in fiscal 2026, what was gross profit less research and development expense, as a percentage of revenue?",
     "reference_answer": "About 62.5%. Gross profit 153,463 less R&D 18,497 = 134,966; 134,966 / 215,938 = 62.5%.",
     "evidence": "NVIDIA income statement: gross profit 153,463, R&D 18,497, revenue 215,938.",
     "difficulty": "hard", "section": "subtraction then ratio", "answer_type": "number"},
]

def bucket(example):
    """Which scoring group an example belongs to. Read the category, don't infer it."""
    if example["answer_type"] == "refusal":
        return "refusal"
    if example.get("derived"):          # arithmetic-heavy items, isolated on purpose
        return "derived"
    return "needs-both" if len(example["companies"]) == 2 else "single-company"

if __name__ == "__main__":
    from collections import Counter
    print(f"Cross set: {len(CROSS_SET)} entries")
    print("  buckets:", dict(Counter(bucket(e) for e in CROSS_SET)))
    
    # single = [e for e in CROSS_SET if len(e["companies"]) <= 1]
    # both   = [e for e in CROSS_SET if len(e["companies"]) == 2]
    # print(f"Cross set: {len(CROSS_SET)} entries")
    # print(f"  single-company: {len(single)}   needs-both: {len(both)}")
    # print("  by difficulty:", dict(Counter(e["difficulty"] for e in CROSS_SET)))
    # for e in CROSS_SET:
    #     tag = "+".join(e["companies"]) or "neither"
    #     print(f"  {e['id']} [{e['difficulty']:<6}] {tag:<12} {e['question'][:56]}")