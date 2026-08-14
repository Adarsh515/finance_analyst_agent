import io
import warnings
import pandas as pd
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from langchain_text_splitters import RecursiveCharacterTextSplitter

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def clean_table(df):
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    lines = []
    for _, row in df.iterrows():
        cells = [str(x).strip() for x in row if str(x).strip() and str(x).lower() != "nan"]
        tidy = []
        for c in cells:
            if not tidy or tidy[-1] != c:
                tidy.append(c)
        if tidy:
            lines.append(" | ".join(tidy))
    return "\n".join(lines)

def looks_like_junk(s):
    low = s.lower()
    return any(tok in low for tok in ["iso4217", "xbrli", "us-gaap", "fasb.org", "utr:"])


def has_digit(s):
    return any(ch.isdigit() for ch in s)

def parse_filing(path, company, period, doc_type="10-K"):
    """Split one filing into retrievable pieces.

    Tables are lifted out whole and given a title line, because a bare grid of numbers
    has no words for an embedding to match on - that mistake cost 38 points in Phase 2.
    The narrative is then split around the removed tables so nothing is counted twice.

    doc_type is carried into every piece of text. It used to be the literal string
    "10-K", which is a false statement the moment a 10-Q is ingested - and that false
    statement would sit inside the text the model reads and cites.
    """
    html = open(path, encoding="utf-8").read()
    pieces = []

    for i, df in enumerate(pd.read_html(io.StringIO(html))):
        table_text = clean_table(df)
        if len(table_text) > 60 and has_digit(table_text):
            labeled = table_title(table_text, company, period, doc_type) + "\n" + table_text
            pieces.append({"text": labeled, "type": "table", "source_table": i,
                           "company": company, "period": period, "doc_type": doc_type})

    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        t.decompose()
    narrative = soup.get_text(separator=" ")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    for chunk in splitter.split_text(narrative):
        c = chunk.strip()
        if len(c) > 80 and not looks_like_junk(c):
            pieces.append({"text": f"[{company} {doc_type}, {period}] {c}",
                           "type": "narrative", "company": company,
                           "period": period, "doc_type": doc_type})

    return pieces

def table_title(text, company, period, doc_type="10-K"):
    low = text.lower()
    if ("cost of revenue" in low or "cost of sales" in low) and "gross profit" in low:
        return f"{company} Consolidated Statements of Income (income statement) - {period}, in millions:"
    if "total assets" in low and "total liabilities" in low:
        return f"{company} Consolidated Balance Sheets - {period}, in millions:"
    if "operating activities" in low and "financing activities" in low:
        return f"{company} Consolidated Statements of Cash Flows - {period}, in millions:"
    return f"{company} {doc_type} financial table - {period}:"

if __name__ == "__main__":
    # The filing list lives in corpus.py. It used to be duplicated here, which made
    # it two sources of truth for one fact - add a filing, update one list, forget
    # the other, and this smoke test quietly stops covering the new filing.
    from corpus import DOCS

    for doc in DOCS:
        pieces = parse_filing(doc["path"], doc["company"], doc["period"], doc["doc_type"])
        n_tab = sum(1 for p in pieces if p["type"] == "table")
        print(f"{doc['slug']:16} {len(pieces)} pieces  "
              f"({n_tab} tables, {len(pieces) - n_tab} narrative)")
        print("   first table title:", pieces[0]["text"].split("\n")[0][:100])
        print()
