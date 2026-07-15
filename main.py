from dotenv import load_dotenv
import os

load_dotenv()

print("GOOGLE_API_KEY:", os.getenv("GOOGLE_API_KEY"))
print("LANGSMITH_API_KEY:", os.getenv("LANGSMITH_API_KEY"))
print("LANGSMITH_TRACING:", os.getenv("LANGSMITH_TRACING"))
print("LANGSMITH_PROJECT:", os.getenv("LANGSMITH_PROJECT"))
print("PROJECT_NAME:", os.getenv("PROJECT_NAME"))