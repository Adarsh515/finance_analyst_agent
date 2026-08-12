from rag import vectorstore          # jo bhi naam aapke code mein hai

docs = vectorstore.similarity_search("NVIDIA total assets", k=2)

for d in docs:
    print("ID:", repr(getattr(d, "id", None)))
    print("META:", d.metadata)
    print("---")

docs2 = vectorstore.similarity_search("AMD total assets", k=2)
print([d.id for d in docs2])

from rag import detect_companies
print(detect_companies("NVIDIA"), detect_companies("AMD"), detect_companies("Intel"))