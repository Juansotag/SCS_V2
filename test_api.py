import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
print(f"API Key found: {api_key[:10]}...")

client = OpenAI(api_key=api_key)

try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=5
    )
    print("API Call Successful!")
    print(f"Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"API Call Failed: {e}")
