from dotenv import load_dotenv
import os
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash", 
    #temperature=0.2, 
    #max_output_tokens=1024
    )

response = llm.invoke("In one sentence, what is a 10-K filing?")

print(response.content)  