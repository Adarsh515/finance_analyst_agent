from dotenv import load_dotenv
from langsmith import Client
from golden_set import GOLDEN_SET

load_dotenv()
client = Client() #auto-reads LANGSMITH_API_KEY

DATASET_NAME ="nvidia-10k-golden"

# create the dataset (handle re-runs so you don't crash on a duplicate name)
if client.has_dataset(dataset_name=DATASET_NAME):
    dataset = client.read_dataset(dataset_name=DATASET_NAME)
else:
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Human-verified Q/A over NVIDIA FY2026 10-K",
    )

client.create_examples(
    dataset_id=dataset.id,
    examples=[
        {
            "inputs":   {"question": e["question"]},
            "outputs":  {"reference_answer": e["reference_answer"]},
            "metadata": {
                "id": e["id"], "difficulty": e["difficulty"],
                "section": e["section"], "answer_type": e["answer_type"],
                "evidence": e["evidence"],
            },
        }
        for e in GOLDEN_SET
    ],
)
print(f"Uploaded {len(GOLDEN_SET)} examples to dataset '{DATASET_NAME}'.")
