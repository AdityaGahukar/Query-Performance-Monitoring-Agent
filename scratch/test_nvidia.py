import os
import dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA

# Load environment
dotenv.load_dotenv()
api_key = os.getenv("LLM_API_KEY")
model_name = os.getenv("LLM_MODEL", "meta/llama-3.1-8b-instruct")

print(f"Testing Nvidia AI Endpoints ({model_name}) using API key prefix: {api_key[:12]}...")

try:
    client = ChatNVIDIA(
      model=model_name,
      nvidia_api_key=api_key,
      api_key=api_key,
      temperature=1,
      top_p=0.95,
      max_completion_tokens=1024,
    )
    lc_messages = [{"role": "user", "content": "Hello, are you online? Respond with yes or no."}]
    response = client.invoke(lc_messages)
    print("Success!")
    print("Response content:", response.content)
except Exception as e:
    print("Error calling NVIDIA endpoint:")
    print(e)
