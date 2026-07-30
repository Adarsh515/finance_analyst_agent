from dotenv import load_dotenv          # 1
import os                               # 2
from google import genai               # 3

load_dotenv()                                              # 4
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])  # 5

for m in client.models.list():          # 6
    print(m.name)                       # 7