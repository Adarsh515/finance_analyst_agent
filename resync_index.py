# resync_index.py
# Re-embed ONLY the chunks whose text has actually changed, and prove afterwards that the
# index now matches the parser.
#
# WHY NOT JUST REBUILD. Deleting chroma_db/ and running build_index.py again is the safe,
# obvious move, and it re-embeds every piece of all five filings to fix three of them. This
# script does the same job by comparing what the parser produces NOW against what the index
# holds, and touching only the differences. The comparison is the point: a rebuild assumes
# the rest of the index is fine, while this checks it.
#
# WHY IT IS SAFE. Chunk ids are positional within a filing ("amd-fy2025-piece-23"), so a
# change to a piece's TEXT keeps its id, while a change to the number or ORDER of pieces
# would shift every id after it. That second case is a rebuild, not a resync - so this script
# refuses to run if any filing's piece count has changed, rather than quietly rewriting the
# wrong chunks. It also refuses if any expected id is missing from the index.
#
# Dry run by default. Nothing is embedded until --apply is passed.

import argparse
import warnings

from bs4 import XMLParsedAsHTMLWarning
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

from corpus import DOCS
from parse_filing import parse_filing

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
load_dotenv()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true",
                    help="actually re-embed the changed chunks (costs money); "
                         "without it this only reports")
args = parser.parse_args()

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
store = Chroma(collection_name="sec_filings", embedding_function=embeddings,
               persist_directory="chroma_db")

held = store.get(include=["documents", "metadatas"])
INDEX = dict(zip(held["ids"], held["documents"]))
print(f"index holds {len(INDEX)} chunks\n")

changed, missing, count_mismatch = [], [], []
for doc in DOCS:
    pieces = parse_filing(doc["path"], doc["company"], doc["period"], doc["doc_type"])
    ids = [f"{doc['slug']}-piece-{i}" for i in range(len(pieces))]
    in_index = sum(1 for i in ids if i in INDEX)
    held_for_slug = sum(1 for i in INDEX if i.startswith(doc["slug"] + "-piece-"))
    if held_for_slug != len(pieces):
        count_mismatch.append((doc["slug"], held_for_slug, len(pieces)))
    print(f"  {doc['slug']:16} parsed {len(pieces):4} pieces, index holds {held_for_slug:4}")
    for cid, p in zip(ids, pieces):
        if cid not in INDEX:
            missing.append(cid)
        elif INDEX[cid] != p["text"]:
            changed.append((cid, INDEX[cid], p["text"], p))

print()
if count_mismatch:
    print("REFUSING TO RESYNC - the number of pieces has changed, so the positional ids no")
    print("longer line up and updating by id would rewrite the WRONG chunks:")
    for slug, was, now in count_mismatch:
        print(f"    {slug}: index has {was}, parser now produces {now}")
    print("\nThis is a rebuild, not a resync. Delete chroma_db/ and run build_index.py.")
    raise SystemExit(1)
if missing:
    print(f"REFUSING TO RESYNC - {len(missing)} expected ids are absent from the index, "
          f"e.g. {missing[:3]}")
    raise SystemExit(1)

print(f"chunks whose text changed: {len(changed)}\n")
for cid, old, new, _p in changed:
    print(f"  {cid}")
    print(f"      was : {old.split(chr(10))[0][:100]}")
    print(f"      now : {new.split(chr(10))[0][:100]}")
    # Only the title line should move. If the body differs the parser changed more than
    # intended, and that is worth seeing before paying to embed it.
    if old.split("\n")[1:] != new.split("\n")[1:]:
        print("      NOTE: the BODY changed too, not just the title line")
    print()

if not changed:
    print("nothing to do - the index already matches the parser")
    raise SystemExit(0)

if not args.apply:
    print(f"dry run. {len(changed)} embedding calls would be made. Re-run with --apply.")
    raise SystemExit(0)

ids = [c[0] for c in changed]
texts = [c[2] for c in changed]
metas = [{"company": c[3]["company"], "period": c[3]["period"],
          "doc_type": c[3]["doc_type"], "type": c[3]["type"],
          "source_table": c[3].get("source_table", -1)} for c in changed]
store.add_texts(texts, metadatas=metas, ids=ids)
print(f"re-embedded {len(ids)} chunks")

# Verify rather than assume. add_texts on an existing id is an upsert in this version, but
# "is an upsert" is a belief until it is read back.
after = store.get(ids=ids, include=["documents"])
got = dict(zip(after["ids"], after["documents"]))
bad = [i for i, t in zip(ids, texts) if got.get(i) != t]
print(f"verified {len(ids) - len(bad)}/{len(ids)} chunks now hold the new text")
if bad:
    print(f"  STILL WRONG: {bad}")
    raise SystemExit(1)
print(f"index still holds {store._collection.count()} chunks "
      f"(was {len(INDEX)} - these numbers must match)")
