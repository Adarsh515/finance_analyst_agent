# probe_titles.py
# Phase 4.5.4 - audit the TITLE LINE this pipeline writes onto every table.
#
# WHY THIS EXISTS. d04 is the one known live failure of Phase 4.4: the answer reported
# AMD's total liabilities as $3,345 million and total assets as $7,546 million. Those are
# real numbers from a real AMD table - the purchase price allocation for an acquisition,
# whose rows read "Total liabilities assumed" and "Total assets acquired". They are not the
# balance sheet, which says $76,926 million.
#
# The generator did not invent that. parse_filing.table_title() titles a table
# "AMD Consolidated Balance Sheets" whenever the words "total assets" and "total liabilities"
# both appear anywhere in it - and "Total assets ACQUIRED" contains "total assets". So the
# retrieved chunk itself carries a false heading, written by us, and every downstream
# component behaves correctly given it:
#
#   the retriever    matched a chunk that says "AMD Consolidated Balance Sheets" - correct
#   the generator    reported figures from a table titled "Consolidated Balance Sheets" - correct
#   the groundedness judge  saw the claim supported by the context AS WRITTEN - correct
#   the human label (grounded=0) judged against the FILING, not the context - a different question
#
# Which is the finding: this was never a retrieval or a judging bug. It is a data bug, and
# the whole 4.4 investigation was looking downstream of it.
#
# This probe re-parses every filing and compares the title the pipeline WOULD write against
# a stricter test - does the table carry a row whose label IS the statement's total, not a
# row that merely contains those words. No API calls, no embeddings, no index. Free.

import io
import re
import warnings

import pandas as pd
from bs4 import XMLParsedAsHTMLWarning

from corpus import DOCS
from parse_filing import clean_table, has_digit, table_title

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# A real statement names its own totals exactly. An acquisition note qualifies them:
# "Total assets acquired", "Total liabilities assumed", "Net assets acquired". The
# qualifier is the whole signal, and substring matching is exactly what destroys it.
EXACT = {
    "balance": (r"^total assets\s*$", r"^total liabilities(?: and stockholders.{0,3} equity)?\s*$"),
    "income": (r"^(total )?(net )?revenue", r"^gross (profit|margin)\s*$"),
    "cashflow": (r"^net cash (provided|used)", r"financing activities"),
}

# Phrases that mark a table as a NOTE about a transaction rather than a primary statement.
NOTE_MARKERS = ("acquired", "assumed", "purchase price", "fair value of net assets",
                "held for sale", "goodwill recognized", "consideration transferred")


def row_labels(table_text):
    """The first cell of every row - the row's label, before any numbers."""
    out = []
    for line in table_text.split("\n"):
        first = line.split("|")[0].strip().lower()
        first = re.sub(r"[^a-z0-9 ]+", " ", first).strip()
        if first:
            out.append(first)
    return out


def strict_kind(table_text):
    """What the table actually is, judged on exact row labels. None if it is not a
    primary financial statement at all."""
    labels = row_labels(table_text)
    for kind, (a, b) in EXACT.items():
        if any(re.search(a, l) for l in labels) and any(re.search(b, l) for l in labels):
            return kind
    return None


def claimed_kind(title):
    low = title.lower()
    if "balance sheet" in low:
        return "balance"
    if "statements of income" in low:
        return "income"
    if "cash flows" in low:
        return "cashflow"
    return None


if __name__ == "__main__":
    total = mislabeled = 0
    rows, missed, agreed = [], [], 0
    for doc in DOCS:
        html = open(doc["path"], encoding="utf-8").read()
        for i, df in enumerate(pd.read_html(io.StringIO(html))):
            text = clean_table(df)
            if len(text) <= 60 or not has_digit(text):
                continue
            total += 1
            title = table_title(text, doc["company"], doc["period"], doc["doc_type"])
            claimed = claimed_kind(title)
            actual = strict_kind(text)
            if claimed is None:
                # The pipeline claims nothing. If the strict test says this IS a statement,
                # the current rule is missing a title - the OPPOSITE error, and it costs
                # retrieval rather than truth. Counted, because a fix that trades one error
                # for the other has not fixed anything.
                if actual is not None:
                    missed.append((doc["slug"], i, actual, text))
                continue
            note = [m for m in NOTE_MARKERS if m in text.lower()]
            if actual != claimed:
                mislabeled += 1
                rows.append((doc["slug"], i, claimed, actual, note, text))
            else:
                agreed += 1

    print("=" * 92)
    print(f"TABLE TITLE AUDIT - {total} tables indexed across {len(DOCS)} filings")
    print("=" * 92)
    print(f"\n  statement titles the strict row-label test CONFIRMS: {agreed}")
    print(f"  statement titles the strict test REJECTS (false headings): {mislabeled}")
    print(f"  statements the current rule fails to title at all:        {len(missed)}\n")
    for slug, i, actual, text in missed:
        print(f"  MISSED TITLE  {slug}  table {i}  looks like: {actual}")
        for line in text.split("\n")[:4]:
            print(f"      | {line[:96]}")
        print()
    for slug, i, claimed, actual, note, text in rows:
        print(f"  {slug}  table {i}")
        print(f"      titled as : {claimed}")
        print(f"      actually  : {actual or 'not a primary statement'}")
        if note:
            print(f"      note markers present: {note}")
        for line in text.split("\n")[:6]:
            print(f"      | {line[:96]}")
        print()

    print("  A false title is worse than a missing one. A missing title costs retrieval a")
    print("  match; a false title is a sentence the model reads, believes and cites.")
