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

def parse_filing(path, company, period):
    html = open(path, encoding="utf-8").read()
    pieces = []

    for i, df in enumerate(pd.read_html(io.StringIO(html))):
        table_text = clean_table(df)
        if len(table_text) > 60 and has_digit(table_text):
            labeled = table_title(table_text, company, period) + "\n" + table_text
            pieces.append({"text": labeled, "type": "table", "source_table": i,
                           "company": company, "period": period})

    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        t.decompose()
    narrative = soup.get_text(separator=" ")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    for chunk in splitter.split_text(narrative):
        c = chunk.strip()
        if len(c) > 80 and not looks_like_junk(c):
            pieces.append({"text": f"[{company} 10-K, {period}] {c}",
                           "type": "narrative", "company": company, "period": period})

    return pieces

def table_title(text, company, period):
    low = text.lower()
    if ("cost of revenue" in low or "cost of sales" in low) and "gross profit" in low:
        return f"{company} Consolidated Statements of Income (income statement) - {period}, in millions:"
    if "total assets" in low and "total liabilities" in low:
        return f"{company} Consolidated Balance Sheets - {period}, in millions:"
    if "operating activities" in low and "financing activities" in low:
        return f"{company} Consolidated Statements of Cash Flows - {period}, in millions:"
    return f"{company} 10-K financial table - {period}:"

if __name__ == "__main__":
    for path, company, period in [
        ("data/nvidia_10k.htm", "NVIDIA", "fiscal year 2026 (ended January 25, 2026)"),
        ("data/amd_10k.htm",    "AMD",    "fiscal year 2025 (ended December 27, 2025)"),
    ]:
        pieces = parse_filing(path, company, period)
        n_tab = sum(1 for p in pieces if p["type"] == "table")
        print(f"{company}: {len(pieces)} pieces  ({n_tab} tables, {len(pieces) - n_tab} narrative)")
        print("   first table title:", pieces[0]["text"].split("\n")[0][:100])
        print()