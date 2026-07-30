import io
import warnings
import pandas as pd
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

html = open("data/nvidia_10k.htm", encoding="utf-8").read()

tables = pd.read_html(io.StringIO(html))     # one entry per <table> in the filing
print(f"Found {len(tables)} tables in the filing.\n")

# find the income statement (it has both "Revenue" and "Cost of revenue")
for i, t in enumerate(tables):
    text = t.to_string()
    if "Revenue" in text and "Cost of revenue" in text:
        print(f"Table #{i} looks like the Income Statement:\n")
        print(t.to_string()[:1500])
        break

def clean_table(df):
    # drop columns and rows that are entirely empty
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    lines = []
    for _, row in df.iterrows():
        # keep only non-empty cells, as clean strings
        cells = [str(x).strip() for x in row if str(x).strip() and str(x).lower() != "nan"]
        # collapse repeats that sit next to each other (e.g. Revenue|Revenue|Revenue)
        tidy = []
        for c in cells:
            if not tidy or tidy[-1] != c:
                tidy.append(c)
        if tidy:
            lines.append(" | ".join(tidy))
    return "\n".join(lines)


print("\n--- CLEANED TABLE ---")
print(clean_table(tables[10]))