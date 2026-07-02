import os
import dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA

# Load environment
dotenv.load_dotenv()
api_key = os.getenv("LLM_API_KEY")

print(f"Testing meta/llama-3.1-70b-instruct using API key: {api_key[:12]}...")

try:
    client = ChatNVIDIA(
      model="meta/llama-3.1-70b-instruct",
      nvidia_api_key=api_key,
      api_key=api_key,
      temperature=1,
      top_p=0.95,
      max_completion_tokens=8192,
    )
    lc_messages = [{"role": "user", "content": "Hello, are you online? Respond with yes or no."}]
    response = client.invoke(lc_messages)
    print("Success!")
    print("Response content:", response.content)
except Exception as e:
    print("Error calling NVIDIA endpoint:")
    print(e)
